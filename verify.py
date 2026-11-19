"""Check this repository end to end. Prints `verify: PASS` or `verify: FAIL at <step>: <reason>`.

Steps (cheapest first, stops at the first failure, writes nothing into the repository):
  1. compile   every .py file compiles
  2. tests     pytest (the 10 eval questions through an in-memory MCP client, error paths,
               the HTTP client on a mock transport); skips count as failure
  3. answers   eval/answers.py recomputed in memory from eval/data/ matches eval/expected.json
  4. stdio     the installed `energidata-mcp` command starts over stdio, lists exactly the 3 tools,
               and turns a bad date into a tool error (no network needed)

Needs: the dev install (`pip install -e .[dev]`). The raw API rows for the test days are committed
in eval/data/.
No network in any step; a live API run is not part of verify (the API rate-limits hard).

    python verify.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = {"co2_intensity", "spot_price", "best_hours"}


class Fail(Exception):
    pass


def step_compile() -> str:
    files = [p for d in ("src", "eval", "tests") for p in (ROOT / d).rglob("*.py")] + [ROOT / "verify.py"]
    for path in files:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as err:
            raise Fail(f"{path.relative_to(ROOT)}: {err}") from err
    return f"{len(files)} files"


def step_tests() -> str:
    if not any((ROOT / "eval" / "data").glob("*.json")):
        raise Fail("eval/data/ is empty; run python eval/answers.py once")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr.strip()[-200:]
    if proc.returncode != 0 or "skipped" in last:
        raise Fail(last)
    return last


def step_answers() -> str:
    spec = importlib.util.spec_from_file_location("answers", ROOT / "eval" / "answers.py")
    answers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(answers)
    questions = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    known = json.loads((ROOT / "eval" / "expected.json").read_text(encoding="utf-8"))["answers"]
    got = {str(q["id"]): answers.answer(q) for q in questions}
    wrong = [k for k in known if got.get(k) != known[k]]
    if wrong or len(got) != len(known):
        raise Fail(f"differs from eval/expected.json on questions {wrong}")
    return f"{len(got)}/{len(known)} match"


def step_stdio() -> str:
    exe = shutil.which("energidata-mcp", path=sysconfig.get_path("scripts"))
    if not exe:
        raise Fail("energidata-mcp command not installed in this environment")

    async def run() -> str:
        from mcp import Client, StdioServerParameters

        async with Client(StdioServerParameters(command=exe)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            if names != TOOLS:
                raise Fail(f"tools are {sorted(names)}, expected {sorted(TOOLS)}")
            result = await client.call_tool("spot_price", {"area": "DK1", "start": "17/11/2026"})
            if not result.is_error or "not a date" not in result.content[0].text:
                raise Fail("bad date did not come back as a tool error")
        return "3 tools listed, bad date -> tool error"

    return asyncio.run(run())


STEPS = [("compile", step_compile), ("tests", step_tests), ("answers", step_answers), ("stdio", step_stdio)]


def main() -> int:
    sys.dont_write_bytecode = True
    print(f"verify-repo: {ROOT}")
    for name, fn in STEPS:
        try:
            detail = fn()
        except Fail as err:
            print(f"verify: FAIL at {name}: {err}")
            return 1
        except Exception as err:  # an unexpected crash is a failure of that step, not a pass
            print(f"verify: FAIL at {name}: {type(err).__name__}: {err}")
            return 1
        print(f"{name}: ok ({detail})")
    print("verify: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
