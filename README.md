# energidata-mcp

An MCP server that lets an AI assistant look up Danish electricity data from Energinet's open Energi Data Service: CO2 intensity, day-ahead spot price, and the cleanest or cheapest hours, for price area DK1 or DK2.

**Result:** 10 out of 10 (Claude Sonnet 5.5 through Claude Code 2.1.314, 2026-11-19), after one fix to the server. Before the fix it was 9 out of 10. The miss was my server's arithmetic, not the model.

## Run it

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). From a clone:

```bash
uvx --from . energidata-mcp
```

Claude Code:

```bash
claude mcp add energidata -- uvx --from /absolute/path/to/energidata-mcp energidata-mcp
```

## Tools

| Tool | Answers | Dataset |
|---|---|---|
| `co2_intensity(area, start, end, source)` | g CO2/kWh per hour | `CO2Emis` (measured) or `CO2EmisProg` (forecast) |
| `spot_price(area, start, end, currency)` | DKK or EUR per MWh per hour | `DayAheadPrices` |
| `best_hours(area, metric, start, end, n_hours, consecutive, highest)` | the n cleanest or cheapest hours, or the best block of n back-to-back hours | as above |

Structure: [docs/architecture.md](docs/architecture.md).

## Results

| # | Question (short) | Right answer (plain script) | Agent run 1 (run 2 is after the fix) |
|---|---|---|---|
| 1 | CO2 DK1, 17 Nov, 08:00 | 189.83 g/kWh | right |
| 2 | Cleanest hour DK2, 17 Nov | 01:00 (24.58 g/kWh) | right |
| 3 | Lower daily CO2, 18 Nov | DK1, 120.92 vs DK2 121.48 g/kWh | right |
| 4 | Price DK1, 17 Nov, 18:00 | 1586.96 DKK/MWh | right |
| 5 | Cheapest hour DK2, 18 Nov | 04:00 (829.75 DKK/MWh) | right |
| 6 | Dearest hour DK1, 18 Nov | 18:00, 1574.96 DKK/MWh | right |
| 7 | Cheapest 3 h block DK1, 17 Nov | starts 21:00, mean 1255.58 DKK/MWh | right |
| 8 | Cleanest 3 h block DK2, 18 Nov | starts 08:00, mean 108.19 g/kWh | right (said mean 108.2); run 2 right (108.19) |
| 9 | 4 cheapest hours DK1, 18 Nov, 06 to 22 | 06:00, 11:00, 12:00, 13:00 | right |
| 10 | Day mean DK2, 17 Nov, EUR | 225.69 EUR/MWh | **wrong** (225.68); run 2 right (225.69) |

Test set and failures: [docs/details.md](docs/details.md). Pip install: `pip install .`, then `energidata-mcp`.

## Limits

- **Rate limit.** After very few uncached calls the next got HTTP 429 (about 60 seconds).
- **Hourly values are averages** of the 15-minute price rows and 5-minute CO2 rows.
- **Prices start 2025-10-01.** No taxes, tariffs or grid fees.
- **CO2 data is initial data.** The forecast path (`CO2EmisProg`) is not in the test set.

## Data and licence

Data: Energinet, [Energi Data Service](https://www.energidataservice.dk/), datasets
[CO2Emis](https://www.energidataservice.dk/tso-electricity/CO2Emis),
[CO2EmisProg](https://www.energidataservice.dk/tso-electricity/CO2EmisProg) and
[DayAheadPrices](https://www.energidataservice.dk/tso-electricity/DayAheadPrices).
Published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) per the
[terms and conditions](https://www.energidataservice.dk/terms-and-conditions).
Source: Energinet (www.energidataservice.dk). Changes made here: sub-hourly values are
averaged into hours. Energinet does not endorse this project.

The raw rows for the two test days (17 and 18 November 2026, DK1 and DK2) are stored
unchanged in `eval/data/`, so the tests run offline. The computed answers are in
`eval/expected.json`.

Code: MIT, see `LICENSE`.
