# Project Memory MCP

A project-local, LLM-driven knowledge graph MCP server for safe code understanding, equation tracking, impact analysis, and agent-assisted editing.

## Features

- **Multi-language support**: Python, TypeScript, JavaScript, Rust, Go, Java, C, C++, and more via tree-sitter
- **LLM-driven analysis**: Uses LLMs to understand code semantics, equations, and relationships
- **Knowledge graph**: SQLite-based graph with files, symbols, equations, variables, and dependencies
- **Impact analysis**: Analyze the effect of changes before making them
- **Delete safety**: Check references and dependents before deletion
- **Incremental updates**: Only re-scan changed files using SHA256 hash comparison
- **MCP tools**: Full MCP server with tools, resources, and prompts
- **Agent-driven mode**: Works with any AI agent (Claude Code, Cursor, etc.)
- **Auto-generated manual**: Creates PROJECT_AGENT_MANUAL.md for each project
- **Configuration-driven workflow**: Automated pipeline via YAML/JSON config files

## Installation

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .

# Or, after the npm wrapper is published
npm install -g project-memory-mcp
```

For MCP client snippets for Claude/Cursor/Codex-style tools, see
[`AGENT_SETUP.md`](AGENT_SETUP.md).

## Quick Start

### 1. Initialize a project

```bash
project-memory init .
```

Or use the MCP tool:
```
project.bootstrap(project_path=".")
```

### 2. Index the repository

```bash
project-memory index .
```

Or use the MCP workflow:
```
project.plan_indexing(project_path=".")
project.scan_files(project_path=".")
# Then run analysis tasks via get_next_analysis_task / submit_*_analysis
```

### 2b. Description/summary generation

`init`/`index` only ingests file contents and extracts **static** structure
(symbols, imports, calls) into the knowledge graph. Descriptions are generated
with this policy:

1. The default path is **server-driven local analysis** against
   `http://localhost:4000/v1` using model `patcher-main`.
2. If that local endpoint is unavailable, the MCP tool does **not** silently ask
   the calling agent to spend its own tokens. It returns a fallback instruction
   telling the agent to ask the user whether agent-driven analysis is allowed.
3. If the user does not allow agent-driven analysis, Project Memory keeps the
   static map only: files, symbols, imports, calls, hashes, and graph edges are
   still recorded; LLM summaries remain pending.

Start local background analysis through MCP:

```
project.start_analysis_loop(project_path=".")
project.get_analysis_progress(project_path=".")
```

If the local endpoint is unavailable and the user explicitly permits the agent
to run analysis itself, use this fallback loop:

```
# 1. The MCP server returns a fully-formatted prompt + JSON Schema.
task = project.get_next_analysis_task(project_path=".", task_type="file")
# task.system_prompt, task.user_prompt (contains the source code),
#       task.output_schema (JSON Schema), task.output_schema_name

# 2. The agent reads the prompt, analyzes the source, and produces JSON
#    conforming to task.output_schema.

# 3. The agent submits the structured result; the server validates it
#    (Pydantic) and writes summary/key_concepts/risk_notes back to the DB.
project.submit_file_analysis(task_id=task.task_id,
                             file_path=task.file_path,
                             analysis={...})   # validated against output_schema

# 4. Repeat until task.task_id == "" (no more tasks), then do the same
#    for task_type="symbol" and task_type="equation".
```

Prompts and schemas live in `llm_analysis/schemas.py` (`BUILTIN_PROMPTS`),
so you can tune the analysis intent centrally. Each submit validates and stores
the description into the `files`/`symbols`/`equations` tables.


Or use the MCP workflow:
```
project.plan_indexing(project_path=".")
project.scan_files(project_path=".")
# Then run analysis tasks via get_next_analysis_task / submit_*_analysis
```

### 3. Query the knowledge graph

Once the agent-driven analysis loop is complete, every analyzed file carries
`llm_summary` / `key_concepts` / `purpose`. Search by **what a file does**
rather than by exact path:

```
# MCP: rank files by description match, analyzed-first
project.search_files(project_path=".", query="PID controller")
project.search_files(project_path=".", query="auth", only_analyzed=True)
```

Then drill into a specific file/symbol/equation:

```bash
# Query a file
project-memory query file src/controller.py

# Query a symbol
project-memory query symbol compute_control

# Query equations
project-memory query equation PID

# Impact analysis
project-memory impact equation PID --operation modify
```

## Comprehensive Usage Guide

### Configuration File Support

Project Memory MCP now supports configuration files (YAML or JSON) for automated, reproducible workflows.

#### Creating a Configuration File

