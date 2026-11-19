"""Thin client for the Energi Data Service API (Energinet).

Behaviour measured against the live API on 2026-11-19:
- `start` and `end` are read as Danish local time, `end` is exclusive.
- `limit=0` returns every row in the window.
- The API rate-limits hard: after one uncached call a dataset answers with
  the header `RemainingCalls: 0`, and further calls get HTTP 429
  "Rate limit is exceeded. Try again in N seconds".

Failure handling: a 429 waits the time the API asks for (once, at most
MAX_WAIT_SECONDS); a timeout, a dropped connection or an HTTP 5xx is retried
up to TRANSIENT_RETRIES times with a short back-off. Everything else that goes
wrong becomes an ApiError with a message a model can read.
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
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
TRANSIENT_RETRIES = 2
BACKOFF_SECONDS = 2.0

_cache: dict[tuple[str, str, str, str], tuple[float, list[dict[str, Any]]]] = {}


class ApiError(Exception):
    """The API could not give us the data."""


def _client() -> httpx.AsyncClient:
    """One place to build the HTTP client, so tests can swap in a mock transport."""
    return httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})


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


async def _get(dataset: str, params: dict[str, str]) -> httpx.Response:
    """GET with the retry rules in the module docstring."""
    rate_limited_once = False
    transient_left = TRANSIENT_RETRIES
    async with _client() as client:
        while True:
            try:
                response = await client.get(BASE_URL + dataset, params=params)
            except httpx.TransportError as err:  # timeout, refused or dropped connection
                if transient_left == 0:
                    raise ApiError(f"no answer from Energi Data Service ({type(err).__name__}); try again later") from err
                transient_left -= 1
                await anyio.sleep(BACKOFF_SECONDS)
                continue
            if response.status_code == 429 and not rate_limited_once:
                wait = _wait_seconds(response)
                if wait > MAX_WAIT_SECONDS:
                    return response
                rate_limited_once = True
                await anyio.sleep(wait)
                continue
            if response.status_code >= 500 and transient_left > 0:
                transient_left -= 1
                await anyio.sleep(BACKOFF_SECONDS)
                continue
            return response


async def fetch_records(dataset: str, start: str, end: str, area: str) -> list[dict[str, Any]]:
    """Return all rows of `dataset` for one price area between start and end (Danish time)."""
    key = (dataset, start, end, area)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]

    response = await _get(dataset, _params(start, end, area))
    if response.status_code == 429:
        raise ApiError("Energi Data Service rate limit hit (HTTP 429); wait about a minute and ask again")
    if response.status_code != 200:
        raise ApiError(f"Energi Data Service answered HTTP {response.status_code}: {response.text[:200]}")
    try:
        records = response.json()["records"]
    except (ValueError, KeyError, TypeError) as err:
        raise ApiError("Energi Data Service sent an answer without a 'records' list") from err
    if not isinstance(records, list):
        raise ApiError("Energi Data Service sent an answer without a 'records' list")
    _cache[key] = (time.monotonic(), records)
    return records
