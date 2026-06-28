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
    """Return a list of symbols: {kind, name, sig, doc}."""
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
def _py_args(node: ast.AST) -> str:
    try:
        a = node.args  # type: ignore[attr-defined]
    except AttributeError:
        return "()"
    parts: List[str] = []
    pos = list(a.posonlyargs) + list(a.args)
    for arg in pos:
        parts.append(arg.arg)
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    for arg in a.kwonlyargs:
        parts.append(arg.arg)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return "(" + ", ".join(parts) + ")"


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
            out.append({"kind": "class", "name": node.name, "sig": sig, "doc": doc})
    return out


# --------------------------------------------------------------------------- #
# Regex-based extractors for other languages
# --------------------------------------------------------------------------- #
def _collect(text: str, patterns: List[tuple]) -> List[Dict[str, str]]:
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
            out.append({"kind": kind, "name": name, "sig": sig, "doc": ""})
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


def _js_ts(text: str) -> List[Dict[str, str]]:
    return _collect(text, _JS_TS)


def _go(text: str) -> List[Dict[str, str]]:
    return _collect(text, _GO)


def _rust(text: str) -> List[Dict[str, str]]:
    return _collect(text, _RUST)


_HEADING = re.compile(r"^(#{1,3})\s+(?P<name>.+?)\s*#*$", re.M)


def _markdown(text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in _HEADING.finditer(text):
        level = len(m.group(1))
        out.append({
            "kind": f"h{level}",
            "name": m.group("name").strip(),
            "sig": "",
            "doc": "",
        })
    return out[:30]


_GENERIC = [
    ("def", re.compile(r"^\s*(?:public|private|protected|static|\s)*\b(?:func|function|def|fn|sub|method)\s+(?P<name>\w+)", re.M)),
]


def _generic(text: str) -> List[Dict[str, str]]:
    return _collect(text, _GENERIC)