Create a `config.yaml` or `config.json` in your project root:

```yaml
# config.yaml
project:
  root: "."
  memory_dir: ".project-memory"
  
database:
  path: ".project-memory/project_knowledge.db"
  echo: false

llm:
  mode: "server_driven"  # or "agent_driven"
  provider: "myself"
  api_key: "not-needed"
  model: "patcher-main"
  api_base: "http://localhost:4000/v1"
  temperature: 0.1

analysis:
  use_vector_similarity: false
  max_analysis_depth: 3

safety:
  require_impact_analysis_before_edit: true
  require_confirmation_before_delete: true
  preserve_comments: true
  preserve_commented_code: true

exclude_patterns:
  - ".git"
  - "node_modules"
  - "__pycache__"
  - ".venv"
  - "venv"
  - "env"
  - "build"
  - "dist"
  - "target"
  - "*.egg-info"
  - ".tox"
  - ".idea"
  - ".vscode"
  - "*.pyc"
  - "*.log"
  - "*.tmp"

languages:
  - "python"
  - "typescript"
  - "javascript"
  - "rust"
  - "go"
  - "java"
  - "c"
  - "cpp"

workflow:
  auto_index: true
  auto_build_graph: true
  auto_generate_manual: true
```

```json
// config.json
{
  "project": {
    "root": ".",
    "memory_dir": ".project-memory"
  },
  "database": {
    "path": ".project-memory/project_knowledge.db",
    "echo": false
  },
  "llm": {
    "mode": "server_driven",
    "provider": "myself",
    "api_key": "not-needed",
    "model": "patcher-main",
    "api_base": "http://localhost:4000/v1",
    "temperature": 0.1
  },
  "analysis": {
    "use_vector_similarity": false,
    "max_analysis_depth": 3
  },
  "safety": {
    "require_impact_analysis_before_edit": true,
    "require_confirmation_before_delete": true,
    "preserve_comments": true,
    "preserve_commented_code": true
  },
  "exclude_patterns": [
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "target",
    "*.egg-info",
    ".tox",
    ".idea",
    ".vscode",
    "*.pyc",
    "*.log",
    "*.tmp"
  ],
  "languages": [
    "python",
    "typescript",
    "javascript",
    "rust",
    "go",
    "java",
    "c",
    "cpp"
  ],
  "workflow": {
    "auto_index": true,
    "auto_build_graph": true,
    "auto_generate_manual": true
  }
}
```

#### Using Configuration Files

```bash
# Initialize with config file
project-memory init . --config config.yaml

# Or use environment variable
export PROJECT_MEMORY_CONFIG=config.yaml
project-memory init .

# Full automated workflow with config
project-memory auto . --config config.yaml
```

### CLI Commands Reference

#### `project-memory init`
Initialize project memory for a project.

```bash
project-memory init [PROJECT_PATH] [OPTIONS]

Options:
  --mode TEXT          LLM mode: agent_driven or server_driven (default: server_driven)
  --no-vector / --vector  Enable/disable vector similarity search (default: disabled)
  --config PATH        Path to configuration file (YAML or JSON)
```

#### `project-memory index`
Run full repository indexing.

```bash
project-memory index [PROJECT_PATH] [OPTIONS]

Options:
  --config PATH        Path to configuration file (YAML or JSON)
```

#### `project-memory rescan`
Rescan only changed files based on hash comparison.

```bash
project-memory rescan [PROJECT_PATH] [OPTIONS]

Options:
  --config PATH        Path to configuration file (YAML or JSON)
```

#### `project-memory auto`
Run fully automated workflow: index → build graph → generate manual.

```bash
project-memory auto [PROJECT_PATH] [OPTIONS]

Options:
  --config PATH        Path to configuration file (YAML or JSON)
  --skip-index         Skip indexing step
  --skip-graph         Skip graph building step
  --skip-manual        Skip manual generation step
```

#### `project-memory query`
Query the knowledge graph.

```bash
project-memory query [COMMAND] [OPTIONS]

Commands:
  file FILE_PATH       Query file information
  symbol SYMBOL_NAME   Query symbol information
  equation KEYWORD     Query equations by keyword

Options:
  --project-path TEXT  Project root directory (default: .)
  --qualified-name TEXT  Qualified name for symbols
  --equation-name TEXT  Specific equation name
```

#### `project-memory impact`
Analyze impact of a proposed change.

```bash
project-memory impact [TARGET_TYPE] [TARGET_NAME] [OPTIONS]

Arguments:
  TARGET_TYPE  Type: file, symbol, equation
  TARGET_NAME  Name of target

Options:
  --operation TEXT     Operation: modify, delete, refactor (default: modify)
  --project-path TEXT  Project root directory (default: .)
```

