"""Compute the right answers to eval/questions.json straight from the API. No model, no MCP.

Standard library only, and deliberately written separately from the server code
(it groups by the Danish-time hour string instead of the UTC hour), so it is an
independent check on the server's arithmetic.

    python eval/answers.py          # downloads raw data once into eval/.cache/, writes eval/expected.json
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / ".cache"
WINDOW = ("2026-11-17T00:00", "2026-11-19T00:00")
DATASETS = {
    "co2": ("CO2Emis", "Minutes5DK", "CO2Emission"),
    "DKK": ("DayAheadPrices", "TimeDK", "DayAheadPriceDKK"),
    "EUR": ("DayAheadPrices", "TimeDK", "DayAheadPriceEUR"),
}


def raw(dataset: str, area: str) -> list[dict]:
    """Rows for one dataset and area over WINDOW, cached on disk so the API is hit once."""
    path = CACHE / f"{dataset}_{area}_{WINDOW[0][:10]}_{WINDOW[1][:10]}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    query = urllib.parse.urlencode(
        {"start": WINDOW[0], "end": WINDOW[1], "filter": json.dumps({"PriceArea": [area]}), "limit": 0}
    )
    url = f"https://api.energidataservice.dk/dataset/{dataset}?{query}"
    for _ in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "energidata-mcp eval"})) as r:
                rows = json.load(r)["records"]
            break
        except urllib.error.HTTPError as err:
            if err.code != 429:
                raise
            wait = int(re.search(r"(\d+) seconds", err.read().decode()).group(1)) + 2
            print(f"  rate limited on {dataset}, waiting {wait} s")
            time.sleep(wait)
    else:
        raise RuntimeError(f"gave up on {dataset} {area}")
    CACHE.mkdir(exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def hours(series: str, area: str, day: str) -> dict[str, float]:
    """{'08:00': mean value} for one Danish day, from the sub-hourly rows."""
    dataset, time_key, value_key = DATASETS[series]
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in raw(dataset, area):
        stamp = row[time_key]
        if stamp.startswith(day) and row[value_key] is not None:
            buckets[stamp[11:13] + ":00"].append(row[value_key])
    return {h: sum(v) / len(v) for h, v in sorted(buckets.items())}


def day_mean(h: dict[str, float]) -> float:
    return sum(h.values()) / len(h)


def best_block(h: dict[str, float], n: int) -> tuple[str, float]:
    keys = list(h)
    blocks = [(sum(h[k] for k in keys[i : i + n]) / n, keys[i]) for i in range(len(keys) - n + 1)]
    value, start = min(blocks)  # ties go to the earlier start because keys sort by time
    return start, value


def answer(q: dict) -> dict:
    kind, day = q["kind"], q["day"]
    if kind == "co2_hour":
        return {"value": round(hours("co2", q["area"], day)[q["hour"]], 2), "unit": "g/kWh"}
    if kind == "co2_min_hour":
        h = hours("co2", q["area"], day)
        best = min(h, key=lambda k: (h[k], k))
        return {"hour": best, "value": round(h[best], 2), "unit": "g/kWh"}
    if kind == "co2_compare_day":
        m = {a: round(day_mean(hours("co2", a, day)), 2) for a in ("DK1", "DK2")}
        return {"lower": min(m, key=m.get), "DK1": m["DK1"], "DK2": m["DK2"], "unit": "g/kWh"}
    if kind == "price_hour":
        return {"value": round(hours(q["currency"], q["area"], day)[q["hour"]], 2), "unit": "DKK/MWh"}
    if kind in ("price_min_hour", "price_max_hour"):
        h = hours(q.get("currency", "DKK"), q["area"], day)
        sign = 1 if kind == "price_min_hour" else -1
        best = min(h, key=lambda k: (sign * h[k], k))
        return {"hour": best, "value": round(h[best], 2), "unit": "DKK/MWh"}
    if kind in ("price_block", "co2_block"):
        series = "co2" if kind == "co2_block" else q["currency"]
        start, value = best_block(hours(series, q["area"], day), q["n"])
        return {"start_hour": start, "mean": round(value, 2), "unit": "g/kWh" if series == "co2" else "DKK/MWh"}
    if kind == "price_n_cheapest":
        h = {k: v for k, v in hours("DKK", q["area"], day).items() if q["from"] <= k < q["to"]}
        picked = sorted(sorted(h, key=lambda k: (h[k], k))[: q["n"]])
        return {"hours": picked, "values": [round(h[k], 2) for k in picked], "unit": "DKK/MWh"}
    if kind == "price_day_mean":
        return {"value": round(day_mean(hours(q["currency"], q["area"], day)), 2), "unit": "EUR/MWh"}
    raise ValueError(kind)


def completeness() -> dict[str, dict[str, int]]:
    """How many sub-hourly rows each dataset has per area over WINDOW (expected: 576 x 5-min, 192 x 15-min)."""
    return {f"{d}_{a}": len(raw(d, a)) for d in ("CO2Emis", "DayAheadPrices") for a in ("DK1", "DK2")}


def main() -> None:
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    expected = {str(q["id"]): answer(q) for q in questions}
    out = {"window": WINDOW, "rows": completeness(), "answers": expected}
    (HERE / "expected.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for q in questions:
        print(f"Q{q['id']}: {expected[str(q['id'])]}")
    print("rows:", out["rows"])


if __name__ == "__main__":
    main()
