# Project Memory MCP Server: Technical Research Report

**Date**: 2026-07-02
**Scope**: Architecture research for a semantic code analysis MCP server (NO vector search as primary mechanism)

---

## 1. LLM-as-Judge: Code Analysis Output Quality

### 1.1 Validating LLM-Generated Code Analysis

The key pattern for validating LLM-produced code analysis (equation purpose, function responsibilities, data flow descriptions) is **two-stage verification**:

- **Stage 1 — Schema Enforcement**: Ensure the LLM output matches the expected JSON structure at generation time
- **Stage 2 — Semantic Audit**: Use a second LLM pass (or self-critique) to flag hallucinations — verify identified entities actually exist in source files by cross-referencing with the tree-sitter AST

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────┐
│  LLM analyzes   │────▶│ Schema enforced   │────▶│ Semantics cross-│
│  code snippet   │     │ via Instructor    │     │ checked w/ AST  │
└─────────────────┘     └──────────────────┘     └────────────────┘
```

### 1.2 Confidence Scoring Mechanisms

| Method | Description | Pros | Cons |
|--------|-------------|------|------|
| **Self-consistency** | Run same prompt N times (temp=0.3—0.7), score agreement rate | Simple, no extra model | Cost proportional to N |
| **Log-prob based** | Use `logprobs` from OpenAI/Anthropic API; token-level probability of generated analysis tokens | Directly from model | API-specific, not available on all providers |
| **Semantic grounding** | For each LLM claim (e.g., "this function computes factorial"), verify existence of referenced identifiers in the AST | Deterministic, no hallucination risk | Requires AST tooling |
| **Structural checks** | Verify required fields present, no extra fields | Pydantic handles this automatically | Doesn't catch wrong-but-valid-JSON |

**Recommendation**: Combine **semantic grounding** (cheap, deterministic) with **self-consistency N=3** (setup cost) for highest-confidence outputs. Set a threshold — if self-consistency agreement < 0.66, either re-prompt or flag as low-confidence.

### 1.3 JSON Schema Enforcement Techniques Comparison

#### A. `instructor` (13.4k ★, MIT license) — **RECOMMENDED**
```
pip install instructor
```

```python
import instructor
from pydantic import BaseModel, Field
from openai import OpenAI

class FunctionAnalysis(BaseModel):
    name: str
    purpose: str = Field(description="One-sentence summary of what this function computes")
    input_variables: list[str]
    output_variables: list[str]
    equations: list[str] = Field(description="Mathematical equations if any, e.g. 'y = mx + b'")
    called_functions: list[str]
    side_effects: list[str]
    complexity_notes: str

client = instructor.from_openai(OpenAI())

# Single call — Instructor handles retries on validation failure
analysis = client.chat.completions.create(
    response_model=FunctionAnalysis,
    messages=[{
        "role": "user",
        "content": f"Analyze this Python function:\n```python\n{source}\n```"
    }],
    max_retries=3,  # Auto-retry on Pydantic validation failure
)
# analysis is already a typed FunctionAnalysis instance
print(analysis.model_dump_json(indent=2))
```

**Why instructor wins for this project**:
- Works with **any provider** (OpenAI, Anthropic, Google, Ollama/Local) via `instructor.from_provider("anthropic/claude-3-5-sonnet")`
- **Automatic retries** with error feedback — failed validations are sent back to the LLM with the Pydantic error message
- **Streaming partial objects** possible for long analyses
- **Nested models** — parent analysis containing child function/variable analyses
- 3M+ monthly downloads, battle-tested, very active maintenance

#### B. `outlines` (14.3k ★, Apache 2.0) — Guaranteed grammar-level constraints

```
pip install outlines
```

```python
import outlines
from pydantic import BaseModel

class CodeEntity(BaseModel):
    entity_type: str  # "function", "class", "variable"
    name: str
    purpose: str

# Outlines guarantees the output WILL be valid JSON matching the Pydantic model
# by constraining token generation at the logit level
model = outlines.from_transformers(model, tokenizer)
result = model(prompt, CodeEntity)
parsed = CodeEntity.model_validate_json(result)
```

| Feature | instructor | outlines | guidance | raw Pydantic |
|---------|-----------|----------|----------|--------------|
| **Guaranteed valid JSON** | Provider-dependent (tool call mode) | ✅ Grammar-constrained generation | ✅ Grammar-constrained | ❌ Manual parsing |
| **Provider agnostic** | ✅ All major providers | ✅ Transformers, vLLM, Ollama, APIs | ✅ Transformers, llama.cpp, OpenAI | N/A (no LLM layer) |
| **Auto-retry on failure** | ✅ Built-in | ❌ Not needed (guaranteed) | ❌ Not needed (guaranteed) | N/A |
| **Streaming** | ✅ Partial objects | ❌ | ✅ | N/A |
| **Complexity** | Low | Medium | Medium | Low (manual) |
| **Python ecosystem** | pip install only | pip install only | Requires CUDA/compiler sometimes | stdlib |
| **Local model support** | ✅ (Ollama) | ✅ (native) | ✅ (native) | N/A |

#### C. `guidance` (21.5k ★, MIT) — Microsoft-backed

```
pip install guidance
```

```python
from guidance import json as gen_json
from pydantic import BaseModel, Field

