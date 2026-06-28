"""Walk a repository and build its compact crumb data."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import extractors, store

# Directories never worth indexing.
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".next", ".nuxt", "out", "vendor",
    ".idea", ".vscode", "coverage", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "site-packages", ".tox", "bin", "obj", ".cache",
    ".remember", ".crumbs",
}

# Files to skip by name.
SKIP_FILES = {"package-lock.json", "yarn.lock", "poetry.lock", "Cargo.lock", "pnpm-lock.yaml"}

MAX_FILE_BYTES = 1_500_000  # skip files larger than this (likely generated/binary)
DOC_NAMES = {"readme.md", "readme.rst", "readme.txt", "readme"}


def _is_text(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(2048)
        return b"\x00" not in chunk
    except OSError:
        return False


def _git_info(root: Path) -> Dict[str, str]:
    info: Dict[str, str] = {}
    try:
        remote = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if remote.returncode == 0:
            info["remote"] = remote.stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if branch.returncode == 0:
            info["branch"] = branch.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def index_repo(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Index a repository at ``path`` and persist its crumbs.

    Returns the crumb data dict.
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    rid = store.repo_id(str(root))
    name = name or root.name
    files: List[Dict[str, Any]] = []
    total_source_bytes = 0
    readme_excerpt = ""

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d in (".github",)]
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            fpath = Path(dirpath) / fn
            rel = str(fpath.relative_to(root))
            lang = extractors.lang_for(fn)

            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                continue

            # Capture a top-level README excerpt for the repo summary.
            if fn.lower() in DOC_NAMES and "/" not in rel and not readme_excerpt:
                if _is_text(fpath):
                    readme_excerpt = _read(fpath)[:600]

            if not lang:
                continue
            if not _is_text(fpath):
                continue

            text = _read(fpath)
            total_source_bytes += len(text)
            symbols = extractors.extract(rel, text)
            files.append({
                "path": rel,
                "lang": lang,
                "loc": text.count("\n") + 1,
                "symbols": symbols,
            })

    files.sort(key=lambda f: f["path"])
    sym_count = sum(len(f["symbols"]) for f in files)

    data: Dict[str, Any] = {
        "id": rid,
        "name": name,
        "path": str(root),
        "indexed_at": store.now(),
        "git": _git_info(root),
        "readme": readme_excerpt,
        "files": files,
        "stats": {
            "files": len(files),
            "symbols": sym_count,
            "source_bytes": total_source_bytes,
        },
    }
    store.save_repo(rid, data)
    return data


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
