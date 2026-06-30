"""Search across indexed repos and build LLM-ready context slices."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from . import digest, store

# Splits an identifier chunk into word pieces: runs of an acronym, a
# capitalized or lower word, or digits. So ``parseHTTPServer`` ->
# ``parse``, ``HTTP``, ``Server`` and ``getID2`` -> ``get``, ``ID``, ``2``.
_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z][a-z0-9]*|[A-Z]+|[0-9]+")


def _stem(t: str) -> str:
    """Very light suffix stripping so ``logins``/``logging`` share a root.

    Not linguistically correct -- just enough to collapse plurals and common
    verb forms (``classes``->``class``, ``parsing``->``pars``) so a query term
    matches its inflected forms. Short tokens are left alone.
    """
    for suf in ("ing", "ed", "es", "s"):
        if len(t) - len(suf) >= 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _terms(text: str) -> List[str]:
    """Normalize text to stemmed search terms.

    Splits on non-identifier chars, then breaks each chunk on camelCase and
    snake_case boundaries (keeping the whole chunk too), then stems. So
    ``loginUser`` is findable by ``login``, ``user``, or ``loginuser``.
    """
    out: List[str] = []
    # Split on non-identifier chars but keep original case so camelCase
    # boundaries survive; lowercase only the final pieces.
    for raw in re.split(r"[^A-Za-z0-9_]+", text):
        if not raw:
            continue
        pieces = {raw.replace("_", "").lower()} if "_" in raw else {raw.lower()}
        for seg in raw.split("_"):
            for m in _WORD.finditer(seg):
                pieces.add(m.group(0).lower())
        for p in pieces:
            if p:
                out.append(_stem(p))
    return out


# Backwards-compatible alias; some callers/tests import _tokens.
def _tokens(q: str) -> List[str]:
    return _terms(q)


def _name_boost(qset: set, name: str) -> float:
    """Reward matches on the symbol *name* over incidental sig/doc hits."""
    nm = name.lower()
    name_terms = set(_terms(name))
    boost = 0.0
    for qt in qset:
        if qt == nm:
            boost += 10  # whole-name hit
        elif qt in name_terms:
            boost += 5   # a word inside the name (camel/snake piece)
        elif qt in nm:
            boost += 2   # substring of the name
    return boost


def search(query: str, repo: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """Return ranked symbol matches across indexed repos.

    Ranking blends TF-IDF over the matched corpus (so rare, specific terms
    outweigh common ones) with a boost for hits on the symbol name, and finally
    favors public symbols over internals when scores tie.
    """
    qset = set(_terms(query))
    if not qset:
        return []
    rids = [store.resolve(repo)] if repo else store.all_repos()
    rids = [r for r in rids if r]

    # First pass: gather candidate symbols and their term frequencies, and
    # accumulate document frequencies for IDF.
    docs: List[Dict[str, Any]] = []
    df: Counter = Counter()
    for rid in rids:
        data = store.load_repo(rid)
        if not data:
            continue
        for f in data["files"]:
            for sym in f["symbols"]:
                hay = f"{f['path']} {sym['name']} {sym['sig']} {sym.get('doc', '')}"
                tf = Counter(_terms(hay))
                for t in tf:
                    df[t] += 1
                docs.append({"repo": data["name"], "path": f["path"],
                             "lang": f["lang"], "sym": sym, "tf": tf})

    n_docs = len(docs)
    results: List[Dict[str, Any]] = []
    for d in docs:
        tf = d["tf"]
        score = 0.0
        for qt in qset:
            freq = tf.get(qt, 0)
            if freq:
                # Smoothed IDF: rarer terms across the corpus weigh more.
                idf = math.log((n_docs + 1) / (df[qt] + 1)) + 1.0
                score += freq * idf
        score += _name_boost(qset, d["sym"]["name"])
        if score > 0:
            results.append({
                "repo": d["repo"],
                "path": d["path"],
                "lang": d["lang"],
                "score": round(score, 3),
                **d["sym"],
            })
    # Public before internal on ties, then a stable order.
    results.sort(key=lambda r: (r["score"], r.get("vis") != "internal"), reverse=True)
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
            tag = digest.loc(it)
            where = f" [{tag}]" if tag else ""
            mark = " ·internal" if it.get("vis") == "internal" else ""
            doc = f"  — {it['doc']}" if it.get("doc") else ""
            lines.append(f"    - {sig}{where}{mark}{doc}")
        lines.append("")
    return "\n".join(lines)