lm = phi_lm  # guidance model object
class BloodPressure(BaseModel):
    systolic: int = Field(gt=300, le=400)
    diastolic: int

lm += gen_json(name="bp", schema=BloodPressure)
print(lm["bp"])  # guaranteed valid JSON matching schema, but string, not object
```

Guidance excels at **complex nested grammars** (like generating HTML) but for pure JSON schema enforcement on code analysis, instructor provides a cleaner API.

### 1.4 Final Recommendation

| Scenario | Tool |
|----------|------|
| **Using OpenAI/Anthropic API (cloud)** | `instructor` — simplest, auto-retry, broad provider support |
| **Running local models (Llama, Phi, etc.)** | `instructor` (Ollama mode) or `outlines` (if guaranteed generation matters more than retry logic) |
| **Need maximum schema guarantee for local models** | `outlines` — constrains at token-logit level, impossible to produce invalid JSON |
| **Complex nested grammar + text generation** | `guidance` |

**For Project Memory MCP: Use `instructor`** as primary with fallback to manual Pydantic validation. The auto-retry feature and provider neutrality are critical for an MCP server that may use different LLM backends.

---

## 2. SQLite FTS5 for Semantic Search Without Vectors

### 2.1 FTS5 Configuration Best Practices

```sql
-- Optimal setup for code search
CREATE VIRTUAL TABLE code_fts USING fts5(
    entity_name,
    entity_type,          -- "function", "class", "variable"
    source_code,
    docstring,
    analysis_summary,     -- LLM-generated summary text
    file_path UNINDEXED,  -- only needed for retrieval, not search
    rowid_range UNINDEXED,-- byte span in source
    tokenize='unicode61 remove_diacritics 2 tokenchars "-_"',
    prefix='2 3 4',       -- prefix indexes for partial-name queries
    columnsize=0,         -- save space if BM25 ranking not critical
    detail=column         -- reduce index size (omit position offsets)
);
```

**Key decisions**:

| Option | Recommendation | Rationale |
|--------|---------------|-----------|
| `tokenize` | `unicode61 tokenchars "-_"` | Treats `snake_case` and `kebab-case` as single tokens → `get_user_name` becomes token `get_user_name` not `get`, `user`, `name` |
| `prefix` | `'2 3 4'` | Enables fast `get*`, `get_u*`, `get_us*` prefix queries which are common in code search |
| `detail` | `column` | Saves ~40% index size vs `full` since we don't need offset-level snippets (we'll use `snippet()` differently) |
| `columnsize` | `1` (default) | Keep BM25 ranking; relevant code hits should be scored |
| `content` | Empty string for contentless tables OR external content table pointing to a regular SQLite table with actual code text | Separates raw storage from search index |

### 2.2 Three-Tier Query Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│                      QUERY PIPELINE                               │
├─────────────┬────────────────────┬───────────────────────────────┤
│  TIER 1     │  TIER 2            │  TIER 3                       │
│ Exact Match │  FTS5 Full-Text    │  Graph Traversal              │
│ (SQL index) │  (MATCH operator)  │  (Adjacency table BFS/DFS)    │
├─────────────┼────────────────────┼───────────────────────────────┤
│ Use case:   │ Use case:          │ Use case:                     │
│ "Find       │ "Find functions    │ "Given function_A, find all   │
│ function_A" │ that compute       │ functions that call it AND    │
│             │ interest rates"    │ all functions IT calls"       │
├─────────────┼────────────────────┼───────────────────────────────┤
│ Latency:    │ Latency:           │ Latency:                      │
│ ~0.2ms      │ ~2-15ms            │ ~10-500ms (depth-dependent)   │
├─────────────┼────────────────────┼───────────────────────────────┤
│ Mechanism:  │ Mechanism:         │ Mechanism:                    │
│ B-tree      │ FTS5 inverted      │ SQLite recursive CTE or       │
│ index on    │ index with BM25    │ Python-level BFS on           │
│ entity_name │ ranking            │ adjacency table               │
└─────────────┴────────────────────┴───────────────────────────────┘
```

```python
# Unified query execution example
def three_tier_search(query: str, max_results: int = 20) -> list[dict]:
    results = []

    # TIER 1: Exact name match — fastest
    exact = db.execute("""
        SELECT rowid, entity_name, entity_type, file_path, rowid_range
        FROM code_entities
        WHERE entity_name = ?
        LIMIT ?
    """, (query, max_results)).fetchall()
    results.extend([dict(r) for r in exact])
    seen_ids = {r["rowid"] for r in results}

    # TIER 2: FTS5 full-text — fallback when exact match insufficient
    if len(results) < max_results:
        fts_results = db.execute("""
            SELECT code_fts.rowid, entity_name, entity_type, file_path,
                   snippet(code_fts, 1, '<mark>', '</mark>', '...', 64),
                   bm25(code_fts, 0.0, 5.0, 0.0, 0.0, 1.0) AS rank
            FROM code_fts
            WHERE code_fts MATCH ?
              AND code_fts.rowid NOT IN ({})
            ORDER BY rank
            LIMIT ?
        """.format(",".join("?" * len(seen_ids))),
            (query, *seen_ids, max_results - len(results))
        ).fetchall()
        results.extend([dict(r) for r in fts_results])

    # TIER 3: Graph expansion — traverse call/data deps for context
    if len(results) < max_results:
        for root_id in seen_ids:
            neighbors = graph_traverse_bfs(db, root_id, depth=2)
            for n in neighbors:
                if n["rowid"] not in seen_ids:
                    results.append(n)
                    seen_ids.add(n["rowid"])
                    if len(results) >= max_results:
                        break

    return results[:max_results]
```

