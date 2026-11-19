"""Unit tests for the pure functions in core.py. No network, no MCP."""

from __future__ import annotations

from datetime import datetime

import pytest

from energidata_mcp import core


def test_parse_window_date_only_runs_to_next_midnight():
    assert core.parse_window("2026-11-17", None) == ("2026-11-17T00:00", "2026-11-18T00:00")


def test_parse_window_accepts_space_and_seconds():
    assert core.parse_window("2026-11-17 06:00", "2026-11-17T08:00:00") == ("2026-11-17T06:00", "2026-11-17T08:00")


@pytest.mark.parametrize("bad", ["17/11/2026", "", "tomorrow", "2026-13-01"])
def test_parse_window_rejects_bad_dates(bad):
    with pytest.raises(ValueError, match="not a date"):
        core.parse_window(bad, None)


def test_parse_window_rejects_empty_and_long_windows():
    with pytest.raises(ValueError, match="must be after start"):
        core.parse_window("2026-11-17T06:00", "2026-11-17T06:00")
    with pytest.raises(ValueError, match="longer than"):
        core.parse_window("2026-01-01", "2026-02-02")


def _rows(triples):
    return [{"utc": u, "dk": d, "v": v} for u, d, v in triples]


def test_hourly_averages_and_counts_samples():
    rows = _rows([
        ("2026-11-17T07:00:00", "2026-11-17T08:00:00", 10.0),
        ("2026-11-17T07:30:00", "2026-11-17T08:30:00", 20.0),
        ("2026-11-17T08:00:00", "2026-11-17T09:00:00", 5.0),
    ])
    hours = core.hourly(rows, "utc", "dk", "v")
    assert [h["hour_dk"] for h in hours] == ["2026-11-17T08:00", "2026-11-17T09:00"]
    assert hours[0]["value"] == 15.0 and hours[0]["samples"] == 2


def test_hourly_skips_missing_values():
    rows = _rows([
        ("2026-11-17T07:00:00", "2026-11-17T08:00:00", None),
        ("2026-11-17T07:05:00", "2026-11-17T08:05:00", 4.0),
    ])
    assert core.hourly(rows, "utc", "dk", "v")[0]["samples"] == 1


def test_hourly_keeps_the_repeated_dst_hour_apart():
    # 2026-10-25: Danish clocks go back, so 02:00 local time happens twice (00:00 and 01:00 UTC).
    rows = _rows([
        ("2026-10-25T00:00:00", "2026-10-25T02:00:00", 1.0),
        ("2026-10-25T01:00:00", "2026-10-25T02:00:00", 3.0),
    ])
    hours = core.hourly(rows, "utc", "dk", "v")
    assert [h["value"] for h in hours] == [1.0, 3.0]


def _hours(values, start_hour=0):
    return [
        {
            "hour_dk": f"2026-11-17T{start_hour + i:02d}:00",
            "hour_utc": f"2026-11-17T{start_hour + i:02d}:00",
            "value": v,
            "samples": 4,
        }
        for i, v in enumerate(values)
    ]


def test_mean_uses_unrounded_values():
    assert core.mean([{"value": 1.0049}, {"value": 1.0049}, {"value": 1.0149}]) == 1.01  # rounding first would give 1.0
    assert core.mean([]) is None


def test_pick_hours_lowest_highest_and_ties():
    hours = _hours([5, 1, 1, 9])
    assert [h["value"] for h in core.pick_hours(hours, 2, False)] == [1, 1]
    assert [h["value"] for h in core.pick_hours(hours, 1, False, highest=True)] == [9]
    assert core.pick_hours(_hours([2, 2]), 1, False)[0]["hour_dk"] == "2026-11-17T00:00"


def test_pick_hours_consecutive_block():
    block = core.pick_hours(_hours([9, 1, 2, 9, 0]), 2, True)
    assert [h["value"] for h in block] == [1, 2]


def test_pick_hours_consecutive_skips_gaps():
    hours = _hours([1]) + _hours([1], start_hour=5)
    with pytest.raises(ValueError, match="back-to-back"):
        core.pick_hours(hours, 2, True)


def test_pick_hours_bounds():
    with pytest.raises(ValueError, match="at least 1"):
        core.pick_hours(_hours([1]), 0, False)
    with pytest.raises(ValueError, match="only has data for 1"):
        core.pick_hours(_hours([1]), 2, False)


def test_window_has_ended():
    now = datetime(2026, 11, 19, 12, 0)
    assert core.window_has_ended("2026-11-19T12:00", now)
    assert not core.window_has_ended("2026-11-19T13:00", now)
