"""Lightweight staleness detection for the project memory knowledge base.

Purpose
-------
On **every** MCP query call, the server should be able to cheaply tell the
calling agent whether the on-disk working tree has diverged from the indexed
knowledge graph (files changed / added / deleted since the last
reconciliation). The agent gets this notification *immediately* in the tool
result, so it can re-analyze **before** trusting stale descriptions — instead
of only discovering the staleness lazily when it tries to use a record.

Design
------
- A JSON snapshot of ``{relative_path: hash}`` is stored at
  ``.project-memory/change_log.json`` next to the SQLite DB.
- The snapshot is (re)written after every ``bootstrap`` / ``rescan_changed_files``
  / ``index`` operation.
- ``check_staleness(project_path)`` compares the on-disk hashes to the
  snapshot and returns the diff. It is intentionally cheap: it scans the
  working tree with :class:`FileScanner` (same scanner used for indexing,
  same exclude rules) and does a dict diff — no DB access, no LLM.
- The result is a small dict suitable for attaching to any tool output as a
  ``staleness_warning`` field.

The snapshot is the source of truth for "what the graph thinks the tree looks
like"; the working tree is the source of truth for "what the tree actually
looks like". The diff is what we warn about.
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from project_memory_mcp.db.connection import get_session
from project_memory_mcp.db.models import File
from project_memory_mcp.static_analysis.file_scanner import FileScanner

CHANGE_LOG_FILENAME = "change_log.json"


def get_snapshot_path(project_path: str | Path) -> Path:
    """Return the absolute path to the change_log.json snapshot."""
    root = Path(project_path).resolve()
    return root / ".project-memory" / CHANGE_LOG_FILENAME


def load_snapshot(project_path: str | Path) -> dict[str, str]:
    """Load the recorded ``{relative_path: hash}`` snapshot.

    Returns an empty dict if no snapshot exists yet (e.g. before the first
    index), which makes every current file appear "added".
    """
    path = get_snapshot_path(project_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "files" in data and isinstance(data["files"], dict):
            return {str(k): str(v) for k, v in data["files"].items()}
        # Tolerate a bare {path: hash} mapping for forward/backward compat.
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


def save_snapshot(project_path: str | Path, files: dict[str, str]) -> Path:
    """Persist the ``{relative_path: hash}`` snapshot.

    ``files`` should be the full set of indexed file paths and their current
    hashes — i.e. the post-reconciliation ground truth. Called after
    bootstrap/index/rescan so the next staleness check compares against the
    freshest state.
    """
    path = get_snapshot_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "files": files,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_snapshot_from_scanner(project_path: str | Path) -> dict[str, str]:
    """Build a ``{relative_path: hash}`` dict by scanning the working tree.

    Uses the same :class:`FileScanner` (and exclude patterns) as the indexer,
    so "what the snapshot thinks is on disk" and "what the indexer sees" stay
    consistent.
    """
    scanner = FileScanner(str(Path(project_path).resolve()))
    return {f.relative_path: f.hash for f in scanner.scan()}


async def build_snapshot_from_db_async(project_path: str | Path) -> dict[str, str]:
    """Build a ``{relative_path: hash}`` dict from the indexed ``File`` rows.

    This is the "what the graph currently believes" baseline. Used when
    refreshing the snapshot after a rescan so it reflects DB truth (which may
    differ from a raw scan if e.g. some files failed to insert).
    """
    out: dict[str, str] = {}
    async with get_session() as session:
        rows = (await session.execute(select(File.path, File.hash))).all()
        for row in rows:
            out[str(row.path)] = str(row.hash)
    return out


def check_staleness(project_path: str | Path) -> dict[str, Any]:
    """Compare the on-disk working tree to the recorded snapshot.

    Returns a dict with ``stale``, ``changed_files``, ``deleted_files``,
    ``added_files``, and an ``action`` string. Cheap enough to call on every
    tool invocation: one directory scan + one dict diff, no DB/LLM work.

    ``stale`` is ``True`` iff there is any divergence (or no snapshot yet but
    files exist on disk). The caller is expected to surface this to the agent
    as a ``staleness_warning`` so the agent re-analyzes proactively.
    """
    project_root = Path(project_path).resolve()

    try:
        current = build_snapshot_from_scanner(project_root)
    except Exception:
        # If the scanner blows up (e.g. bad path), don't block the tool call;
        # report a benign "unknown" state instead.
        return {
            "stale": False,
            "changed_files": [],
            "deleted_files": [],
            "added_files": [],
            "action": "Staleness check skipped (scan failed).",
        }

    snapshot = load_snapshot(project_root)

    snapshot_paths = set(snapshot.keys())
    current_paths = set(current.keys())

    changed = sorted(
        p for p in (snapshot_paths & current_paths) if snapshot[p] != current[p]
    )
    deleted = sorted(snapshot_paths - current_paths)
    added = sorted(current_paths - snapshot_paths)

    stale = bool(changed or deleted or added)

    if not stale:
        action = "Knowledge base is in sync with the working tree."
    else:
        parts = []
        if changed:
            parts.append(f"{len(changed)} changed")
        if added:
            parts.append(f"{len(added)} added")
        if deleted:
            parts.append(f"{len(deleted)} deleted")
        action = (
            "Files differ from the indexed knowledge base ("
            + ", ".join(parts)
            + "). Call project.rescan_changed_files then "
            + "project.start_analysis_loop to re-analyze before trusting the graph."
        )

    return {
        "stale": stale,
        "changed_files": changed,
        "deleted_files": deleted,
        "added_files": added,
        "action": action,
    }


async def refresh_snapshot_async(project_path: str | Path) -> Path:
    """Reconcile the snapshot with DB truth after a rescan / index.

    Uses the DB (not a raw scan) so the snapshot matches exactly what the
    graph believes, including any files the indexer decided to skip.
    """
    files = await build_snapshot_from_db_async(project_path)
    return save_snapshot(project_path, files)
