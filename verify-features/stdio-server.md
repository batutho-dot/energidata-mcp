# Server over stdio

- **What it does:** the `energidata-mcp` command starts the server the way Claude Code or Claude Desktop does.
- **How to reach it:** `energidata-mcp` after `pip install .`, or `uvx --from . energidata-mcp`.
- **How verify drives it:** step `stdio` launches the installed command as a subprocess, lists tools, calls `spot_price` with a bad date.
- **End state that proves it worked:** exactly the 3 tools; the bad date returns `is_error` with "not a date".
- **Gotchas:** needs the package installed in the Python that runs verify. The `uvx` path was checked by hand, not by verify.