### 2.3 FTS5 vs Vector Search for Code Queries

| Query Type | FTS5 | Vector Embedding |
|-----------|------|-----------------|
| `find "calculate_tax"` (exact name) | **0.2ms**, perfect precision | ~5ms, may return `calc_tax`, `compute_vat`, etc. |
| `"factorial computation"` (semantic) | Poor (no synonym understanding) | Good (semantic similarity) |
| `"sqlite OR postgres AND database"` (boolean) | **Excellent**, native boolean operators | Awkward (must filter post-retrieval) |
| `"calculate*"` (prefix) | **Native prefix index**, instant | Not supported natively |
| `NEAR("error handle", 5)` (proximity) | **Native NEAR queries** | Cannot express proximity |
| Scaling to 1M+ code entities | **Excellent** (proven at billions of docs) | Degrades (ANN index grows) |
| Cold start (no GPU) | **Instant** (CPU-only, tiny library) | Requires embedding model + GPU or slow CPU |

**Conclusion**: FTS5 is **superior** for code search because code search is predominantly **identifier/text-based**, not semantic. Users search for "function that computes tax" by name (`calculate_tax`) not by embedding. The 3-tier pipeline covers exact, full-text, and graph — no vector needed.

### 2.4 Custom Tokenizer Strategy for Code

Rather than writing a C tokenizer extension (complex), use **Python pre-processing** before insertion:

```python
import re

def tokenize_for_code(text: str) -> str:
    """Pre-process identifiers so FTS5 treats them as single tokens."""
    # 1. Preserve snake_case, camelCase, PascalCase as single tokens
    #    by replacing internal boundaries with a tokenchar that FTS5 keeps
    #    (we configured tokenchars='-_' in the CREATE VIRTUAL TABLE)
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', '_', text)  # camelCase → camel_Case

    # 2. Convert dots in qualified names to underscores
    text = re.sub(r'\.', '_', text)  # module.func → module_func

    # 3. Wrap identifiers the user wants to search as exact phrases in double-quotes
    #    This is done at QUERY time, not insertion time.

    return text

# Insertion
code_text = "def get_user_name(user_id: int) -> str:"
tokenized = tokenize_for_code(code_text)
db.execute("INSERT INTO code_fts(entity_name, source_code) VALUES (?, ?)",
           ("get_user_name", tokenized))

# Query time — use double-quoted phrases for exact multi-token identifiers
db.execute("SELECT * FROM code_fts WHERE code_fts MATCH ?",
           ('"get_user_name" AND user_id',))
```

**Alternative**: Pre-built trigram tokenizer for substring matching:

```sql
CREATE VIRTUAL TABLE code_fts USING fts5(
    entity_name, source_code,
    tokenize='trigram',  -- any 3-char substring becomes a token
    detail=column
);

-- Now queries like 'user' match inside 'get_user_name' without needing explicit token boundaries
SELECT * FROM code_fts('user');
-- Also supports LIKE/GLOB with index acceleration:
SELECT * FROM code_fts WHERE source_code LIKE '%get_user%';
```

**Recommendation**: Use `unicode61 tokenchars "-_"` for primary search (preserves identifier integrity) + `trigram` on a second FTS5 virtual table for substring fallback when exact and FTS5 phase queries return insufficient results.

---

## 3. Graph Query Without Neo4j — Embeddable Alternatives

### 3.1 KuzuDB vs SQLite Adjacency Model

| Feature | KuzuDB | SQLite Adjacency |
|---------|--------|-----------------|
| **License** | MIT | Public domain |
| **Current status** | **ARCHIVED** Oct 2025 (repo read-only, v0.11.3 last release) | Actively maintained |
| **Embeddability** | C++ lib, Python bindings via `pip install kuzu` | Native Python `sqlite3` module |
| **Query language** | Cypher (openCypher subset) | Recursive CTEs in SQL |
| **Storage format** | Columnar disk-based | Row-based B-tree |
| **Performance** | Excellent for analytical graph queries (columnar + vectorized) | Adequate for code-scale graphs (<500K nodes) |
| **Dependencies** | Heavy C++ build, ~50MB compiled lib | Zero (Python stdlib) |
| **Future** | Archived — no further updates | Guaranteed long-term stability |

**Verdict**: KuzuDB is **not recommended** — archived as of Oct 2025. The last release v0.11.3 bundles extensions locally but the project is frozen.

### 3.2 SQLite Adjacency Model Implementation

```sql
-- Schema for code dependency graph
CREATE TABLE code_entities (
    rowid INTEGER PRIMARY KEY,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,  -- 'function', 'class', 'method', 'variable', 'module'
    file_path TEXT NOT NULL,
    start_byte INTEGER,
    end_byte INTEGER,
    source_hash TEXT,           -- SHA256 of source text for change detection
    last_indexed_at TEXT
);

CREATE TABLE code_edges (
    source_id INTEGER NOT NULL REFERENCES code_entities(rowid),
    target_id INTEGER NOT NULL REFERENCES code_entities(rowid),
    edge_type TEXT NOT NULL,    -- 'calls', 'imports', 'defines', 'references', 'inherits'
    file_path TEXT,
    line_number INTEGER,
    PRIMARY KEY (source_id, target_id, edge_type)
);

-- Index for fast traversal
CREATE INDEX idx_edges_source ON code_edges(source_id, edge_type);
CREATE INDEX idx_edges_target ON code_edges(target_id, edge_type);
```

