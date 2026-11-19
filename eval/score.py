"""Score the agent's answers (eval/agent_results.json) against eval/expected.json.

A question counts as right when every required item appears in the answer text:
hours as "HH:00", numbers rounded to 2, 1 or 0 decimals (thousand separators ignored).
For question 3 the lower area must be named first of the two.

    python eval/score.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent


def numbers_in(text: str) -> set[str]:
    text = re.sub(r"(?<=\d)[,  ](?=\d{3}\b)", "", text)
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def has_number(text: str, value: float) -> bool:
    found = numbers_in(text)
    return any(f"{value:.{d}f}" in found for d in (2, 1, 0))


def required(qid: str, exp: dict) -> list[tuple[str, object]]:
    if qid == "3":
        return [("lower", exp["lower"]), ("num", exp["DK1"]), ("num", exp["DK2"])]
    items: list[tuple[str, object]] = []
    for key in ("hour", "start_hour"):
        if key in exp:
            items.append(("hour", exp[key]))
    for h in exp.get("hours", []):
        items.append(("hour", h))
    if "value" in exp and qid not in ("2", "5"):
        items.append(("num", exp["value"]))
    if "mean" in exp and qid == "7":
        items.append(("num", exp["mean"]))
    return items


def check(text: str, kind: str, want: object) -> bool:
    if kind == "hour":
        return want in text
    if kind == "num":
        return has_number(text, float(want))
    if kind == "lower":
        other = "DK2" if want == "DK1" else "DK1"
        m = re.search(r"\b(DK[12])\b[^.]*\blower\b|\blower\b[^.]*?\b(DK[12])\b", text)
        named = (m.group(1) or m.group(2)) if m else None
        return named == want or (named is None and text.find(want) < text.find(other))
    raise ValueError(kind)


def main() -> None:
    expected = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))["answers"]
    results = json.loads((HERE / "agent_results.json").read_text(encoding="utf-8"))
    score = 0
    rows = []
    for qid, exp in expected.items():
        res = results.get(qid, {})
        text = res.get("answer") or ""
        misses = [f"{k}={w}" for k, w in required(qid, exp) if not check(text, k, w)]
        ok = not misses
        score += ok
        calls = ", ".join(c["tool"] for c in res.get("tool_calls", []))
        rows.append((qid, ok, len(res.get("tool_calls", [])), calls, misses))
    for qid, ok, n, calls, misses in rows:
        print(f"Q{qid}: {'right' if ok else 'WRONG'} | {n} calls: {calls}" + (f" | missing {misses}" if misses else ""))
    print(f"score: {score}/{len(expected)}")


if __name__ == "__main__":
    main()
