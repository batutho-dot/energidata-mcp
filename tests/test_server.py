"""Call the MCP tools through an in-memory client and check them against eval/expected.json.

The API call is swapped for the raw rows that eval/answers.py saved in eval/data/
(committed to the repository), so the tests run offline and never touch the API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client

from energidata_mcp import api
from energidata_mcp.server import mcp

EVAL = Path(__file__).parent.parent / "eval"
DATA = EVAL / "data"
EXPECTED = json.loads((EVAL / "expected.json").read_text(encoding="utf-8"))["answers"]
DK_KEY = {"CO2Emis": "Minutes5DK", "DayAheadPrices": "TimeDK"}

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def fake_fetch(dataset, start, end, area):
        (path,) = DATA.glob(f"{dataset}_{area}_*.json")
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in rows if start <= r[DK_KEY[dataset]][:16] < end]

    monkeypatch.setattr(api, "fetch_records", fake_fetch)


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


async def call(client, tool, **args):
    result = await client.call_tool(tool, args)
    assert not result.is_error, result.content
    return result.structured_content


def hour(h):
    return h["hour_dk"][11:16]


@pytest.mark.anyio
async def test_q1_co2_hour(client):
    out = await call(client, "co2_intensity", area="DK1", start="2026-11-17T08:00", end="2026-11-17T09:00", source="measured")
    assert out["hours"][0]["value"] == pytest.approx(EXPECTED["1"]["value"], abs=1e-9)
    assert out["hours"][0]["samples"] == 12


@pytest.mark.anyio
async def test_q2_cleanest_hour(client):
    out = await call(client, "best_hours", area="DK2", metric="co2", start="2026-11-17")
    assert hour(out["picked"][0]) == EXPECTED["2"]["hour"]


@pytest.mark.anyio
async def test_q3_compare_areas(client):
    means = {a: (await call(client, "co2_intensity", area=a, start="2026-11-18"))["mean_of_hours"] for a in ("DK1", "DK2")}
    assert means["DK1"] == pytest.approx(EXPECTED["3"]["DK1"], abs=1e-9)
    assert means["DK2"] == pytest.approx(EXPECTED["3"]["DK2"], abs=1e-9)
    assert min(means, key=means.get) == EXPECTED["3"]["lower"]


@pytest.mark.anyio
async def test_q4_price_hour(client):
    out = await call(client, "spot_price", area="DK1", start="2026-11-17T18:00", end="2026-11-17T19:00")
    assert out["hours"][0]["value"] == pytest.approx(EXPECTED["4"]["value"], abs=1e-9)


@pytest.mark.anyio
async def test_q5_cheapest_hour(client):
    out = await call(client, "best_hours", area="DK2", metric="price", start="2026-11-18")
    assert hour(out["picked"][0]) == EXPECTED["5"]["hour"]


@pytest.mark.anyio
async def test_q6_most_expensive_hour(client):
    out = await call(client, "best_hours", area="DK1", metric="price", start="2026-11-18", highest=True)
    assert hour(out["picked"][0]) == EXPECTED["6"]["hour"]
    assert out["picked"][0]["value"] == pytest.approx(EXPECTED["6"]["value"], abs=1e-9)


@pytest.mark.anyio
async def test_q7_cheapest_block(client):
    out = await call(client, "best_hours", area="DK1", metric="price", start="2026-11-17", n_hours=3, consecutive=True)
    assert hour(out["picked"][0]) == EXPECTED["7"]["start_hour"]
    assert out["mean_of_picked"] == pytest.approx(EXPECTED["7"]["mean"], abs=1e-9)


@pytest.mark.anyio
async def test_q8_cleanest_block(client):
    out = await call(client, "best_hours", area="DK2", metric="co2", start="2026-11-18", n_hours=3, consecutive=True)
    assert hour(out["picked"][0]) == EXPECTED["8"]["start_hour"]
    assert out["mean_of_picked"] == pytest.approx(EXPECTED["8"]["mean"], abs=1e-9)


@pytest.mark.anyio
async def test_q9_n_cheapest(client):
    out = await call(client, "best_hours", area="DK1", metric="price", start="2026-11-18T06:00", end="2026-11-18T22:00", n_hours=4)
    assert [hour(h) for h in out["picked"]] == EXPECTED["9"]["hours"]


@pytest.mark.anyio
async def test_q10_day_mean_eur(client):
    out = await call(client, "spot_price", area="DK2", start="2026-11-17", currency="EUR")
    assert out["mean_of_hours"] == pytest.approx(EXPECTED["10"]["value"], abs=1e-9)
    assert len(out["hours"]) == 24


@pytest.mark.anyio
async def test_bad_date_is_a_tool_error(client):
    result = await client.call_tool("spot_price", {"area": "DK1", "start": "17/11/2026"})
    assert result.is_error
    assert "not a date" in result.content[0].text


async def error_text(client, tool, **args):
    result = await client.call_tool(tool, args)
    assert result.is_error, result.structured_content
    return result.content[0].text


@pytest.mark.anyio
async def test_end_before_start_is_a_tool_error(client):
    text = await error_text(client, "co2_intensity", area="DK1", start="2026-11-18T10:00", end="2026-11-18T09:00")
    assert "must be after start" in text


@pytest.mark.anyio
async def test_window_over_31_days_is_a_tool_error(client):
    text = await error_text(client, "spot_price", area="DK1", start="2026-01-01", end="2026-03-01")
    assert "longer than 31 days" in text


@pytest.mark.anyio
async def test_prices_before_dataset_start_are_refused(client):
    text = await error_text(client, "spot_price", area="DK1", start="2025-09-30")
    assert "2025-10-01" in text


@pytest.mark.anyio
async def test_unknown_area_is_refused(client):
    await error_text(client, "spot_price", area="SE3", start="2026-11-17")


@pytest.mark.anyio
async def test_too_many_hours_is_a_tool_error(client):
    text = await error_text(client, "best_hours", area="DK1", metric="price", start="2026-11-17T20:00", n_hours=5)
    assert "only has data for 4" in text


@pytest.mark.anyio
async def test_zero_hours_is_a_tool_error(client):
    text = await error_text(client, "best_hours", area="DK1", metric="price", start="2026-11-17", n_hours=0)
    assert "at least 1" in text


@pytest.mark.anyio
async def test_empty_window_is_a_tool_error(client):
    text = await error_text(client, "spot_price", area="DK1", start="2026-11-20")
    assert "No price data" in text


@pytest.mark.anyio
async def test_api_failure_becomes_a_tool_error(client, monkeypatch):
    async def broken(dataset, start, end, area):
        raise api.ApiError("Energi Data Service answered HTTP 503: down")

    monkeypatch.setattr(api, "fetch_records", broken)
    text = await error_text(client, "spot_price", area="DK1", start="2026-11-17")
    assert "Could not get DayAheadPrices data" in text and "503" in text


@pytest.mark.anyio
async def test_lists_exactly_three_tools(client):
    names = {t.name for t in (await client.list_tools()).tools}
    assert names == {"co2_intensity", "spot_price", "best_hours"}