### 3.3 Graph Traversal on SQLite Adjacency Tables

#### BFS (Breadth-First Search) — Impact Analysis: "Who calls function X?"

```python
import sqlite3
from collections import deque

def bfs_callers(db: sqlite3.Connection, entity_id: int, max_depth: int = 5) -> list[dict]:
    """Find all functions that directly or transitively call entity_id."""
    visited = set()
    queue = deque([(entity_id, 0)])
    results = []

    while queue:
        current_id, depth = queue.popleft()
        if current_id in visited or depth > max_depth:
            continue
        visited.add(current_id)

        # Find callers: edges where target_id = current_id and edge_type = 'calls'
        callers = db.execute("""
            SELECT ce.rowid, ce.entity_name, ce.entity_type, ce.file_path,
                   e.line_number
            FROM code_edges e
            JOIN code_entities ce ON ce.rowid = e.source_id
            WHERE e.target_id = ? AND e.edge_type = 'calls'
        """, (current_id,)).fetchall()

        for caller in callers:
            if caller["rowid"] not in visited:
                queue.append((caller["rowid"], depth + 1))
                results.append({**dict(caller), "depth": depth + 1})

    return results
```

#### DFS (Depth-First Search) — Dependency Chain: "What does function X depend on?"

```python
def dfs_dependencies(db: sqlite3.Connection, entity_id: int, max_depth: int = 10) -> list[dict]:
    """Find all transitive dependencies of entity_id (functions it calls)."""
    visited = set()
    results = []
    stack = [(entity_id, 0, [])]  # (node_id, depth, path)

    while stack:
        current_id, depth, path = stack.pop()
        if current_id in visited or depth > max_depth:
            continue
        visited.add(current_id)

        deps = db.execute("""
            SELECT ce.rowid, ce.entity_name, ce.entity_type, ce.file_path
            FROM code_edges e
            JOIN code_entities ce ON ce.rowid = e.target_id
            WHERE e.source_id = ? AND e.edge_type = 'calls'
        """, (current_id,)).fetchall()

        for dep in deps:
            dep_path = path + [dep["entity_name"]]
            if dep["rowid"] not in visited:
                stack.append((dep["rowid"], depth + 1, dep_path))
                results.append({**dict(dep), "depth": depth + 1, "path": " → ".join(dep_path)})

    return results
```

#### Recursive CTE (Pure SQL) — for moderate depths

```sql
-- Find all transitive callers of function with rowid = 42, max depth 5
WITH RECURSIVE callers(depth, source_id, target_id, path) AS (
    -- Base case: direct callers
    SELECT 1, e.source_id, e.target_id, ce.entity_name
    FROM code_edges e
    JOIN code_entities ce ON ce.rowid = e.source_id
    WHERE e.target_id = 42 AND e.edge_type = 'calls'

    UNION ALL

    -- Recursive step: callers of callers
    SELECT c.depth + 1, e.source_id, e.target_id,
           c.path || ' → ' || ce.entity_name
    FROM code_edges e
    JOIN callers c ON e.target_id = c.source_id
    JOIN code_entities ce ON ce.rowid = e.source_id
    WHERE e.edge_type = 'calls'
      AND c.depth < 5
)
SELECT DISTINCT source_id AS rowid, path, depth
FROM callers
ORDER BY depth;
```

### 3.4 Apache AGE — Viability for Embeddable Use

| Factor | Assessment |
|--------|------------|
| **Embedded use** | ❌ **Not viable**. Requires a full PostgreSQL 11—18 server installation (~200MB+). Cannot be embedded as a library in a Python process. |
| **Dependencies** | Requires PostgreSQL dev headers, GCC, bison, flex, readline, zlib |
| **Query language** | openCypher + PostgreSQL SQL — powerful hybrid queries |
| **Install complexity** | `make PG_CONFIG=/path/to/pg_config install` then `CREATE EXTENSION age; LOAD 'age';` |
| **License** | Apache 2.0 |
| **Use case fit** | Server-side graph applications, not embeddable MCP servers |

**Verdict**: **Not suitable** for an embeddable MCP server. The PostgreSQL dependency is a dealbreaker.

### 3.5 DuckDB as an Alternative

| Factor | Assessment |
|--------|------------|
| **Embedded use** | ✅ **Excellent**. `pip install duckdb`, zero dependencies, in-process. |
| **Graph queries** | No native graph support, but **recursive CTEs + excellent SQL performance** make it viable for adjacency-table traversal |
| **Performance** | Columnar, vectorized execution — up to 10-50x faster than SQLite for analytical queries |
| **FTS capability** | No built-in FTS (must roll your own inverted index or use SQLite for FTS + DuckDB for graph analytics) |
| **License** | MIT |
| **Size** | ~15MB Python wheel |

