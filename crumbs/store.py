"""Local on-disk store for crumb data.

Layout (default ~/.crumbs, override with CRUMBS_HOME):

    <home>/
        registry.json        # id -> {name, path, indexed_at, stats}
        repos/<id>.json      # full crumb data for one repo
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def home() -> Path:
    """Return the crumbs home directory, creating it if needed."""
    root = Path(os.environ.get("CRUMBS_HOME", Path.home() / ".crumbs"))
    (root / "repos").mkdir(parents=True, exist_ok=True)
    return root


def repo_id(path: str) -> str:
    """Stable short id for a repo, derived from its absolute path."""
    abspath = str(Path(path).expanduser().resolve())
    return hashlib.sha1(abspath.encode()).hexdigest()[:12]


def _registry_path() -> Path:
    return home() / "registry.json"


def load_registry() -> Dict[str, Any]:
    p = _registry_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_registry(reg: Dict[str, Any]) -> None:
    _registry_path().write_text(json.dumps(reg, indent=2, sort_keys=True))


def save_repo(rid: str, data: Dict[str, Any]) -> None:
    """Persist one repo's crumb data and update the registry."""
    (home() / "repos" / f"{rid}.json").write_text(json.dumps(data))
    reg = load_registry()
    reg[rid] = {
        "name": data["name"],
        "path": data["path"],
        "indexed_at": data["indexed_at"],
        "stats": data["stats"],
    }
    save_registry(reg)


def load_repo(rid: str) -> Optional[Dict[str, Any]]:
    p = home() / "repos" / f"{rid}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def remove_repo(rid: str) -> bool:
    p = home() / "repos" / f"{rid}.json"
    existed = p.exists()
    if existed:
        p.unlink()
    reg = load_registry()
    if rid in reg:
        del reg[rid]
        save_registry(reg)
    return existed


def resolve(selector: str) -> Optional[str]:
    """Resolve a user-supplied selector to a repo id.

    Accepts an exact id, a repo name, or a filesystem path.
    """
    reg = load_registry()
    if selector in reg:
        return selector
    # by name (exact, then unique prefix)
    by_name = [rid for rid, m in reg.items() if m["name"] == selector]
    if len(by_name) == 1:
        return by_name[0]
    # by path
    try:
        rid = repo_id(selector)
        if rid in reg:
            return rid
    except OSError:
        pass
    # by name prefix
    pref = [rid for rid, m in reg.items() if m["name"].startswith(selector)]
    if len(pref) == 1:
        return pref[0]
    return None


def now() -> float:
    return time.time()


def all_repos() -> List[str]:
    return list(load_registry().keys())
