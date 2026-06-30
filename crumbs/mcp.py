"""A minimal MCP (Model Context Protocol) server for crumbs.

This speaks the MCP wire protocol directly over stdio with **zero
dependencies** -- no SDK -- to keep crumbs pure-stdlib. An MCP host (Claude
Code, Claude Desktop, or any MCP client) launches ``crumbs mcp`` as a
subprocess and talks to it in JSON-RPC 2.0 over stdin/stdout.

Wire format (stdio transport): newline-delimited JSON. Each message is one
JSON object on its own line. stdout is reserved for protocol traffic only;
all logging goes to stderr.

Lifecycle:
    client -> initialize            -> server: capabilities + serverInfo
    client -> notifications/initialized   (no response)
    client -> tools/list            -> server: the tool catalog
    client -> tools/call            -> server: the tool's output

The tools are thin adapters over the existing crumbs modules; the MCP layer
only translates JSON-RPC <-> Python calls and formats results as text.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, List, Optional

from . import __version__, digest, indexer, query, store

# Protocol version we default to if the client doesn't propose one. We echo
# the client's requested version when present for forward compatibility.
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC error codes we use.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _log(msg: str) -> None:
    print(f"[crumbs-mcp] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Tool implementations -- each returns a plain string (rendered as text).
# --------------------------------------------------------------------------- #
def _tool_index(args: Dict[str, Any]) -> str:
    paths = args.get("paths") or ([args["path"]] if args.get("path") else ["."])
    name = args.get("name")
    out: List[str] = []
    for p in paths:
        data = indexer.index_repo(p, name=name)
        st = data["stats"]
        m = digest.repo_map(data["id"])
        sav = digest.savings(data, m)
        out.append(
            f"indexed {data['name']}: {st['files']} files, {st['symbols']} symbols "
            f"(map ~{sav['map_tokens']} tok vs ~{sav['source_tokens']} source, -{sav['saved_pct']}%)"
        )
    return "\n".join(out)


def _tool_list(args: Dict[str, Any]) -> str:
    reg = store.load_registry()
    if not reg:
        return "No repos indexed yet. Use crumbs_index with a path first."
    rows = sorted(reg.items(), key=lambda kv: kv[1]["name"])
    lines = []
    for rid, m in rows:
        st = m["stats"]
        lines.append(f"{m['name']} ({rid}): {st['files']} files, {st['symbols']} symbols")
    return "\n".join(lines)


def _resolve_or_index(selector: str) -> Optional[str]:
    """Resolve a repo selector, indexing (or re-indexing when stale) as needed.

    An already-indexed repo is rebuilt if its source has changed since the last
    index, so map/search/context never serve an out-of-date crumb map.
    """
    rid = store.resolve(selector)
    if rid:
        data = store.load_repo(rid)
        if data and not indexer.is_stale(data):
            return rid
        try:
            indexer.index_repo(data["path"] if data else selector)
        except (NotADirectoryError, FileNotFoundError, KeyError):
            pass  # keep the existing (possibly stale) index rather than failing
        return rid
    try:
        indexer.index_repo(selector)
    except (NotADirectoryError, FileNotFoundError):
        return None
    return store.resolve(selector)


def _tool_map(args: Dict[str, Any]) -> str:
    repo = args["repo"]
    rid = _resolve_or_index(repo)
    if not rid:
        return f"No indexed repo matches '{repo}' (and it is not an indexable path)."
    return digest.repo_map(rid, max_symbols_per_file=int(args.get("max_symbols", 12)))


def _tool_search(args: Dict[str, Any]) -> str:
    repo = args.get("repo")
    if repo:
        _resolve_or_index(repo)
    hits = query.search(args["query"], repo=repo, limit=int(args.get("limit", 30)))
    if not hits:
        return "No matches."
    lines = []
    for h in hits:
        sig = h["sig"] or f"{h['kind']} {h['name']}"
        loc = f":{h['line']}" if h.get("line") else ""
        lines.append(f"{h['repo']}:{h['path']}{loc}  {sig}")
    return "\n".join(lines)


def _tool_context(args: Dict[str, Any]) -> str:
    repo = args.get("repo")
    if repo:
        _resolve_or_index(repo)
    return query.context(args["query"], repo=repo, limit=int(args.get("limit", 20)))


# --------------------------------------------------------------------------- #
# Tool catalog: name -> {description, inputSchema, handler}. The description and
# schema are what the model uses to decide *whether* and *how* to call a tool.
# --------------------------------------------------------------------------- #
def _str(desc: str) -> Dict[str, str]:
    return {"type": "string", "description": desc}


TOOLS: Dict[str, Dict[str, Any]] = {
    "crumbs_map": {
        "description": (
            "Get a compact, token-efficient map of a repository: every file with "
            "its typed function/class signatures, one-line docs, and source line "
            "ranges (e.g. [L40-92]) -- but NOT the file bodies. Use this FIRST to "
            "orient yourself in a repo instead of reading files; then open only the "
            "line ranges it points to. Indexes the repo automatically if needed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _str("Repo name, id, or filesystem path."),
                "max_symbols": {"type": "integer", "description": "Max symbols shown per file (default 12)."},
            },
            "required": ["repo"],
        },
        "handler": _tool_map,
    },
    "crumbs_search": {
        "description": (
            "Search for symbols (functions, classes, types) by keyword across all "
            "indexed repos, ranked by relevance. Returns repo:path:line plus the "
            "signature for each hit, so you can open the exact slice. Use to find "
            "where something lives across one or many repos."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _str("Keywords to search for, e.g. 'auth token'."),
                "repo": _str("Optional: limit to one repo (name, id, or path)."),
                "limit": {"type": "integer", "description": "Max results (default 30)."},
            },
            "required": ["query"],
        },
        "handler": _tool_search,
    },
    "crumbs_context": {
        "description": (
            "Build an LLM-ready context slice for a topic: the most relevant symbols "
            "across indexed repos, grouped by repo and file, with signatures, docs, "
            "and line ranges. Use when you want focused context on a topic rather "
            "than a whole repo map."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _str("Topic to gather context for, e.g. 'rate limiting'."),
                "repo": _str("Optional: limit to one repo."),
                "limit": {"type": "integer", "description": "Max symbols (default 20)."},
            },
            "required": ["query"],
        },
        "handler": _tool_context,
    },
    "crumbs_index": {
        "description": (
            "Index one or more repositories so their maps/searches are available. "
            "Usually unnecessary -- the other tools auto-index a path on first use -- "
            "but call this to (re)index explicitly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Repo paths to index."},
                "path": _str("A single repo path (alternative to 'paths')."),
                "name": _str("Optional override name for the repo."),
            },
        },
        "handler": _tool_index,
    },
    "crumbs_list": {
        "description": "List all indexed repositories with their file and symbol counts.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": _tool_list,
    },
}


# --------------------------------------------------------------------------- #
# JSON-RPC plumbing
# --------------------------------------------------------------------------- #
def _result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process one JSON-RPC message; return a response, or None for notifications."""
    method = msg.get("method")
    req_id = msg.get("id")
    is_notification = "id" not in msg
    params = msg.get("params") or {}

    if method == "initialize":
        proto = params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION)
        return _result(req_id, {
            "protocolVersion": proto,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "crumbs", "version": __version__},
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # notification: acknowledge by doing nothing

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        tools = [
            {"name": name, "description": t["description"], "inputSchema": t["inputSchema"]}
            for name, t in TOOLS.items()
        ]
        return _result(req_id, {"tools": tools})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = TOOLS.get(name)
        if not tool:
            return _error(req_id, INVALID_PARAMS, f"unknown tool: {name}")
        try:
            text = tool["handler"](arguments)
        except KeyError as e:
            # a required argument was missing -- report as a tool error, not a crash
            return _result(req_id, {
                "content": [{"type": "text", "text": f"missing argument: {e}"}],
                "isError": True,
            })
        except Exception as e:  # noqa: BLE001 -- surface any tool failure to the client
            _log(f"tool {name} failed: {e}")
            return _result(req_id, {
                "content": [{"type": "text", "text": f"error: {e}"}],
                "isError": True,
            })
        return _result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})

    if is_notification:
        return None  # ignore unknown notifications
    return _error(req_id, METHOD_NOT_FOUND, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    """Run the stdio MCP server loop until stdin closes."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    _log(f"crumbs {__version__} MCP server ready (stdio)")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_error(None, PARSE_ERROR, "invalid JSON")) + "\n")
            stdout.flush()
            continue
        response = _handle(msg)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0