#### `project-memory manual`
Generate PROJECT_AGENT_MANUAL.md.

```bash
project-memory manual [PROJECT_PATH] [OPTIONS]

Options:
  --config PATH        Path to configuration file (YAML or JSON)
```

#### `project-memory serve`
Run the MCP server.

```bash
project-memory serve [OPTIONS]

Options:
  --http / --stdio    Run HTTP server instead of stdio (default: stdio)
  --host TEXT         Host for HTTP server (default: 127.0.0.1)
  --port INTEGER      Port for HTTP server (default: 8000)
```

### MCP Tools

The server exposes the following MCP tools:

#### Bootstrap & Indexing
- `project.bootstrap` - Initialize project memory
- `project.plan_indexing` - Get indexing plan
- `project.scan_files` - Scan and create file records
- `project.get_next_analysis_task` - Get next LLM analysis task
- `project.submit_file_analysis` - Submit file analysis result
- `project.submit_symbol_analysis` - Submit symbol analysis result
- `project.submit_equation_analysis` - Submit equation analysis result
- `project.build_graph_edges` - Build graph edges from analysis
- `project.rescan_changed_files` - Rescan only changed files
- `project.generate_manual` - Generate PROJECT_AGENT_MANUAL.md

#### Query
- `project.query_file` - Query file details
- `project.query_symbol` - Query symbol details
- `project.query_equation` - Query equations
- `project.query_impact` - Impact analysis
- `project.search_graph` - Search the knowledge graph

#### Edit
- `project.propose_edit` - Propose an edit plan
- `project.apply_edit` - Apply confirmed edit
- `project.delete_candidate` - Analyze delete safety
- `project.confirm_delete` - Confirm and execute deletion

### Configuration

Create a `.env` file or set environment variables:

```env
# LLM Configuration
LLM_MODE=server_driven
LLM_PROVIDER=myself
LLM_API_KEY=not-needed
LLM_MODEL=patcher-main
LLM_API_BASE=http://localhost:4000/v1

# Database
DB_PATH=.project-memory/project_knowledge.db

# Safety
REQUIRE_IMPACT_ANALYSIS_BEFORE_EDIT=true
REQUIRE_CONFIRMATION_BEFORE_DELETE=true
```

Or use the configuration file approach (recommended for automation):
```bash
# Load config from file
project-memory auto . --config config.yaml
```

### Project Structure

```
.project-memory/
├── project_knowledge.db      # SQLite knowledge graph
├── PROJECT_AGENT_MANUAL.md   # Auto-generated manual
├── config.yaml               # Project configuration (optional)
├── operations_history.jsonl  # Operation history
├── unresolved_items.json     # Unresolved references
└── snapshots/                # Periodic snapshots
```

### Automated Workflow Example

```bash
# 1. Create configuration
cat > config.yaml << 'EOF'
project:
  root: "."
  memory_dir: ".project-memory"

llm:
  mode: "server_driven"
  provider: "myself"
  api_key: "not-needed"
  model: "patcher-main"
  api_base: "http://localhost:4000/v1"

workflow:
  auto_index: true
  auto_build_graph: true
  auto_generate_manual: true
EOF

# 2. Run fully automated workflow
project-memory auto . --config config.yaml

# 3. Start the MCP server for agent interaction
project-memory serve
```

### Development

```bash
# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Lint
uv run ruff check

# Type check
uv run pyright

# Run server (stdio)
uv run project-memory-mcp

# Run server (HTTP)
uv run project-memory-mcp --http 127.0.0.1 8000
```

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Agent / MCP Client                    │
└─────────────────────────────┬───────────────────────────────┘
                              │ MCP Protocol
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Project Memory MCP Server                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │   Tools     │  │ Resources   │  │  Prompts    │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Workflow Orchestrator                     │
│  index_repository, rescan_changed_files, impact_analysis,   │
│  propose_edit, apply_edit, delete_safety, generate_manual   │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LLM Analysis Layer                        │
│  File/Symbol/Equation/Variable/Dependency Analysis          │
│  (instructor + Pydantic for structured output)              │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Static Locator Layer                      │
│  tree-sitter (30+ languages) + jedi (Python semantic)       │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Project Knowledge DB                       │
│  SQLite + SQLAlchemy 2.0 + FTS5 + Graph adjacency           │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Target Source Repository                   │
└─────────────────────────────────────────────────────────────┘
```

### License

MIT
