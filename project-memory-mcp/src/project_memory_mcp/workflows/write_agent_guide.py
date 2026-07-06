"""Write the agent-agnostic AGENT_GUIDE.md into .project-memory/.

This is a static knowledge-base usage guide. Every AI agent that opens the
project should read `.project-memory/AGENT_GUIDE.md` and learn how to use the
Project Memory knowledge base, regardless of which vendor built it. The file
is intentionally vendor-neutral and self-contained, so it doubles as the
single entry point for any agent discovering the project memory store.
"""

# ruff: noqa: E501

from pathlib import Path
from typing import Any

AGENT_GUIDE_FILENAME = "AGENT_GUIDE.md"

AGENT_GUIDE_CONTENT = """# Project Memory — Agent Guide

> This directory (`.project-memory/`) is a **persistent knowledge base** about
> this codebase, maintained by the `project-memory-mcp` server. Any AI agent
> working in this repo **should read this guide first** and use the knowledge
> base instead of re-reading the whole codebase from scratch.

## What lives here

| File / Artifact             | Purpose                                                                 |
| --------------------------- | ----------------------------------------------------------------------- |
| `AGENT_GUIDE.md`            | This file. Read it first.                                               |
| `PROJECT_AGENT_MANUAL.md`   | Auto-generated, project-specific manual (core files, queries, risks).  |
| `project_knowledge.db`      | SQLite knowledge graph: files, symbols, imports, calls, equations, LLM. |
| `config.yaml`               | Project configuration (LLM endpoint, exclude patterns, flags).         |
| `change_log.json`           | Last recorded file-state snapshot used for stale-change detection.      |

## Why use the knowledge base

The knowledge graph already contains:
- Every source file (path, language, hash, size, role).
- Every symbol (function/class/method), with signature, docstring, line range,
  caller/callee edges.
- Static import and call edges between files and symbols.
- LLM-produced descriptions: per-file purpose & summary, per-symbol
  responsibility & side effects, per-equation math/physical meaning.

Re-reading files you already have indexed wastes context. Query the graph
first; only read source when the graph is missing what you need.

## How to use it (any agent, any vendor)

1. **Before working on the code**, call a query tool:
   - `project.search_files(query="auth")` — find files by what they do.
   - `project.query_file(file_path="src/auth.py")` — file purpose + symbols +
     dependencies.
   - `project.query_symbol(symbol_name="login")` — definition, callers,
     callees, side effects.
   - `project.query_equation(keyword="loss")` — equations and their meaning.
   - `project.query_impact(...)` — blast radius before editing.

2. **Before editing**, follow the safety policy (see `config.yaml`):
   - Run impact analysis first.
   - Propose the edit, then apply only after review.

3. **After editing**, do NOT assume the graph is still in sync. The server
   checks for stale files on every tool call and will warn you. When warned:
   - Call `project.rescan_changed_files(project_path=".")` to reconcile the
     graph with the working tree.
   - Re-run the analysis loop:
     `project.start_analysis_loop(project_path=".")`
     then poll `project.get_analysis_progress(project_path=".")`.
   - Regenerate the manual: `project.generate_manual(project_path=".")`.

## Stale-file notifications (important)

The server keeps a snapshot of every indexed file's hash. On **every** query
tool call it compares the snapshot with the current working tree. If it
detects that files have been **modified, added, or deleted** since the last
reconciliation, the tool result includes a `staleness_warning` field:

```json
{
  "...tool result fields...": "...",
  "staleness_warning": {
    "stale": true,
    "changed_files": ["src/auth.py", "src/utils.py"],
    "deleted_files": ["src/legacy.py"],
    "added_files": ["src/new_feature.py"],
    "action": "Call project.rescan_changed_files then project.start_analysis_loop to re-analyze before trusting the graph."
  }
}
```

When you see `stale: true`, **re-reconcile before trusting the graph** — the
descriptions you just retrieved may be outdated. You can also call
`project.check_staleness(project_path=".")` proactively to poll for changes
without running a full query.

## Tool quick reference

```
# indexing / lifecycle
project.bootstrap(project_path=".")
project.rescan_changed_files(project_path=".")
project.start_analysis_loop(project_path=".")
project.get_analysis_progress(project_path=".")
project.generate_manual(project_path=".")

# staleness
project.check_staleness(project_path=".")

# queries
project.search_files(query="...", only_analyzed=true)
project.query_file(file_path="...")
project.query_symbol(symbol_name="...")
project.query_equation(keyword="...")
project.query_impact(target_type="file", target_name="...", operation_type="modify")

# agent-driven analysis (when local LLM is unavailable)
project.get_next_analysis_task(project_path=".", task_type="file")
project.submit_file_analysis(task_id="file_1", analysis={...})
```

## Conventions

- Paths in the DB are **repo-relative** (POSIX-style `/`).
- `analysis_status` is one of `pending`, `completed`, `failed`.
- The `.project-memory/` directory is part of the project; do not delete it
  (the DB and snapshots live here). Add it to `.gitignore` only if you don't
  want to version the knowledge base; otherwise commit it so teammates and
  other agents inherit the same graph.

---

*Generated by `project-memory-mcp` on bootstrap. Regenerated automatically
whenever you re-index or rescan.*
"""


def get_guide_path(project_path: str | Path) -> Path:
    """Return the absolute path to AGENT_GUIDE.md for a project."""
    root = Path(project_path).resolve()
    return root / ".project-memory" / AGENT_GUIDE_FILENAME


def write_agent_guide(project_path: str | Path) -> dict[str, Any]:
    """Write AGENT_GUIDE.md into <project>/.project-memory/.

    Idempotent: overwrites the previous guide on every call so the content
    stays in sync with the server's current behavior. Called from the indexing
    workflow on bootstrap / re-index.

    Returns a small summary dict for logging/recording.
    """
    guide_path = get_guide_path(project_path)
    guide_path.parent.mkdir(parents=True, exist_ok=True)
    guide_path.write_text(AGENT_GUIDE_CONTENT, encoding="utf-8")
    return {
        "written": True,
        "path": str(guide_path),
        "filename": AGENT_GUIDE_FILENAME,
    }
