# crumbs

**Local, token-efficient cross-repo context for LLMs.**

`crumbs` indexes your repositories into compact *context crumbs* — file maps and
symbol signatures (typed function/class/type declarations + one-line docs + line
ranges), **never the full file bodies**. An assistant like Claude can then
understand many repos at once by reading a tiny map instead of paying tokens to
read the entire source tree.

Indexing this very tool produces a map of **~1,200 tokens** standing in for
**~8,400 tokens** of source — an **~86% reduction** — while still naming every
file and symbol. Each symbol carries its full type signature and a source line
range (e.g. `def build_parser() -> ArgumentParser [L125-168]`), so the assistant
can open *just that slice* of a file rather than the whole thing.

- 🪶 **Zero dependencies.** Pure Python 3.8+ stdlib. Runs on any device.
- 🔒 **Fully local.** Crumbs live in `~/.crumbs`. Nothing leaves your machine.
- 🧠 **Cross-repo.** Search and pull context across every repo you've indexed.
- 🎯 **High signal.** Python is parsed via `ast`; JS/TS/Go/Rust/etc. via fast
  regex. Skips `node_modules`, `.git`, build dirs, lockfiles, and binaries.
- 🗂️ **Progressive maps.** Large repos render as a directory overview first;
  drill into a subtree with `--path` so you never load what you don't need.
- 🔎 **Smart search.** Splits `camelCase`/`snake_case` and stems lightly, then
  ranks with TF-IDF — `login` finds `loginUser`, and rare terms rank higher.
- 🚪 **API-first.** Symbols are tagged public/internal (Python `_`, JS `export`,
  Go capitalization, Rust `pub`); maps lead with the exported surface.

## Install

The distribution is named `crumbs-cli`; it provides the `crumbs` command.

```bash
pipx install crumbs-cli       # isolated, on your PATH (recommended)
# or, no install at all:
uvx --from crumbs-cli crumbs --help
# or, from a clone:
pip install -e .              # dev install
python3 -m crumbs --help      # run without installing
```

## Usage

```bash
crumbs index ~/code/my-api ~/code/my-web   # index one or more repos
crumbs list                                # show indexed repos + stats
crumbs map my-api --stats                  # compact map of one repo (+ token estimate)
crumbs map my-api --path src/auth          # expand just one directory subtree
crumbs map my-api --overview               # force the directory-level overview
crumbs search "auth token"                 # rank matching symbols across all repos
crumbs context "rate limiting" --repo my-api   # LLM-ready context slice
crumbs refresh                             # re-index everything
crumbs remove my-web                       # drop a repo from the index
```

A repo can be referenced by name, id, or path.

### Progressive maps for large repos

`crumbs map` adapts to repo size. A small repo prints in full; a large one
(more than ~40 files) opens as a **directory overview** — each directory with its
file and symbol counts but no signatures — so the map itself never becomes the
token bloat it exists to eliminate. Pick a directory and expand only that one:

```bash
crumbs map my-api                  # overview for a large repo, full map for a small one
crumbs map my-api --path src/auth  # drill into a subtree
crumbs map my-api --full           # force the complete map regardless of size
```

Within each file, symbols are ordered **public API first**, with internals
demoted and marked `·internal` — so the first tokens you read are the ones you're
most likely to call, and the exported surface survives truncation.

## Use with Claude Code (MCP)

crumbs ships an MCP server (`crumbs mcp`) so an MCP host — Claude Code, Claude
Desktop, or any MCP client — can call it as native tools. It speaks the MCP wire
protocol over stdio with **zero dependencies** (no SDK).

**One-command install (Claude Code plugin):**

```shell
/plugin marketplace add crumbs1505/crumbs
/plugin install crumbs@crumbs
```

This bundles the MCP server and a skill; repo paths are auto-indexed on first
use. See [`plugin/`](plugin/) for details.

**Manual registration** (e.g. in a project `.mcp.json` or your Claude Code config):

```jsonc
{
  "mcpServers": {
    "crumbs": { "command": "uvx", "args": ["--from", "crumbs-cli", "crumbs", "mcp"] }
  }
}
```

`uvx` fetches and runs crumbs on demand, so nothing needs to be installed first.
(If you installed via `pipx`, use `"command": "crumbs", "args": ["mcp"]` instead.)

The server exposes five model-controlled tools — `crumbs_map`, `crumbs_search`,
`crumbs_context`, `crumbs_index`, `crumbs_list` — and auto-indexes a repo path on
first use, so there is no manual setup step. `crumbs_map` accepts a `path`
argument to expand a single subtree (and returns a directory overview for large
repos), and `crumbs_search` applies the same camelCase/snake_case splitting,
stemming, and TF-IDF ranking as the CLI.

## Workflow with Claude

1. `crumbs index` the repos you work across (once, or on a `crumbs refresh` cron).
2. Ask Claude to run `crumbs map <repo>` or `crumbs context "<topic>"` instead of
   reading whole files. It gets the structure and the relevant symbols for a
   fraction of the tokens, then reads full files only where it actually needs to.

## How it stays cheap

| | Full repo read | `crumbs map` |
|---|---|---|
| What | every byte of every file | file tree + typed signatures + 1-line docs + line ranges |
| Bodies | yes | no |
| Cost | grows with codebase | grows with *interface* size |

Because every symbol records its line range, the follow-up step is cheap too: the
assistant reads `path:start-end` for the one function it needs instead of opening
the entire file.

Storage layout (`~/.crumbs`, override with `CRUMBS_HOME`):

```
registry.json        # id -> {name, path, indexed_at, stats}
repos/<id>.json      # full crumb data for one repo
```

## Supported languages

Python (AST), JavaScript/TypeScript, Go, Rust, and a generic declaration
matcher for Java, Ruby, PHP, C/C++, C#, Swift, Kotlin. Markdown is indexed by
heading. Anything else is skipped from symbol extraction but still ignored
safely.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Releasing

Releases are published to [PyPI](https://pypi.org/project/crumbs-cli/) automatically by
CI ([`.github/workflows/publish.yml`](.github/workflows/publish.yml)) whenever a version
tag is pushed. To cut a release:

1. Bump the version in **all three** places: `pyproject.toml`, `crumbs/__init__.py`,
   and `plugin/.claude-plugin/plugin.json` (keep them in sync).
2. Commit the bump and push to `main`.
3. Tag and push it:

   ```bash
   git tag v0.3.1 && git push origin v0.3.1
   ```

CI then builds the sdist + wheel, runs `twine check`, and publishes to PyPI via
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC — no token stored
in the repo). PyPI versions are immutable, so every release needs a new version number.

## License

MIT
