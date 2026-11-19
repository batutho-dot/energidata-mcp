# Hourly lookups

- **What it does:** returns hourly CO2 intensity (g/kWh) or day-ahead price (DKK or EUR per MWh) for DK1 or DK2 in a Danish-time window.
- **How to reach it:** MCP tools `co2_intensity` and `spot_price`.
- **How verify drives it:** step `tests`, `tests/test_server.py` Q1, Q3, Q4, Q10 through the in-memory client, with the API swapped for rows cached in `eval/.cache/`.
- **End state that proves it worked:** hourly values and day means equal `eval/expected.json` to 0.01; Q1 hour has 12 of 12 samples; Q10 day has 24 hours.
- **Gotchas:** the live API is never called by verify (rate limit of about one uncached call per dataset per minute). The forecast path (`CO2EmisProg`) has no fixed answer and is not covered.
