"""crumbs command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import List, Optional

from . import __version__, digest, indexer, query, store


def _fmt_age(ts: float) -> str:
    secs = max(0, int(time.time() - ts))
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= n:
            return f"{secs // n}{unit} ago"
    return "just now"


def cmd_index(args: argparse.Namespace) -> int:
    paths = args.paths or ["."]
    for p in paths:
        try:
            data = indexer.index_repo(p, name=args.name)
        except (NotADirectoryError, FileNotFoundError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        st = data["stats"]
        m = digest.repo_map(data["id"])
        sav = digest.savings(data, m)
        print(
            f"indexed {data['name']}  "
            f"{st['files']} files, {st['symbols']} symbols  "
            f"(map ~{sav['map_tokens']} tok vs ~{sav['source_tokens']} tok source, "
            f"-{sav['saved_pct']}%)"
        )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    reg = store.load_registry()
    if not reg:
        print("no repos indexed. run: crumbs index <path>")
        return 0
    if args.json:
        print(json.dumps(reg, indent=2))
        return 0
    rows = sorted(reg.items(), key=lambda kv: kv[1]["name"])
    name_w = max((len(m["name"]) for _, m in rows), default=4)
    for rid, m in rows:
        st = m["stats"]
        print(
            f"{m['name']:<{name_w}}  {rid}  "
            f"{st['files']:>4} files  {st['symbols']:>5} symbols  "
            f"{_fmt_age(m['indexed_at'])}"
        )
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    rid = store.resolve(args.repo)
    if not rid:
        print(f"error: no indexed repo matches '{args.repo}'", file=sys.stderr)
        return 1
    text = digest.repo_map(rid, max_symbols_per_file=args.max_symbols)
    print(text)
    if args.stats:
        data = store.load_repo(rid)
        sav = digest.savings(data, text)
        print(
            f"\n_~{sav['map_tokens']} tokens (vs ~{sav['source_tokens']} for full source, "
            f"-{sav['saved_pct']}%)_",
            file=sys.stderr,
        )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    hits = query.search(args.query, repo=args.repo, limit=args.limit)
    if args.json:
        print(json.dumps(hits, indent=2))
        return 0
    if not hits:
        print("no matches")
        return 0
    for h in hits:
        sig = h["sig"] or f"{h['kind']} {h['name']}"
        loc = f":{h['line']}" if h.get("line") else ""
        print(f"{h['repo']}:{h['path']}{loc}  {sig}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    print(query.context(args.query, repo=args.repo, limit=args.limit))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    rid = store.resolve(args.repo)
    if not rid:
        print(f"error: no indexed repo matches '{args.repo}'", file=sys.stderr)
        return 1
    name = store.load_registry().get(rid, {}).get("name", rid)
    store.remove_repo(rid)
    print(f"removed {name}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    reg = store.load_registry()
    if not reg:
        print("nothing to refresh")
        return 0
    for rid, m in list(reg.items()):
        try:
            indexer.index_repo(m["path"], name=m["name"])
            print(f"refreshed {m['name']}")
        except (NotADirectoryError, FileNotFoundError):
            print(f"skip {m['name']} (path missing: {m['path']})", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="crumbs",
        description="Local, token-efficient cross-repo context for LLMs.",
    )
    p.add_argument("--version", action="version", version=f"crumbs {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="index one or more repos")
    pi.add_argument("paths", nargs="*", help="repo paths (default: .)")
    pi.add_argument("--name", help="override repo name")
    pi.set_defaults(func=cmd_index)

    pl = sub.add_parser("list", help="list indexed repos")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    pm = sub.add_parser("map", help="print compact map of a repo")
    pm.add_argument("repo", help="repo name, id, or path")
    pm.add_argument("--max-symbols", type=int, default=12)
    pm.add_argument("--stats", action="store_true", help="print token estimate to stderr")
    pm.set_defaults(func=cmd_map)

    ps = sub.add_parser("search", help="search symbols across repos")
    ps.add_argument("query")
    ps.add_argument("--repo", help="limit to one repo")
    ps.add_argument("--limit", type=int, default=30)
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_search)

    pc = sub.add_parser("context", help="LLM-ready context slice for a query")
    pc.add_argument("query")
    pc.add_argument("--repo", help="limit to one repo")
    pc.add_argument("--limit", type=int, default=20)
    pc.set_defaults(func=cmd_context)

    pr = sub.add_parser("remove", help="remove a repo from the index")
    pr.add_argument("repo")
    pr.set_defaults(func=cmd_remove)

    prf = sub.add_parser("refresh", help="re-index all known repos")
    prf.set_defaults(func=cmd_refresh)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
