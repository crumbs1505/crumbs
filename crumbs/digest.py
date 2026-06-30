"""Render a compact, token-efficient map of an indexed repo."""

from __future__ import annotations

import posixpath
from typing import Any, Dict, List, Optional

from . import store

# Repos with more files than this render as a directory overview by default,
# so the map itself never becomes the token bloat it exists to eliminate.
OVERVIEW_THRESHOLD = 40


def _est_tokens(chars: int) -> int:
    """Rough token estimate (~4 chars/token)."""
    return chars // 4


def loc(sym: Dict[str, Any]) -> str:
    """Compact source location tag, e.g. ``L40-92`` or ``L40``."""
    start = sym.get("line")
    if not start:
        return ""
    end = sym.get("end_line", start)
    return f"L{start}" if end == start else f"L{start}-{end}"


def _header(data: Dict[str, Any]) -> List[str]:
    """The shared title/git/stats/readme block used by every renderer."""
    lines: List[str] = [f"# {data['name']}"]
    g = data.get("git", {})
    meta = []
    if g.get("remote"):
        meta.append(g["remote"])
    if g.get("branch"):
        meta.append(f"@{g['branch']}")
    if meta:
        lines.append(" ".join(meta))
    st = data["stats"]
    lines.append(f"_{st['files']} files, {st['symbols']} symbols indexed_")
    lines.append("")
    if data.get("readme"):
        excerpt = data["readme"].strip().replace("\n\n", "\n")
        lines.append("> " + excerpt.replace("\n", "\n> "))
        lines.append("")
    return lines


def _in_subtree(path: str, prefix: str) -> bool:
    """True if ``path`` is ``prefix`` itself or lives under it."""
    prefix = prefix.strip("/")
    return path == prefix or path.startswith(prefix + "/")


def repo_map(
    rid: str, max_symbols_per_file: int = 12, path: Optional[str] = None
) -> str:
    data = store.load_repo(rid)
    if not data:
        return ""
    lines = _header(data)

    files = data["files"]
    if path:
        files = [f for f in files if _in_subtree(f["path"], path)]
        scope = path.strip("/")
        if not files:
            lines.append(f"_no indexed files under '{scope}/'_")
            return "\n".join(lines)
        lines.append(f"_scope: {scope}/_")
        lines.append("")

    for f in files:
        syms = f["symbols"]
        if not syms:
            continue
        # Lead with the public API, then internals -- so the exported surface
        # survives truncation and the first tokens an agent reads are the ones
        # it is most likely to call. Stable sort keeps source order within each
        # group.
        syms = sorted(syms, key=_internal_first)
        lines.append(f"### {f['path']}")
        for sym in syms[:max_symbols_per_file]:
            sig = sym["sig"] or f"{sym['kind']} {sym['name']}"
            tag = loc(sym)
            where = f" [{tag}]" if tag else ""
            mark = " ·internal" if sym.get("vis") == "internal" else ""
            doc = f"  — {sym['doc']}" if sym.get("doc") else ""
            lines.append(f"- {sig}{where}{mark}{doc}")
        if len(syms) > max_symbols_per_file:
            lines.append(f"- … +{len(syms) - max_symbols_per_file} more")
        lines.append("")

    return "\n".join(lines)


def _internal_first(sym: Dict[str, Any]) -> int:
    """Sort key: public symbols (0) before internal ones (1)."""
    return 1 if sym.get("vis") == "internal" else 0


def repo_overview(rid: str) -> str:
    """A directory-level map: each directory with its file/symbol counts.

    The compact entry point for large repos -- the agent reads this to pick a
    subtree, then calls :func:`repo_map` with ``path=`` to expand just that one.
    """
    data = store.load_repo(rid)
    if not data:
        return ""
    lines = _header(data)

    # Aggregate by each file's parent directory ("." for repo-root files).
    dirs: Dict[str, Dict[str, int]] = {}
    for f in data["files"]:
        d = posixpath.dirname(f["path"]) or "."
        agg = dirs.setdefault(d, {"files": 0, "symbols": 0})
        agg["files"] += 1
        agg["symbols"] += len(f["symbols"])

    for d in sorted(dirs):
        agg = dirs[d]
        label = d if d == "." else d + "/"
        fw = "file" if agg["files"] == 1 else "files"
        sw = "symbol" if agg["symbols"] == 1 else "symbols"
        lines.append(f"{label}   ({agg['files']} {fw}, {agg['symbols']} {sw})")

    lines.append("")
    lines.append('_Use crumbs map with path="<dir>" to expand a directory._')
    return "\n".join(lines)


def auto_map(rid: str, max_symbols_per_file: int = 12) -> str:
    """Overview for large repos, full map for small ones (the default view)."""
    data = store.load_repo(rid)
    if not data:
        return ""
    if data["stats"]["files"] > OVERVIEW_THRESHOLD:
        return repo_overview(rid)
    return repo_map(rid, max_symbols_per_file=max_symbols_per_file)


def savings(data: Dict[str, Any], map_text: str) -> Dict[str, int]:
    src_tokens = _est_tokens(data["stats"]["source_bytes"])
    map_tokens = _est_tokens(len(map_text))
    pct = 0 if src_tokens == 0 else round(100 * (1 - map_tokens / src_tokens))
    return {
        "source_tokens": src_tokens,
        "map_tokens": map_tokens,
        "saved_pct": pct,
    }
