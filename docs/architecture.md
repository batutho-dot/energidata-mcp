# Architecture

Line numbers point at the main function or class of each box.

## (a) Structure

Arrows read "uses". The dashed arrow is a test-only swap.

```mermaid
flowchart LR
    client["Claude (MCP client)<br/>picks a tool, reads the JSON"]
    sdk["MCP Python SDK<br/>MCPServer, stdio, ToolError"]
    server["server.py<br/>3 tools, input checks, shape the answer"]
    core["core.py<br/>time window, hourly means, pick best hours"]
    api["api.py<br/>HTTP GET, timeouts, 5 min cache, retries"]
    ext["Energi Data Service API<br/>CO2Emis, CO2EmisProg, DayAheadPrices"]
    tests["tests/test_server.py<br/>pytest, in-memory client, offline, 10 questions"]

    client -->|"stdio: tool call"| sdk
    sdk -->|"runs the tool function"| server
    server -->|"parse_window, hourly, mean, pick_hours"| core
    server -->|"await fetch_records"| api
    api -->|"HTTPS GET with PriceArea filter"| ext
    tests -->|"in-memory Client"| sdk
    tests -.->|"monkeypatch fetch_records"| api

    classDef outside fill:#eee,stroke:#888,stroke-dasharray: 4 3
    class client,ext outside
```

| Box | File | Main function or class | What it does |
|---|---|---|---|
| Claude (MCP client) | outside this repository | n/a | Starts the server and decides which tool to call. |
| MCP Python SDK | `src/energidata_mcp/server.py:17` | `mcp = MCPServer("energidata", ...)` | Speaks the protocol over stdin and stdout, turns `ToolError` into an error the model can read. |
| server.py | `src/energidata_mcp/server.py:63` | `co2_intensity` (also `spot_price` at :81, `best_hours` at :98, `main` at :135) | The three tools. Bad input becomes `ToolError`. |
| core.py | `src/energidata_mcp/core.py:40` | `hourly` (also `parse_window` at :12, `pick_hours` at :80) | Pure functions, no network: window check, hourly means, best hours. |
| api.py | `src/energidata_mcp/api.py:88` | `fetch_records` (retry loop `_get` at :60) | Fetches rows, caches 5 minutes, retries once on HTTP 429 and twice on a timeout or HTTP 5xx. |
| Energi Data Service API | `src/energidata_mcp/api.py:26` | `BASE_URL` | Energinet's open data service. |
| tests/test_server.py | `tests/test_server.py:38` | `client` fixture (offline swap at :28) | In-memory MCP client on rows saved in `eval/data/`, checked against `eval/expected.json`. |

## (b) One request: `spot_price`

"What was the spot price in DK1 on 17 November?" The other two tools differ only in dataset and what they do with the hours.

```mermaid
sequenceDiagram
    participant C as Claude (MCP client)
    participant S as MCP SDK
    participant T as server.py
    participant K as core.py
    participant A as api.py
    participant E as Energi Data Service API

    C->>S: tools/call spot_price with area, start, end, currency
    S->>T: spot_price(area, start, end, currency)
    T->>K: parse_window(start, end)
    K-->>T: start and end as YYYY-MM-DDTHH:MM
    Note over T,K: bad date or empty window: ValueError, then ToolError
    Note over T: _price_hours refuses a start before 2025-10-01
    T->>A: fetch_records("DayAheadPrices", start, end, area)
    alt same request answered less than 300 seconds ago
        A-->>T: rows from the cache
    else not in the cache
        A->>E: GET dataset DayAheadPrices with start, end, PriceArea filter, limit 0
        E-->>A: HTTP 200 with JSON records
        opt the first answer is HTTP 429
            A->>A: sleep as long as Energinet says (at most 70 s)
            A->>E: GET again, once
            E-->>A: HTTP 200 with JSON records
        end
        Note over A: any other HTTP status: ApiError, then ToolError
        A->>A: store the rows in the cache
        A-->>T: records
    end
    T->>K: hourly(records, "TimeUTC", "TimeDK", "DayAheadPriceDKK")
    K-->>T: one value per hour, the mean of the 15-minute rows
    T->>K: mean(hours) and rounded(hours)
    K-->>T: mean of hours and hours rounded to 2 decimals
    T-->>S: dict with area, unit, mean_of_hours, hours, credit
    S-->>C: result as text and structured JSON
```

| Step | File | Line | What happens |
|---|---|---|---|
| Tool entry | `src/energidata_mcp/server.py` | `spot_price` at :81 | Receives the arguments. |
| Window check | `src/energidata_mcp/core.py` | `parse_window` at :12 | Accepts a date or date and time, defaults `end` to the next midnight, rejects windows over 31 days. |
| Price guard | `src/energidata_mcp/server.py` | `_price_hours` at :43 | Refuses starts before 2025-10-01, then fetches through `_fetch` at :50. |
| HTTP, cache, retry | `src/energidata_mcp/api.py` | `fetch_records` at :88 | Fresh cached rows, otherwise one GET with the retries above. |
| Parsing | `src/energidata_mcp/core.py` | `hourly` at :40 | Groups by UTC hour, so daylight saving stays correct. |
| Answer | `src/energidata_mcp/server.py` | `spot_price` at :81 | Adds the mean, the rounded hours and the credit line. |
