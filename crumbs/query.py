"""Search across indexed repos and build LLM-ready context slices."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import store


def _tokens(q: str) -> List[str]:
    return [t for t in re.split(r"[^A-Za-z0-9_]+", q.lower()) if t]


def _score(terms: List[str], path: str, sym: Dict[str, str]) -> int:
    hay = f"{path} {sym['name']} {sym['sig']} {sym.get('doc', '')}".lower()
    name = sym["name"].lower()
    score = 0
    for t in terms:
        if not t:
            continue
        if t == name:
            score += 10
        elif t in name:
            score += 5
        if t in hay:
            score += 1
    return score


def search(query: str, repo: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """Return ranked symbol matches across indexed repos."""
    terms = _tokens(query)
    if not terms:
        return []
    rids = [store.resolve(repo)] if repo else store.all_repos()
    rids = [r for r in rids if r]
    results: List[Dict[str, Any]] = []
    for rid in rids:
        data = store.load_repo(rid)
        if not data:
            continue
        for f in data["files"]:
            for sym in f["symbols"]:
                s = _score(terms, f["path"], sym)
                if s > 0:
                    results.append({
                        "repo": data["name"],
                        "path": f["path"],
                        "lang": f["lang"],
                        "score": s,
                        **sym,
                    })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def context(query: str, repo: Optional[str] = None, limit: int = 20) -> str:
    """Format the most relevant crumbs for a query as compact markdown."""
    hits = search(query, repo=repo, limit=limit)
    if not hits:
        return f"# crumbs context: {query}\n\n_No matches across indexed repos._\n"
    lines = [f"# crumbs context: {query}", ""]
    by_repo: Dict[str, List[Dict[str, Any]]] = {}
    for h in hits:
        by_repo.setdefault(h["repo"], []).append(h)
    for repo_name, items in by_repo.items():
        lines.append(f"## {repo_name}")
        cur_path = None
        for it in items:
            if it["path"] != cur_path:
                cur_path = it["path"]
                lines.append(f"- `{it['path']}`")
            sig = it["sig"] or f"{it['kind']} {it['name']}"
            doc = f"  — {it['doc']}" if it.get("doc") else ""
            lines.append(f"    - {sig}{doc}")
        lines.append("")
    return "\n".join(lines)
