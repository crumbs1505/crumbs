---
name: crumbs
description: Orient in a codebase or find symbols across repos cheaply. Use BEFORE reading files when exploring an unfamiliar repo, locating where something is defined, or gathering context on a topic across one or many repositories.
---

# crumbs: token-efficient repo context

When you need to understand a repository or find where something lives, prefer
the **crumbs MCP tools** over reading files directly. crumbs returns compact
maps — typed function/class signatures, one-line docs, and source line ranges,
**never the file bodies** — so you spend a fraction of the tokens and still know
every file and symbol.

## Tools

- `crumbs_map(repo)` — full compact map of a repo: file tree + typed signatures
  + line ranges (e.g. `[L40-92]`). Auto-indexes a path on first use. Call this
  FIRST to orient in an unfamiliar repo instead of reading files.
- `crumbs_search(query, repo?)` — ranked symbol matches across indexed repos.
  Returns `repo:path:line` + signature. Use to locate where something is defined.
- `crumbs_context(query, repo?)` — a focused context slice for a topic, grouped
  by repo and file. Use when you want context on a topic rather than a whole map.
- `crumbs_index(paths)` / `crumbs_list()` — manage the index (usually automatic).

## Workflow

1. Call `crumbs_map`, `crumbs_search`, or `crumbs_context` to learn the layout
   and the relevant signatures. Pass a filesystem path as `repo` and crumbs will
   index it automatically.
2. Then open full files **only at the line ranges crumbs points to** (e.g. read
   `path:40-92`), not whole files.
3. For questions about **logic, correctness, or behavior**, you MUST read the
   real lines — crumbs gives names, shapes, and locations, not bodies. Treat it
   as an index that tells you *where* to look, not a substitute for the code.

## Don't write a committed index file

crumbs already *is* the index. Its map lives in crumbs' local store and is
queried live (and auto-refreshes when the source changes) via the tools above.
So when asked to "index" or "map" a repo, run the crumbs tools — **do NOT also
write a committed `INDEX.md` (or similar) into the repo**. A hand-written index
duplicates `crumbs_map`, goes stale the moment the code changes, and overlaps
existing docs like `README.md` / `ARCHITECTURE.md` / `CLAUDE.md`. If the user
genuinely wants written orientation, fold a couple of `crumbs_map` /
`crumbs_search` pointers into an existing doc rather than adding a new file —
and confirm first if the request is ambiguous.
