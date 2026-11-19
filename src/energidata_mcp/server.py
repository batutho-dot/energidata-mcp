"""MCP server: Danish electricity CO2 intensity and day-ahead prices from Energi Data Service."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from energidata_mcp import api, core

CREDIT = "Source: Energinet (www.energidataservice.dk), CC BY 4.0. Hourly values are averages computed by this server."

Area = Literal["DK1", "DK2"]
Co2Source = Literal["auto", "measured", "forecast"]

mcp = MCPServer(
    "energidata",
    instructions=(
        "Danish electricity data from Energinet's Energi Data Service. "
        "DK1 is West Denmark (Jutland, Funen), DK2 is East Denmark (Zealand, Copenhagen). "
        "All times in and out are Danish local time. A window is start (inclusive) to end (exclusive); "
        "leave end out to get the rest of the start day."
    ),
)


def _window(start: str, end: str | None) -> tuple[str, str]:
    try:
        return core.parse_window(start, end)
    except ValueError as err:
        raise ToolError(str(err)) from err


async def _co2_hours(area: str, start: str, end: str, source: str) -> tuple[str, list[dict[str, Any]]]:
    if source == "auto":
        source = "measured" if core.window_has_ended(end) else "forecast"
    dataset = "CO2Emis" if source == "measured" else "CO2EmisProg"
    records = await _fetch(dataset, start, end, area)
    return dataset, core.hourly(records, "Minutes5UTC", "Minutes5DK", "CO2Emission")


async def _price_hours(area: str, start: str, end: str, currency: str) -> list[dict[str, Any]]:
    if start < "2025-10-01":
        raise ToolError("Prices are only served from 2025-10-01 (the DayAheadPrices dataset).")
    records = await _fetch("DayAheadPrices", start, end, area)
    return core.hourly(records, "TimeUTC", "TimeDK", f"DayAheadPrice{currency}")


async def _fetch(dataset: str, start: str, end: str, area: str) -> list[dict[str, Any]]:
    try:
        return await api.fetch_records(dataset, start, end, area)
    except (api.ApiError, OSError) as err:
        raise ToolError(f"Could not get {dataset} data: {err}") from err


def _no_data(hours: list[dict[str, Any]], what: str, start: str, end: str) -> None:
    if not hours:
        raise ToolError(f"No {what} data for {start} to {end}. Prices for tomorrow appear around 13:00 Danish time.")


@mcp.tool()
async def co2_intensity(area: Area, start: str, end: str | None = None, source: Co2Source = "auto") -> dict[str, Any]:
    """CO2 intensity of electricity consumed in a Danish price area, per hour, in g CO2 per kWh.

    start/end: Danish local time, '2026-11-17' or '2026-11-17T06:00'; end is exclusive and
    defaults to the next midnight. source: 'measured' (CO2Emis), 'forecast' (CO2EmisProg), or
    'auto' = measured when the window is in the past, otherwise forecast.
    Each hour is the mean of the 5-minute values in it; 'samples' says how many there were (12 = complete).
    """
    start, end = _window(start, end)
    dataset, hours = await _co2_hours(area, start, end, source)
    _no_data(hours, dataset, start, end)
    return {
        "area": area, "start": start, "end": end, "dataset": dataset, "unit": "g CO2/kWh",
        "mean_of_hours": core.mean(hours), "hours": core.rounded(hours), "credit": CREDIT,
    }


@mcp.tool()
async def spot_price(area: Area, start: str, end: str | None = None, currency: Literal["DKK", "EUR"] = "DKK") -> dict[str, Any]:
    """Day-ahead (spot) electricity price in a Danish price area, per hour, per MWh, before taxes and tariffs.

    start/end: Danish local time, '2026-11-17' or '2026-11-17T06:00'; end is exclusive and
    defaults to the next midnight. Each hour is the mean of the four 15-minute prices in it.
    Data from the DayAheadPrices dataset, available from 2025-10-01; tomorrow's prices appear around 13:00.
    """
    start, end = _window(start, end)
    hours = await _price_hours(area, start, end, currency)
    _no_data(hours, "price", start, end)
    return {
        "area": area, "start": start, "end": end, "dataset": "DayAheadPrices", "unit": f"{currency}/MWh",
        "mean_of_hours": core.mean(hours), "hours": core.rounded(hours), "credit": CREDIT,
    }


@mcp.tool()
async def best_hours(
    area: Area,
    metric: Literal["co2", "price"],
    start: str,
    end: str | None = None,
    n_hours: int = 1,
    consecutive: bool = False,
    highest: bool = False,
    currency: Literal["DKK", "EUR"] = "DKK",
    co2_source: Co2Source = "auto",
) -> dict[str, Any]:
    """Find the cleanest (lowest CO2) or cheapest hours in a window, e.g. when to run a heat pump or charge a car.

    metric: 'co2' or 'price'. n_hours: how many hours to pick. consecutive=True returns the block of
    n back-to-back hours with the lowest mean instead of the n lowest single hours.
    highest=True flips it to the dirtiest / most expensive hours. Times are Danish local time.
    """
    start, end = _window(start, end)
    if metric == "co2":
        dataset, hours = await _co2_hours(area, start, end, co2_source)
        unit = "g CO2/kWh"
    else:
        dataset, unit = "DayAheadPrices", f"{currency}/MWh"
        hours = await _price_hours(area, start, end, currency)
    _no_data(hours, dataset, start, end)
    try:
        picked = core.pick_hours(hours, n_hours, consecutive, highest)
    except ValueError as err:
        raise ToolError(str(err)) from err
    return {
        "area": area, "metric": metric, "start": start, "end": end, "dataset": dataset, "unit": unit,
        "consecutive": consecutive, "highest": highest, "picked": core.rounded(picked),
        "mean_of_picked": core.mean(picked), "mean_of_window": core.mean(hours),
        "hours_in_window": len(hours), "credit": CREDIT,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
