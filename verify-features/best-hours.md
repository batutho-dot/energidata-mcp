# Cleanest or cheapest hours

- **What it does:** picks the n lowest (or highest) hours, or the best block of n back-to-back hours, by CO2 or price.
- **How to reach it:** MCP tool `best_hours`.
- **How verify drives it:** step `tests`, Q2, Q5, Q6, Q7, Q8, Q9.
- **End state that proves it worked:** picked hours and block means equal `eval/expected.json`.
- **Gotchas:** ties go to the earliest hour in both the server and the answer script; a window with a data gap cannot form a block across the gap.
