"""Pure functions: turn raw API rows into hourly values and pick hours. No network here."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

MAX_WINDOW_DAYS = 31


def parse_window(start: str, end: str | None) -> tuple[str, str]:
    """Check a Danish-local-time window and return it as API strings (YYYY-MM-DDTHH:MM).

    `start` is a date (2026-11-17) or date and time (2026-11-17T06:00).
    `end` is exclusive; when left out the window runs to the next midnight.
    """
    start_dt = _parse(start, "start")
    if end is None:
        end_dt = datetime.combine(start_dt.date() + timedelta(days=1), datetime.min.time())
    else:
        end_dt = _parse(end, "end")
    if end_dt <= start_dt:
        raise ValueError(f"end ({end_dt:%Y-%m-%dT%H:%M}) must be after start ({start_dt:%Y-%m-%dT%H:%M}).")
    if end_dt - start_dt > timedelta(days=MAX_WINDOW_DAYS):
        raise ValueError(f"Window is longer than {MAX_WINDOW_DAYS} days; ask for a shorter one.")
    return f"{start_dt:%Y-%m-%dT%H:%M}", f"{end_dt:%Y-%m-%dT%H:%M}"


def _parse(text: str, name: str) -> datetime:
    text = text.strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"{name}={text!r} is not a date like 2026-11-17 or 2026-11-17T06:00.")


def hourly(records: list[dict[str, Any]], utc_key: str, dk_key: str, value_key: str) -> list[dict[str, Any]]:
    """Average sub-hourly rows into hours. Grouped on the UTC hour so DST changes stay correct."""
    groups: dict[str, dict[str, Any]] = {}
    for row in records:
        value = row.get(value_key)
        if value is None:
            continue
        utc_hour = row[utc_key][:13] + ":00"
        group = groups.setdefault(utc_hour, {"hour_dk": row[dk_key][:13] + ":00", "values": []})
        group["values"].append(float(value))
    hours = []
    for utc_hour in sorted(groups):
        values = groups[utc_hour]["values"]
        hours.append(
            {
                "hour_dk": groups[utc_hour]["hour_dk"],
                "hour_utc": utc_hour,
                "value": sum(values) / len(values),
                "samples": len(values),
            }
        )
    return hours


def mean(hours: list[dict[str, Any]]) -> float | None:
    """Mean of the hourly values (each hour counts once), rounded to 2 decimals.

    Averages the unrounded hourly values: averaging already-rounded ones was off by 0.01
    on 2 of 10 test questions in the first agent run.
    """
    if not hours:
        return None
    return round(sum(h["value"] for h in hours) / len(hours), 2)


def rounded(hours: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy of the hours with values rounded to 2 decimals, for output only."""
    return [{**h, "value": round(h["value"], 2)} for h in hours]


def pick_hours(hours: list[dict[str, Any]], n: int, consecutive: bool, highest: bool = False) -> list[dict[str, Any]]:
    """Return the n lowest (or highest) hours. Ties go to the earliest hour.

    consecutive=True returns the block of n back-to-back hours with the best mean.
    """
    if n < 1:
        raise ValueError("n_hours must be at least 1.")
    if n > len(hours):
        raise ValueError(f"Asked for {n} hours but the window only has data for {len(hours)}.")
    sign = -1 if highest else 1

    if not consecutive:
        order = sorted(range(len(hours)), key=lambda i: (sign * hours[i]["value"], i))
        return [hours[i] for i in sorted(order[:n])]

    best: tuple[float, int] | None = None
    for i in range(len(hours) - n + 1):
        block = hours[i : i + n]
        if not _back_to_back(block):
            continue
        score = sign * sum(h["value"] for h in block) / n
        if best is None or score < best[0]:
            best = (score, i)
    if best is None:
        raise ValueError(f"No run of {n} back-to-back hours with data in this window.")
    return hours[best[1] : best[1] + n]


def _back_to_back(block: list[dict[str, Any]]) -> bool:
    times = [datetime.strptime(h["hour_utc"], "%Y-%m-%dT%H:%M") for h in block]
    return all(b - a == timedelta(hours=1) for a, b in zip(times, times[1:]))


def window_has_ended(end: str, now_dk: datetime | None = None) -> bool:
    """True when the window's end is in the past, judged in Danish local time."""
    if now_dk is None:
        now_dk = datetime.now(ZoneInfo("Europe/Copenhagen")).replace(tzinfo=None)
    return datetime.strptime(end, "%Y-%m-%dT%H:%M") <= now_dk
