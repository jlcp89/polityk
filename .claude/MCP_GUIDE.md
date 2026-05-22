# MCP Server Guide

## Active Servers

- **context7** — documentation lookups (lightweight; keep always on)
- **github** — Issues, PRs, repo metadata (requires `GITHUB_TOKEN` env var; the AFK loop and `/to-issues` use this)
- **filesystem** — repo-rooted filesystem access at `/home/jl2/work/politic/polityk`
- **sqlite** — read-only inspector for `data/polityk.db` (the canonical SQLite store; created when the first scraper runs)

## Managing Context Budget

MCP servers consume context even when idle. For optimal performance:

1. **Disable github MCP** when working offline or doing local-only work.
2. **Disable sqlite MCP** when not working on the data layer or query optimization.
3. **Disable filesystem MCP** if it's redundant with native Read/Glob (it usually is for single-repo work).
4. **Keep context7** always enabled — documentation lookups are lightweight.

### How to Toggle

In Claude Code settings → Search and tools:

- Toggle individual MCP servers on/off per conversation.
- Or edit `.mcp.json` at the project root to comment out server blocks.

## Adding New Servers

Manually add to `.mcp.json`:

```json
{
  "server-name": {
    "command": "npx",
    "args": ["-y", "@scope/mcp-server@latest"]
  }
}
```

## Project-specific notes

- The `sqlite` MCP points at `data/polityk.db`, which **does not exist yet** on a fresh clone. It will be created the first time `pipeline/scripts/scrape.py` runs against any data source. Until then, the MCP will warn — that's expected.
- DuckDB has no first-party MCP server as of 0.10.x; query it directly with `uv run python -c "import duckdb; ..."` or the DuckDB CLI.
