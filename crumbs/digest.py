"""Render a compact, token-efficient map of an indexed repo."""

from __future__ import annotations

from typing import Any, Dict, List

from . import store


def _est_tokens(chars: int) -> int:
    """Rough token estimate (~4 chars/token)."""
    return chars // 4


def repo_map(rid: str, max_symbols_per_file: int = 12) -> str:
    data = store.load_repo(rid)
    if not data:
        return ""
    lines: List[str] = []
    g = data.get("git", {})
    header = f"# {data['name']}"
    lines.append(header)
    meta = []
    if g.get("remote"):
        meta.append(g["remote"])
    if g.get("branch"):
        meta.append(f"@{g['branch']}")
    if meta:
        lines.append(" ".join(meta))
    st = data["stats"]
    lines.append(
        f"_{st['files']} files, {st['symbols']} symbols indexed_"
    )
    lines.append("")
    if data.get("readme"):
        excerpt = data["readme"].strip().replace("\n\n", "\n")
        lines.append("> " + excerpt.replace("\n", "\n> "))
        lines.append("")

    for f in data["files"]:
        syms = f["symbols"]
        if not syms:
            continue
        lines.append(f"### {f['path']}")
        for sym in syms[:max_symbols_per_file]:
            sig = sym["sig"] or f"{sym['kind']} {sym['name']}"
            doc = f"  — {sym['doc']}" if sym.get("doc") else ""
            lines.append(f"- {sig}{doc}")
        if len(syms) > max_symbols_per_file:
            lines.append(f"- … +{len(syms) - max_symbols_per_file} more")
        lines.append("")

    return "\n".join(lines)


def savings(data: Dict[str, Any], map_text: str) -> Dict[str, int]:
    src_tokens = _est_tokens(data["stats"]["source_bytes"])
    map_tokens = _est_tokens(len(map_text))
    pct = 0 if src_tokens == 0 else round(100 * (1 - map_tokens / src_tokens))
    return {
        "source_tokens": src_tokens,
        "map_tokens": map_tokens,
        "saved_pct": pct,
    }