**Verdict**: DuckDB is a strong candidate if you have >100K code entities and need fast recursive CTEs. However, the **dual-database approach** (SQLite for FTS5 + DuckDB for graph analytics) adds complexity:

```python
import duckdb

# DuckDB can directly query SQLite files
duckdb.execute("ATTACH 'code_memory.db' AS sqlite_db (TYPE SQLITE)")

# Run recursive CTE on SQLite-backed data with DuckDB's engine
callers = duckdb.execute("""
    WITH RECURSIVE callers AS (
        SELECT source_id, target_id, 1 AS depth
        FROM sqlite_db.code_edges
        WHERE target_id = 42 AND edge_type = 'calls'
        UNION ALL
        SELECT e.source_id, e.target_id, c.depth + 1
        FROM sqlite_db.code_edges e
        JOIN callers c ON e.target_id = c.source_id
        WHERE e.edge_type = 'calls' AND c.depth < 10
    )
    SELECT * FROM callers
""").fetchall()
```

### 3.6 Final Recommendation

**Use SQLite adjacency tables + Python-level BFS/DFS** for the graph layer:
- Zero dependencies (Python stdlib `sqlite3`)
- Adequate performance for codebase scales (<500K entities)
- Simple implementation
- If scaling issues arise, swap in DuckDB for recursive CTE acceleration without schema changes

---

## 4. Incremental Re-Indexing Strategies

### 4.1 Git Diff-Based Change Detection

```python
import subprocess
import os

def get_changed_files_since(project_root: str, last_commit: str) -> set[str]:
    """Return set of changed file paths since last indexed commit."""
    result = subprocess.run(
        ["git", "-C", project_root, "diff", "--name-only", last_commit, "HEAD"],
        capture_output=True, text=True
    )
    return set(line.strip() for line in result.stdout.splitlines() if line.strip())

def get_changed_lines_in_file(project_root: str, file_path: str,
                               last_commit: str) -> list[tuple[int, int]]:
    """Return list of (start_line, end_line) changed ranges in a file."""
    result = subprocess.run(
        ["git", "-C", project_root, "diff", "--unified=0", last_commit, "HEAD", "--", file_path],
        capture_output=True, text=True
    )
    # Parse @@ -old_start,old_count +new_start,new_count @@ headers
    import re
    ranges = []
    for match in re.finditer(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', result.stdout):
        start = int(match.group(1))
        count = int(match.group(2) or 1)
        ranges.append((start, start + count))
    return ranges
```

### 4.2 File Hash (SHA256) vs mtime

| Method | Accuracy | Speed | Portability | Notes |
|--------|----------|-------|-------------|-------|
| **SHA256** of file content | ✅ Perfect — any content change detected | ~5-50ms/file (depends on file size) | ✅ Cross-platform | **Recommended**. No false positives. |
| **mtime** (modification time) | ❌ Fragile — `git checkout` touches mtime even if unchanged; some editors save without changes; CI clones reset mtime | <0.1ms/file (stat call) | ❌ Windows mtime resolution is 2s (FAT) or 100ns (NTFS) — inconsistent | False positives cause unnecessary re-indexing |
| **git hash-object** | ✅ Same as SHA256 but uses git's object store | ~5-50ms/file | ✅ (requires git) | Good for git-tracked projects |
| **mtime + size** | Better than mtime alone but still fragile | <0.1ms/file | ✅ | Still has false positive risk |

```python
import hashlib

def compute_file_hash(filepath: str) -> str:
    """SHA256 of file contents — reliable change detection."""
    sha = hashlib.sha256()
    with open(filepath, 'rb') as f:
        # Read in chunks to handle large files
        for chunk in iter(lambda: f.read(65536), b''):
            sha.update(chunk)
    return sha.hexdigest()

# Store in DB:
db.execute("""
    CREATE TABLE indexed_files (
        file_path TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL,
        last_indexed_at TEXT NOT NULL,
        entity_count INTEGER
    )
""")

# Check if re-index needed:
def needs_reindex(db, file_path: str) -> bool:
    current_hash = compute_file_hash(file_path)
    row = db.execute("SELECT content_hash FROM indexed_files WHERE file_path = ?",
                     (file_path,)).fetchone()
    if row is None:
        return True  # never indexed
    return row["content_hash"] != current_hash
```

### 4.3 `codebase-memory-mcp` Reference

The repository `github.com/rxc4/codebase-memory-mcp` was not found (404). However, a similar project pattern can be inferred: **C-based file watcher** on Linux uses `inotify`, on macOS uses `FSEvents`, and on Windows uses `ReadDirectoryChangesW`. For Python, the approach is:

### 4.4 Python File Watchers for Windows

| Library | Windows Support | Mechanism | Dependencies | Notes |
|---------|----------------|-----------|-------------|-------|
| **`watchdog`** (6k ★) | ✅ Full support | `ReadDirectoryChangesW` API | Pure Python + optional C ext | **Recommended**. Cross-platform, mature. |
| **`watchfiles`** (2k ★) | ✅ Full support | Rust `notify` crate via PyO3 | Rust compiled wheel | Faster than watchdog, async-native. |
| **Simple polling** | ✅ N/A | `os.stat()` loop | Zero | Simplest, CPU cost for large repos |

