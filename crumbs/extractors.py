"""Extract compact symbol signatures from source files.

The goal is a high-signal, low-token summary of what a file *contains* and
*exposes* -- function/class/type signatures and one-line docs -- never the full
bodies. Python is parsed with the stdlib ``ast`` for accuracy; other languages
use lightweight regex that captures declarations without trying to be a parser.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, List

# Map file extension -> language label used in output.
LANGS: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".md": "markdown",
}


def lang_for(filename: str) -> str:
    for ext, lang in LANGS.items():
        if filename.endswith(ext):
            return lang
    return ""


def _first_line(text: str) -> str:
    text = (text or "").strip()
    return text.splitlines()[0].strip() if text else ""


def extract(path: str, text: str) -> List[Dict[str, str]]:
    """Return a list of symbols.

    Each symbol is ``{kind, name, sig, doc, line, end_line, vis}`` where ``line``
    / ``end_line`` are 1-based source line numbers so a reader can open just the
    symbol's slice (e.g. ``path:line-end_line``) instead of the whole file, and
    ``vis`` is ``"public"`` or ``"internal"`` -- the per-language exported
    surface (PEP-8 ``_``, JS ``export``, Go capitalization, Rust ``pub``) -- so
    maps and search can lead with the API and demote internals.
    """
    lang = lang_for(path)
    if lang == "python":
        return _python(text)
    if lang in ("javascript", "typescript"):
        return _js_ts(text)
    if lang == "go":
        return _go(text)
    if lang == "rust":
        return _rust(text)
    if lang == "markdown":
        return _markdown(text)
    if lang:
        return _generic(text)
    return []


# --------------------------------------------------------------------------- #
# Python (AST-based, accurate)
# --------------------------------------------------------------------------- #
def _unparse(node) -> str:
    """Best-effort source for an annotation/default node (3.9+ has ast.unparse)."""
    if node is None:
        return ""
    if hasattr(ast, "unparse"):
        try:
            return ast.unparse(node)
        except Exception:
            return ""
    return ""  # Python 3.8: omit annotation rather than guess


def _arg(arg: ast.arg, default=None) -> str:
    s = arg.arg
    ann = _unparse(getattr(arg, "annotation", None))
    if ann:
        s += ": " + ann
    if default is not None:
        d = _unparse(default)
        if d:
            s += ("=" if not ann else " = ") + d
    return s


def _py_args(node: ast.AST) -> str:
    try:
        a = node.args  # type: ignore[attr-defined]
    except AttributeError:
        return "()"
    parts: List[str] = []
    pos = list(a.posonlyargs) + list(a.args)
    # defaults align to the tail of the positional args.
    pad = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for arg, default in zip(pos, pad):
        parts.append(_arg(arg, default))
    if a.posonlyargs:
        parts.insert(len(a.posonlyargs), "/")
    if a.vararg:
        parts.append("*" + _arg(a.vararg))
    elif a.kwonlyargs:
        parts.append("*")
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        parts.append(_arg(arg, default))
    if a.kwarg:
        parts.append("**" + _arg(a.kwarg))
    sig = "(" + ", ".join(parts) + ")"
    ret = _unparse(getattr(node, "returns", None))
    if ret:
        sig += " -> " + ret
    return sig


def _python(text: str) -> List[Dict[str, str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _generic(text)
    out: List[Dict[str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            out.append({
                "kind": "function",
                "name": node.name,
                "sig": f"{prefix} {node.name}{_py_args(node)}",
                "doc": _first_line(ast.get_docstring(node) or ""),
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "vis": _py_vis(node.name),
            })
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(
                b.id for b in node.bases if isinstance(b, ast.Name)
            )
            sig = f"class {node.name}" + (f"({bases})" if bases else "")
            methods = [
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not n.name.startswith("_")
            ]
            doc = _first_line(ast.get_docstring(node) or "")
            if methods:
                doc = (doc + " " if doc else "") + "methods: " + ", ".join(methods[:12])
            out.append({
                "kind": "class",
                "name": node.name,
                "sig": sig,
                "doc": doc,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "vis": _py_vis(node.name),
            })
    return out


def _py_vis(name: str) -> str:
    """PEP-8 convention: a leading underscore marks a name as internal."""
    return "internal" if name.startswith("_") else "public"


# --------------------------------------------------------------------------- #
# Regex-based extractors for other languages
# --------------------------------------------------------------------------- #
def _collect(text: str, patterns: List[tuple], vis_of=None) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for kind, rx in patterns:
        for m in rx.finditer(text):
            name = m.group("name")
            if not name or name in seen:
                continue
            seen.add(name)
            sig = m.group(0).strip().rstrip("{(=").strip()
            sig = re.sub(r"\s+", " ", sig)[:120]
            line = text.count("\n", 0, m.start()) + 1
            out.append({
                "kind": kind, "name": name, "sig": sig, "doc": "",
                "line": line, "end_line": line,
                "vis": vis_of(name, m) if vis_of else "public",
            })
    return out


_JS_TS = [
    ("function", re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+(?P<name>\w+)", re.M)),
    ("function", re.compile(r"^\s*(?:async\s+)?function\s+(?P<name>\w+)", re.M)),
    ("class", re.compile(r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\s+(?P<name>\w+)", re.M)),
    ("class", re.compile(r"^\s*(?:abstract\s+)?class\s+(?P<name>\w+)", re.M)),
    ("const", re.compile(r"^\s*export\s+const\s+(?P<name>\w+)", re.M)),
    ("type", re.compile(r"^\s*export\s+(?:type|interface)\s+(?P<name>\w+)", re.M)),
    ("type", re.compile(r"^\s*(?:type|interface)\s+(?P<name>\w+)", re.M)),
]

_GO = [
    ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(?P<name>\w+)\s*\(", re.M)),
    ("type", re.compile(r"^\s*type\s+(?P<name>\w+)\s+(?:struct|interface)", re.M)),
]

_RUST = [
    ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(?P<name>\w+)", re.M)),
    ("struct", re.compile(r"^\s*(?:pub\s+)?struct\s+(?P<name>\w+)", re.M)),
    ("enum", re.compile(r"^\s*(?:pub\s+)?enum\s+(?P<name>\w+)", re.M)),
    ("trait", re.compile(r"^\s*(?:pub\s+)?trait\s+(?P<name>\w+)", re.M)),
]


def _vis_js(name: str, m) -> str:
    """In JS/TS the exported surface is whatever carries an ``export`` keyword."""
    return "public" if "export" in m.group(0) else "internal"


def _vis_go(name: str, m) -> str:
    """Go exports any identifier whose first letter is uppercase."""
    return "public" if name[:1].isupper() else "internal"


def _vis_rust(name: str, m) -> str:
    """Rust items are private unless declared ``pub``."""
    return "public" if re.match(r"\s*pub\b", m.group(0)) else "internal"


def _js_ts(text: str) -> List[Dict[str, str]]:
    return _collect(text, _JS_TS, _vis_js)


def _go(text: str) -> List[Dict[str, str]]:
    return _collect(text, _GO, _vis_go)


def _rust(text: str) -> List[Dict[str, str]]:
    return _collect(text, _RUST, _vis_rust)


_HEADING = re.compile(r"^(#{1,3})\s+(?P<name>.+?)\s*#*$", re.M)


def _markdown(text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in _HEADING.finditer(text):
        level = len(m.group(1))
        line = text.count("\n", 0, m.start()) + 1
        out.append({
            "kind": f"h{level}",
            "name": m.group("name").strip(),
            "sig": "",
            "doc": "",
            "line": line,
            "end_line": line,
            "vis": "public",
        })
    return out[:30]


_GENERIC = [
    ("def", re.compile(r"^\s*(?:public|private|protected|static|\s)*\b(?:func|function|def|fn|sub|method)\s+(?P<name>\w+)", re.M)),
]


def _generic(text: str) -> List[Dict[str, str]]:
    return _collect(text, _GENERIC)
