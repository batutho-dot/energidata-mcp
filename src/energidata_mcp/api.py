"""Thin client for the Energi Data Service API (Energinet).

Behaviour measured against the live API on 2026-11-19:
- `start` and `end` are read as Danish local time, `end` is exclusive.
- `limit=0` returns every row in the window.
- The API rate-limits hard: after one uncached call a dataset answers with
  the header `RemainingCalls: 0`, and further calls get HTTP 429
  "Rate limit is exceeded. Try again in N seconds".
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import anyio
import httpx

BASE_URL = "https://api.energidataservice.dk/dataset/"
USER_AGENT = "energidata-mcp (open-source MCP server)"
MAX_WAIT_SECONDS = 70
CACHE_TTL_SECONDS = 300

_cache: dict[tuple[str, str, str, str], tuple[float, list[dict[str, Any]]]] = {}


class ApiError(Exception):
    """The API could not give us the data."""


def _params(start: str, end: str, area: str) -> dict[str, str]:
    return {
        "start": start,
        "end": end,
        "filter": json.dumps({"PriceArea": [area]}),
        "limit": "0",
    }


def _wait_seconds(response: httpx.Response) -> int:
    match = re.search(r"Try again in (\d+) seconds", response.text)
    return int(match.group(1)) + 1 if match else MAX_WAIT_SECONDS


async def fetch_records(dataset: str, start: str, end: str, area: str) -> list[dict[str, Any]]:
    """Return all rows of `dataset` for one price area between start and end (Danish time)."""
    key = (dataset, start, end, area)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]

    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        for attempt in range(2):
            response = await client.get(BASE_URL + dataset, params=_params(start, end, area))
            if response.status_code == 429 and attempt == 0:
                wait = _wait_seconds(response)
                if wait > MAX_WAIT_SECONDS:
                    break
                await anyio.sleep(wait)
                continue
            break

    if response.status_code != 200:
        raise ApiError(f"Energi Data Service answered HTTP {response.status_code}: {response.text[:200]}")
    records = response.json()["records"]
    _cache[key] = (time.monotonic(), records)
    return records