```python
# Approach A: watchdog (polling-based on Windows, event-based on Linux/macOS)
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class CodeChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith(('.py', '.js', '.ts', '.rs', '.go', '.java', '.c', '.cpp', '.h')):
            schedule_reindex(event.src_path)

observer = Observer()
observer.schedule(CodeChangeHandler(), path=project_root, recursive=True)
observer.start()

# Approach B: Simple polling loop (works everywhere, zero deps)
import time, os

def polling_watcher(project_root: str, interval: float = 2.0):
    """Poll every N seconds for changed files."""
    known = {}  # filepath → (mtime, size)
    while True:
        for dirpath, _, filenames in os.walk(project_root):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    stat = os.stat(fp)
                    key = (stat.st_mtime, stat.st_size)
                    if fp not in known or known[fp] != key:
                        known[fp] = key
                        yield fp  # changed or new
                except OSError:
                    continue
        time.sleep(interval)
```

### 4.5 Incremental Re-Index Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│              INCREMENTAL RE-INDEX PIPELINE                       │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│ Detect   │ Parse    │ Diff     │ Update   │ Re-analyze          │
│ Change   │ AST      │ Entities │ DB       │ (LLM)              │
├──────────┼──────────┼──────────┼──────────┼─────────────────────┤
│ SHA256   │ tree-    │ Compare  │ DELETE   │ Only for new/       │
│ hash or  │ sitter   │ old vs   │ old      │ changed entities    │
│ git diff │ parse    │ new AST  │ entities │ — send to LLM       │
│          │          │ entities │ INSERT   │ with instructor      │
│          │          │          │ new      │ schema enforcement  │
├──────────┼──────────┼──────────┼──────────┼─────────────────────┤
│ <50ms    │ <100ms   │ <10ms    │ <20ms    │ ~200-2000ms         │
│          │          │          │          │ (per entity, async) │
└──────────┴──────────┴──────────┴──────────┴─────────────────────┘
```

**Recommendation**: Use **SHA256 hash comparison** + **simple polling loop** for detection (zero dependencies). For production use with large repos, add `watchfiles` as an optional accelerator.

---

## 5. Static Analysis Tools for Multi-Language Code

### 5.1 Tree-sitter Python Bindings — Setup and Usage

```bash
pip install tree-sitter          # core bindings (pre-compiled wheels)
pip install tree-sitter-python   # Python grammar
pip install tree-sitter-javascript
pip install tree-sitter-typescript
pip install tree-sitter-rust
pip install tree-sitter-go
pip install tree-sitter-java
pip install tree-sitter-c
pip install tree-sitter-cpp
# ~30+ languages available
```

```python
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Parser, Query

# Register languages
LANGUAGES = {
    ".py": Language(tspython.language()),
    ".js": Language(tsjavascript.language()),
    ".ts": Language(tsjavascript.language()),  # TS shares JS grammar with TS extensions
}

def get_language(filepath: str) -> Language:
    ext = os.path.splitext(filepath)[1]
    return LANGUAGES.get(ext)

parser = Parser()
parser.language = LANGUAGES[".py"]

source = b"""
def calculate_interest(principal: float, rate: float, years: int) -> float:
    '''Compute compound interest: A = P(1 + r)^t'''
    return principal * (1 + rate) ** years

class Account:
    balance: float = 0.0
    def deposit(self, amount: float) -> None:
        self.balance += amount
"""

tree = parser.parse(source)
```

### 5.2 Tree-sitter Query Language Examples

```python
# --- FUNCTION DEFINITIONS ---
FUNCTION_QUERY = """
(function_definition
  name: (identifier) @function.name
  parameters: (parameters) @function.params
  return_type: (type)? @function.return_type
  body: (block) @function.body
) @function.def
"""

# --- CLASS DEFINITIONS ---
CLASS_QUERY = """
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list)? @class.superclasses
  body: (block) @class.body
) @class.def
"""

# --- VARIABLE ASSIGNMENTS ---
VARIABLE_QUERY = """
(assignment
  left: (identifier) @variable.name
  right: (_) @variable.value
) @variable.assign

; Also catch annotated assignments (Python 3.6+)
(annotated_assignment
  left: (identifier) @variable.name
  type: (_) @variable.type
) @variable.annotated
"""

# --- IMPORT STATEMENTS ---
IMPORT_QUERY = """
(import_statement
  name: (dotted_name) @import.module
) @import.stmt

(import_from_statement
  module_name: (dotted_name) @import.from_module
  name: (dotted_name) @import.name
) @import.from_stmt
"""

# --- FUNCTION CALLS ---
CALL_QUERY = """
(call
  function: (identifier) @call.func_name
  arguments: (argument_list) @call.args
) @call.expr

; Also catch method calls: obj.method()
(call
  function: (attribute
    object: (_) @call.object
    attribute: (identifier) @call.method_name
  )
  arguments: (argument_list) @call.args
) @call.method
"""

