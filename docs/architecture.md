# Architecture

How `energidata-mcp` is put together, drawn from the code as it is. Line numbers point at
the main function or class of each box. Both diagrams render on GitHub.

## (a) Structure: who calls whom

Boxes are the files of the server plus the two things outside it: the MCP client (Claude)
and Energinet's API. Under each name are a few keywords for what the box does. An arrow
reads "uses". The dashed arrow is a test-only swap.

```mermaid
flowchart LR
    client["Claude (MCP client)<br/>asks a question, picks a tool, reads the JSON"]
    sdk["MCP Python SDK<br/>MCPServer, stdio, tool schemas, ToolError"]
    server["server.py<br/>3 tools, input checks, shape the answer"]
    core["core.py<br/>time window, hourly means, pick best hours"]
    api["api.py<br/>HTTP GET, 5 min cache, retry on 429"]
    ext["Energi Data Service API<br/>Energinet, CO2Emis, CO2EmisProg, DayAheadPrices"]
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
| Claude (MCP client) | outside this repository | n/a | The AI app that starts the server, reads its tool list and decides which tool to call. |
| MCP Python SDK | `src/energidata_mcp/server.py:17` | `mcp = MCPServer("energidata", ...)` | The official library that speaks the protocol over stdin and stdout and turns Python errors of type `ToolError` into tool errors the model can read. |
| server.py | `src/energidata_mcp/server.py:63` | `co2_intensity` (also `spot_price` at :81, `best_hours` at :98, `main` at :135) | Defines the three tools, turns bad input into `ToolError`, and builds the JSON answer from the hours that `core.py` returns. |
| core.py | `src/energidata_mcp/core.py:40` | `hourly` (also `parse_window` at :12, `pick_hours` at :80) | Pure functions with no network: check the time window, average 5-minute or 15-minute rows into hours, pick the lowest or highest hours. |
| api.py | `src/energidata_mcp/api.py:47` | `fetch_records` | Fetches the rows for one dataset, window and price area, keeps them for 5 minutes, and waits and retries once on HTTP 429. |
| Energi Data Service API | `src/energidata_mcp/api.py:21` | `BASE_URL` | Energinet's open data service that holds the CO2 and price rows; it is not part of this repository. |
| tests/test_server.py | `tests/test_server.py:43` | `client` fixture (offline swap at :33) | Calls the tools through an in-memory MCP client, with the API call replaced by rows saved in `eval/.cache/`, and checks the 10 questions against `eval/expected.json`. |

Not drawn: `eval/` (the plain-script answer checker and the Claude Code agent run) and
`verify.py` are scripts around the server, not part of the path a request takes.

## (b) One request: `spot_price` from question to answer

The path of a single call, here "what was the spot price in DK1 on 17 November?". The other
two tools differ only in which dataset they read and what they do with the hours.

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
    Note over T,K: a bad date or an empty window raises ValueError, server.py turns it into ToolError
    Note over T: _price_hours refuses a start before 2025-10-01
    T->>A: fetch_records("DayAheadPrices", start, end, area)
    alt same request answered less than 300 seconds ago
        A-->>T: rows from the cache
    else not in the cache
        A->>E: GET dataset DayAheadPrices with start, end, PriceArea filter, limit 0
        E-->>A: HTTP 200 with JSON records
        opt the first answer is HTTP 429
            A->>A: sleep for the seconds Energinet names (at most 70)
            A->>E: GET again, once
            E-->>A: HTTP 200 with JSON records
        end
        Note over A: any other HTTP status raises ApiError, server.py turns it into ToolError
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
| Tool entry | `src/energidata_mcp/server.py` | `spot_price` at :81 | Receives the arguments the model chose. |
| Window check | `src/energidata_mcp/core.py` | `parse_window` at :12 | Accepts a date or date and time, defaults `end` to the next midnight, rejects windows over 31 days. |
| Price guard and fetch | `src/energidata_mcp/server.py` | `_price_hours` at :43 | Refuses starts before 2025-10-01, then calls the API client through `_fetch` at :50. |
| HTTP call, cache, retry | `src/energidata_mcp/api.py` | `fetch_records` at :47 | Returns cached rows if fresh, otherwise one GET, with one wait and retry on HTTP 429. |
| Parsing | `src/energidata_mcp/core.py` | `hourly` at :40 | Groups rows by UTC hour and averages them, so daylight saving changes stay correct. |
| Answer | `src/energidata_mcp/server.py` | `spot_price` at :81 | Adds the mean, the rounded hours and the credit line, and returns the dict. |
