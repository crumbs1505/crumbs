# crumbs plugin for Claude Code

Wires [crumbs](https://github.com/crumbs1505/crumbs) into Claude Code as an MCP
server plus a skill, so Claude orients in repos and finds symbols for a fraction
of the tokens — reading full files only at the line ranges crumbs points to.

## Install

```shell
/plugin marketplace add crumbs1505/crumbs
/plugin install crumbs@crumbs
```

The MCP server runs via `uvx --from crumbs-cli crumbs mcp`, so the crumbs engine
is fetched on demand — nothing to install first (requires [uv](https://docs.astral.sh/uv/)).
If you prefer a persistent install (`pipx install crumbs-cli`), change the
server command in `.mcp.json` to `"command": "crumbs", "args": ["mcp"]`.

## What you get

- **MCP tools**: `crumbs_map`, `crumbs_search`, `crumbs_context`, `crumbs_index`,
  `crumbs_list`. Repo paths are auto-indexed on first use — zero setup.
- **Skill** (`/crumbs:crumbs`): tells Claude when to reach for the tools and to
  treat crumbs as an index ("where to look"), reading real code for logic.

## Develop / test locally

```shell
claude --plugin-dir ./plugin
```