# --- EXTRACTING DOCSTRINGS / COMMENTS ---
DOCSTRING_QUERY = """
(expression_statement
  (string) @docstring
  (#match? @docstring "^(\\\"\\\"\\\"|''')")
)

(comment) @comment
"""
```

```python
# Execute queries and extract structured data
def extract_code_entities(parser, source: bytes, language) -> dict:
    tree = parser.parse(source)
    root = tree.root_node

    entities = {"functions": [], "classes": [], "variables": [], "imports": [], "calls": []}

    # Functions
    query = Query(language, FUNCTION_QUERY)
    cursor = QueryCursor(query)
    for match in cursor.matches(root):
        entities["functions"].append({
            "name": match[1]["function.name"][0].text.decode(),
            "start_byte": match[0][0].start_byte,
            "end_byte": match[0][0].end_byte,
            "source": source[match[0][0].start_byte:match[0][0].end_byte].decode(),
        })

    # Classes
    query = Query(language, CLASS_QUERY)
    cursor = QueryCursor(query)
    for match in cursor.matches(root):
        entities["classes"].append({
            "name": match[1]["class.name"][0].text.decode(),
            "start_byte": match[0][0].start_byte,
            "end_byte": match[0][0].end_byte,
            "source": source[match[0][0].start_byte:match[0][0].end_byte].decode(),
        })

    return entities
```

### 5.3 Extracting Docstrings and Comments via Tree-sitter

```python
def extract_docstring(function_node, source: bytes) -> str | None:
    """Extract docstring from a function_definition AST node."""
    body = function_node.child_by_field_name("body")
    if body is None:
        return None

    # First statement in the block
    first_stmt = body.child(0) if body.child_count > 0 else None
    if first_stmt is None:
        return None

    # Check if it's an expression_statement containing a string
    if first_stmt.type == "expression_statement":
        string_node = first_stmt.child(0)
        if string_node and string_node.type == "string":
            text = source[string_node.start_byte:string_node.end_byte].decode()
            # Docstrings are triple-quoted strings
            if text.startswith('"""') or text.startswith("'''"):
                return text.strip('"\'')

    return None

# For full-comment extraction, use tree-sitter's comment nodes
def extract_all_comments(parser, source: bytes, language) -> list[dict]:
    tree = parser.parse(source)
    query = Query(language, "(comment) @comment")
    cursor = QueryCursor(query)
    comments = []
    for match in cursor.matches(tree.root_node):
        node = match[1]["comment"][0]
        comments.append({
            "text": source[node.start_byte:node.end_byte].decode().lstrip("# ").strip(),
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
        })
    return comments
```

### 5.4 Language-Specific Tree-sitter Node Types

| Language | Function Def | Class Def | Variable Assign | Import | Call |
|----------|-------------|-----------|----------------|--------|------|
| **Python** | `function_definition` | `class_definition` | `assignment` / `annotated_assignment` | `import_statement` / `import_from_statement` | `call` |
| **JavaScript/TS** | `function_declaration` / `arrow_function` | `class_declaration` | `variable_declarator` | `import_statement` | `call_expression` |
| **Rust** | `function_item` | `struct_item` / `impl_item` | `let_declaration` | `use_declaration` | `call_expression` |
| **Go** | `function_declaration` | `type_declaration` (struct) | `short_var_declaration` / `var_spec` | `import_declaration` | `call_expression` |
| **C** | `function_definition` | `struct_specifier` | `init_declarator` | `preproc_include` | `call_expression` |
| **C++** | `function_definition` | `class_specifier` | `init_declarator` | `preproc_include` / `using_declaration` | `call_expression` |
| **Java** | `method_declaration` | `class_declaration` | `local_variable_declaration` | `import_declaration` | `method_invocation` |

### 5.5 LSP Integration Alternatives for Semantic Type Info

Tree-sitter provides **syntax-level** information (structure, names, positions). For **semantic-level** info (type resolution, jump-to-definition, reference finding), LSP servers are needed:

| Tool | Language Coverage | Embeddable? | Setup Complexity |
|------|------------------|-------------|-----------------|
| **jedi** | Python only | ✅ Pure Python, `pip install jedi` | Trivial |
| **pyright** | Python + TypeScript | ✅ Node.js-based, `pip install pyright` | Low |
| **rust-analyzer** | Rust | ❌ Requires running LSP server process | High |
| **clangd** | C/C++ | ❌ Requires running LSP server + `compile_commands.json` | High |
| **gopls** | Go | ❌ Requires running LSP server + `go.mod` | Medium |

For a Python MCP server that primarily analyzes Python code (but can parse other languages structurally via tree-sitter):

```python
# jedi for Python semantic type information
import jedi

def get_semantic_info(source: str, file_path: str) -> dict:
    script = jedi.Script(source, path=file_path)

    semantic = {
        "names": [],
        "references": [],
        "inferences": [],
    }

    for name in script.get_names(all_scopes=True):
        semantic["names"].append({
            "name": name.name,
            "type": name.type,          # 'function', 'class', 'statement', 'param'
            "line": name.line,
            "description": name.description,
            "full_name": name.full_name,
        })

        for ref in name.get_references():
            semantic["references"].append({
                "from_name": name.name,
                "to_line": ref.line,
                "to_column": ref.column,
            })

        # Type inference
        if name.type in ('statement', 'param'):
            try:
                inferred = name.infer()
                if inferred:
                    semantic["inferences"].append({
                        "name": name.name,
                        "inferred_type": str(inferred[0].description),
                    })
            except Exception:
                pass

    return semantic
