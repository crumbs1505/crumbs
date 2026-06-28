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

## Install

```bash
pip install -e .        # provides the `crumbs` command
# or run without installing:
python3 -m crumbs --help
```

## Usage

```bash
crumbs index ~/code/my-api ~/code/my-web   # index one or more repos
crumbs list                                # show indexed repos + stats
crumbs map my-api --stats                  # compact map of one repo (+ token estimate)
crumbs search "auth token"                 # rank matching symbols across all repos
crumbs context "rate limiting" --repo my-api   # LLM-ready context slice
crumbs refresh                             # re-index everything
crumbs remove my-web                       # drop a repo from the index
```

A repo can be referenced by name, id, or path.

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

## License

MIT
