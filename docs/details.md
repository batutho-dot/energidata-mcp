# Details

DK1 is West Denmark, DK2 is East Denmark.

**Question:** can a model answer "when is power cleanest or cheapest in Denmark?" with three small tools instead of the raw API? I checked 10 questions against answers a plain script computed independently. The server tests reproduce all 10.

**Score:** 10 out of 10 (Claude Sonnet 5.5 through Claude Code 2.1.314, 2026-11-19), after one fix. Before the fix: **9 out of 10**.

## Install

`uvx --from . energidata-mcp` starts the server on stdio. With pip: `pip install .`, then the command `energidata-mcp`.

## Example

Asked for the cheapest 3-hour block in DK1 on 17 November 2026, the model calls
`best_hours(area="DK1", metric="price", start="2026-11-17", n_hours=3, consecutive=True)`
and gets (shortened):

```json
{
  "area": "DK1", "metric": "price", "unit": "DKK/MWh", "consecutive": true,
  "picked": [
    {"hour_dk": "2026-11-17T21:00", "value": 1361.03, "samples": 4},
    {"hour_dk": "2026-11-17T22:00", "value": 1280.32, "samples": 4},
    {"hour_dk": "2026-11-17T23:00", "value": 1125.38, "samples": 4}
  ],
  "mean_of_picked": 1255.58, "mean_of_window": 1563.5, "hours_in_window": 24
}
```

It answers "21:00 to 00:00, mean 1255.58 DKK/MWh", which matches question 7.

## Tests

[![tests](https://github.com/batutho-dot/energidata-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/batutho-dot/energidata-mcp/actions/workflows/tests.yml)

```bash
pip install -e ".[dev]"
pytest            # 48 tests, offline: the API is never called
python verify.py  # compile, tests, answer script, and the installed server over stdio
```

They cover the 10 eval questions, the error paths (bad date, empty or too-long window, unknown area, too many hours, API down), the daylight-saving hour that happens twice, and the HTTP client on a mock transport. GitHub Actions runs them on every push on Linux (Python 3.11 and 3.13) and Windows.

## Files

| File | Job |
|---|---|
| `src/energidata_mcp/api.py` | Fetches rows with a 30 s timeout, caches 5 minutes, retries once on HTTP 429 and twice on a timeout or HTTP 5xx |
| `src/energidata_mcp/core.py` | Time window, 5-minute or 15-minute rows into hours, lowest or highest hours |
| `src/energidata_mcp/server.py` | The three tools, built with the [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/) (`MCPServer`, v2.3) |

`co2_intensity` with `source="auto"` picks measured data for past windows. Times are Danish local time. A window runs from start (inclusive) to end (exclusive); without `end` you get the rest of the start day. Diagrams and a file and line table: [architecture.md](architecture.md).

## The test set

`eval/questions.json` holds 10 questions on two fixed past days (17 and 18 November 2026). `eval/answers.py` computes the answers from the API with the standard library only. It groups by the Danish-time hour string where the server groups by UTC hour, so it checks the arithmetic instead of repeating it.

```bash
python eval/answers.py        # writes eval/expected.json; downloads raw rows into eval/data/ if missing
pytest                        # the 10 questions through an in-memory MCP client, plus error paths
python eval/agent_run.py      # asks Claude Code each question, records answers and tool calls
python eval/score.py          # scores eval/agent_results.json against eval/expected.json
```

The window is complete: 576 of 576 five-minute CO2 rows and 192 of 192 fifteen-minute price rows per area.

## Agent run

Main table: [README](../README.md#results). The run used `claude -p` with only this server's three tools, one fresh session per question. Rule set before the run: right when every required hour and number appears in the answer.

Every question took 1 tool call, except question 3 (2 calls, one per area). The model never needed a retry. Raw answers: `eval/agent_results_run1.json` (run 1) and `eval/agent_results.json` (run 1 with questions 8 and 10 replaced by run 2). My own Claude Code instructions were loaded, so some answers end with "Next:" or "Verified:" lines.

I also checked the extra numbers the model volunteered. All were right except one: in run 2, question 10 said the day's low was 187.98 at 04:00. The real low was 156.40 at 23:00 (run 1 had it right). A strict grader would fail run 2's question 10, which makes it 9 of 10 again.

| # | Tool calls |
|---|---|
| 1 | `co2_intensity` |
| 2 | `best_hours` |
| 3 | `co2_intensity` x2 |
| 4 | `spot_price` |
| 5 | `best_hours` |
| 6 | `best_hours` (highest) |
| 7 | `best_hours` (consecutive) |
| 8 | `best_hours` (consecutive) |
| 9 | `best_hours` |
| 10 | `spot_price` |

## What did not work

- **My server rounded too early.** It rounded each hourly value to 2 decimals, then averaged. Means were 0.01 off on 2 of 10 questions (225.68 instead of 225.69, 108.20 instead of 108.19), and run 1 lost question 10. My tests allowed a 0.01 tolerance and missed it. Now means use unrounded values and the tests demand an exact match. The old code fails 2 of the tightened tests.
- **A side claim was wrong** though the scored number was right (question 10, run 2). Nothing returns a window's minimum and maximum, so the model scanned 24 numbers and picked wrong. A `min`/`max` field would remove that step.
- **The rate limit sets the pace.** My first answer script hit HTTP 429 twice and waited 62 seconds each time.
- **Older MCP examples use `FastMCP`.** Version 2 of the official Python SDK uses `MCPServer`. I wrote the server from the current docs.

## More on limits

- **Rate limit.** After one call a dataset answered with `RemainingCalls: 0`, and the next call got HTTP 429 "Try again in N seconds" (about 60 seconds). The server caches for 5 minutes and waits once, so a question that needs two areas can take a minute. It is not built for polling.
- **Averages.** The day average is the mean of the hourly values.
- **Old prices** are in the discontinued `Elspotprices` dataset.
- **CO2 data is initial data.** Energinet says the 5-minute series comes from upscaled real-time measurements and that errors "will generally not be corrected". The corrected figures are in `DeclarationGridEmission`, which I do not use. A forecast has no fixed answer, so `CO2EmisProg` is not in the test set.
- **"Now"** comes from the machine's clock in Danish time, only to choose measured or forecast CO2 when `source="auto"`.