```

**Recommendation**: Use **tree-sitter** for structural extraction (works on 30+ languages) + **jedi** for Python semantic enrichment. For other languages, tree-sitter alone provides enough structure for the graph layer.

---

## 6. Parallel Indexing & Dependency-Aware Analysis Pipeline

### 6.1 Problem Statement
When indexing large codebases with hundreds of files, sequentially parsing every file via Tree-sitter and generating summaries using LLM endpoints creates a massive bottleneck. LLM API network roundtrips (often taking 1-3 seconds per file) are particularly expensive. A naive concurrent implementation that fires requests for all files simultaneously will:
1. Violate Rate Limits (HTTP 429) on LLM Gateways.
2. Generate suboptimal LLM analysis, since child classes or functions are analyzed before their parents' contextual summaries exist.

### 6.2 Architecture of the Parallel Pipeline
The Project Memory MCP implements a hybrid, dependency-aware parallel processing pipeline that optimizes local compute (parsing ASTs) and remote network calls (LLM summaries).

```
[Scan Workspace File Paths]
          │
          ▼
[Step 1: Extract AST Imports/Symbols in Thread Pool (ParallelStaticAnalyzer)]
          │
          ▼
[Step 2: Build Dependency Graph (DependencyGraphBuilder)]
          │
          ▼
[Step 3: Kahn's Topological Sort (TopologicalSorter)]
          │
          ▼
[Step 4: Group Files into Independent Levels (AnalysisGroup)]
          │
          ▼
[Step 5: Process Levels Sequentially, and Files inside each level Concurrently]
   ├─► Level 0: [File_A (No deps)]  [File_B (No deps)]   (Semaphore Limit = 2)
   │               │                   │
   │               └─────────┬─────────┘ (Complete)
   ▼                         ▼
   └─► Level 1: [File_C (Depends on A/B)]                (LLM references parent contexts)
```

### 6.3 Kahn's Algorithm for Topological Levels
To sort the source files so that dependents are analyzed after their dependencies, we model files as vertices $V$ and imports/calls as directed edges $E$. We use **Kahn's Algorithm** to compute topological levels:

1. **In-degree Count**: Calculate $in\_degree[v]$ (the number of incoming dependencies for each file).
2. **Level Initialization**: Identify all files with $in\_degree[v] = 0$. These form `Level 0` (independent files).
3. **Iterative Reduction**: For each level, process its files. For each processed file $u$, locate all dependent files $w$ (where there is a directed dependency edge $u \to w$). Decrement $in\_degree[w]$ by 1.
4. **Next Level**: All files $w$ whose $in\_degree[w]$ drops to $0$ are assigned to the next topological level, to be processed in the next parallel batch.

This guarantees that a child class or function file is analyzed only after its base class/module file's LLM summary is fully generated and cached in the SQLite database, enabling the LLM to access the parent's context.

### 6.4 Concurrency Control Mechanisms
To balance processing speed and resource consumption:
1. **Thread Pool Executor**: CPU-bound tree-sitter parses run in a `concurrent.futures.ThreadPoolExecutor` (configured via `max_workers`). This keeps the event loop unblocked.
2. **asyncio.Semaphore**: Network-bound LLM tasks are scheduled concurrently using an `asyncio.Semaphore(max_llm_concurrent)` to strictly limit concurrent connections and prevent HTTP 429 rate limit cooling states in the LLM Gateway.
3. **Batching**: Files are processed in configurable chunk batches (`batch_size`) during static analysis to avoid memory spikes.

### 6.5 Performance Comparison (Qualitative)

| Metric | Sequential Pipeline | Parallel Dependency-Aware Pipeline |
|--------|---------------------|-----------------------------------|
| **Static Parsing Speed** | $O(N)$ sequential thread blocks | $O(N / \text{workers})$ using worker thread pools |
| **LLM Call Speed** | $O(N \times \text{RTT})$ | $O(L \times \text{RTT} + (N / \text{max\_llm}))$, where $L$ is number of levels |
| **Contextual Accuracy** | Low (random order, missing parent context) | **High** (dependents always refer to pre-analyzed parent summaries) |
| **Gateway Rate Limits** | Minimal risk (slow) | **Managed** (bounded by semaphore, no 429 triggers) |

---

## Summary: Architecture Recommendations

| Layer | Recommended Technology | Rationale |
|-------|----------------------|-----------|
| **Structured LLM output** | `instructor` + Pydantic | Provider-neutral, auto-retry, most mature ecosystem |
| **Full-text search** | SQLite FTS5 `unicode61` + tokenchars for `_-` | Zero-dependency, superior for code identifier search, native boolean/proximity/prefix operators |
| **Substring fallback** | SQLite FTS5 `trigram` (second table) | Enables `LIKE`-accelerated substring queries when exact+FTS5 insufficient |
| **Graph storage + traversal** | SQLite adjacency tables + Python BFS/DFS | Zero-dependency, adequate for <500K nodes, simple |
| **Analytical graph queries (opt.)** | DuckDB attached to SQLite file | 10-50x faster recursive CTEs when scaling, no schema changes needed |
| **Change detection** | SHA256 file hash + simple polling | Reliable, no false positives, zero dependencies |
| **File watching (opt.)** | `watchfiles` (Rust-backed) | Async-native, faster than watchdog |
| **Static analysis** | `tree-sitter` (30+ languages) + `jedi` (Python semantic) | Structural extraction for all languages, semantic enrichment for Python |
| **Database** | SQLite (stdlib `sqlite3`) | Single-file, zero-config, FTS5 built-in, adjacency model straightforward |