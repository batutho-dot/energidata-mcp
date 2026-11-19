"""The HTTP client against a mock transport: retries, rate limit, timeouts, bad answers. No network."""

from __future__ import annotations

import httpx
import pytest

from energidata_mcp import api

ROWS = [{"TimeUTC": "2026-11-17T00:00:00", "TimeDK": "2026-11-17T01:00:00", "DayAheadPriceDKK": 1.0}]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def slept(monkeypatch):
    """Clear the cache and record sleeps instead of waiting."""
    api._cache.clear()
    waits = []

    async def no_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(api.anyio, "sleep", no_sleep)
    return waits


def serve(monkeypatch, *answers):
    """Answer each request with the next item: an httpx.Response, or an exception to raise."""
    queue = list(answers)
    seen = []

    def handler(request):
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(api, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


async def fetch():
    return await api.fetch_records("DayAheadPrices", "2026-11-17T00:00", "2026-11-18T00:00", "DK1")


@pytest.mark.anyio
async def test_ok_sends_filter_and_caches(monkeypatch):
    seen = serve(monkeypatch, httpx.Response(200, json={"records": ROWS}))
    assert await fetch() == ROWS
    assert await fetch() == ROWS  # the second call is served from the cache
    assert len(seen) == 1
    assert seen[0].url.params["filter"] == '{"PriceArea": ["DK1"]}'
    assert seen[0].url.params["limit"] == "0"


@pytest.mark.anyio
async def test_429_waits_the_time_asked_then_retries(monkeypatch, slept):
    serve(
        monkeypatch,
        httpx.Response(429, text="Rate limit is exceeded. Try again in 7 seconds."),
        httpx.Response(200, json={"records": ROWS}),
    )
    assert await fetch() == ROWS
    assert slept == [8]


@pytest.mark.anyio
async def test_429_twice_is_a_clear_error(monkeypatch):
    serve(monkeypatch, httpx.Response(429, text="Try again in 3 seconds"), httpx.Response(429, text="Try again in 3 seconds"))
    with pytest.raises(api.ApiError, match="rate limit"):
        await fetch()


@pytest.mark.anyio
async def test_429_with_too_long_wait_gives_up_at_once(monkeypatch, slept):
    serve(monkeypatch, httpx.Response(429, text="Try again in 600 seconds"))
    with pytest.raises(api.ApiError, match="rate limit"):
        await fetch()
    assert slept == []


@pytest.mark.anyio
async def test_server_error_is_retried(monkeypatch):
    serve(monkeypatch, httpx.Response(503, text="busy"), httpx.Response(200, json={"records": ROWS}))
    assert await fetch() == ROWS


@pytest.mark.anyio
async def test_server_error_that_persists_is_reported(monkeypatch):
    seen = serve(monkeypatch, *[httpx.Response(502, text="bad gateway")] * 3)
    with pytest.raises(api.ApiError, match="HTTP 502"):
        await fetch()
    assert len(seen) == 3


@pytest.mark.anyio
async def test_timeout_is_retried_then_reported(monkeypatch):
    seen = serve(monkeypatch, *[httpx.ReadTimeout("slow")] * 3)
    with pytest.raises(api.ApiError, match="no answer"):
        await fetch()
    assert len(seen) == 3


@pytest.mark.anyio
async def test_connection_error_then_success(monkeypatch):
    serve(monkeypatch, httpx.ConnectError("refused"), httpx.Response(200, json={"records": ROWS}))
    assert await fetch() == ROWS


@pytest.mark.anyio
async def test_client_error_is_not_retried(monkeypatch):
    seen = serve(monkeypatch, httpx.Response(400, text="bad filter"))
    with pytest.raises(api.ApiError, match="HTTP 400"):
        await fetch()
    assert len(seen) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("body", [b"not json", b'{"total": 0}', b'{"records": "nope"}'])
async def test_malformed_answer_is_an_error(monkeypatch, body):
    serve(monkeypatch, httpx.Response(200, content=body))
    with pytest.raises(api.ApiError, match="records"):
        await fetch()
