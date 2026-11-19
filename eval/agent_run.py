"""Ask Claude Code the 10 questions through this MCP server and save its answers and tool calls.

Needs the `claude` CLI, logged in. Each question is a fresh headless session that can use
only this server's three tools (no shell, no web, no files).

    python eval/agent_run.py            # writes eval/agent_results.json
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / ".cache"
MODEL = "sonnet"
SUFFIX = " Use the energidata tools. Times are Danish local time. Answer in two sentences at most, with the numbers."


def server_command() -> list[str]:
    exe = shutil.which("energidata-mcp", path=str(Path(sys.executable).parent))
    return [exe] if exe else [sys.executable, "-m", "energidata_mcp.server"]


def ask(question: str, config: Path) -> dict:
    cmd = [
        "claude", "-p", question + SUFFIX,
        "--mcp-config", str(config), "--strict-mcp-config",
        "--tools", "",
        "--allowedTools", "mcp__energidata",
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence",
        "--model", MODEL,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=900)
    calls, answer, model = [], None, None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            model = event.get("model")
        if event.get("type") == "assistant":
            for block in event["message"].get("content", []):
                if block.get("type") == "tool_use":
                    calls.append({"tool": block["name"].removeprefix("mcp__energidata__"), "args": block["input"]})
        if event.get("type") == "result":
            answer = event.get("result")
    return {"model": model, "tool_calls": calls, "answer": answer, "exit_code": proc.returncode}


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    config = CACHE / "mcp.json"
    cmd = server_command()
    config.write_text(json.dumps({"mcpServers": {"energidata": {"command": cmd[0], "args": cmd[1:]}}}), encoding="utf-8")
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    only = {int(a) for a in sys.argv[1:]}
    out_path = HERE / "agent_results.json"
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for q in questions:
        if only and q["id"] not in only:
            continue
        print(f"Q{q['id']} ...", flush=True)
        results[str(q["id"])] = {"question": q["question"], **ask(q["question"], config)}
        print(f"  {len(results[str(q['id'])]['tool_calls'])} tool calls: {results[str(q['id'])]['answer']}", flush=True)
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
