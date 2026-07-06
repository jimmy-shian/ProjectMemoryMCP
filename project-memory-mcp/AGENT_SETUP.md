# Agent Setup

This project exposes a stdio MCP server named `project-memory-mcp`.

## Recommended Install Commands

From this repository:

```bash
cd project-memory-mcp
pip install -e .
```

With uv:

```bash
cd project-memory-mcp
uv sync
uv run project-memory-mcp
```

With npm/npx after publishing the npm package:

```bash
npm install -g project-memory-mcp
project-memory-mcp
```

or:

```bash
npx project-memory-mcp
```

The npm wrapper starts the Python MCP server. On first run it installs the
Python package dependencies with pip, then runs `project_memory_mcp.server`.

## MCP Client Snippets

Use the command that matches your install method.

### Local Editable Checkout

```json
{
  "mcpServers": {
    "project-memory": {
      "command": "python",
      "args": [
        "-c",
        "from project_memory_mcp.server import main; main()"
      ],
      "cwd": "/absolute/path/to/PMCPS/project-memory-mcp"
    }
  }
}
```

### Installed Python Package

```json
{
  "mcpServers": {
    "project-memory": {
      "command": "project-memory-mcp",
      "args": []
    }
  }
}
```

### npm / npx

```json
{
  "mcpServers": {
    "project-memory": {
      "command": "npx",
      "args": ["-y", "project-memory-mcp"]
    }
  }
}
```

### Codex TOML Style

```toml
[mcp_servers.project-memory]
command = "project-memory-mcp"
args = []
```

## Default LLM Description Policy

The default description analysis path is:

1. Try local server-driven analysis at `http://localhost:4000/v1` with model
   `patcher-main`.
2. If the local endpoint is unavailable, the MCP tool returns `started=false`
   plus fallback instructions. The calling agent should ask the user whether it
   may run agent-driven analysis itself.
3. If the user does not allow agent-driven analysis, keep using the static map
   only. The system still records files, symbols, imports, calls, hashes, and
   static graph edges; LLM summaries remain pending.

The relevant MCP calls are:

```text
project.bootstrap(project_path=".")
project.start_analysis_loop(project_path=".")
project.get_analysis_progress(project_path=".")
```

### Knowledge-base guide & stale-file detection

On `project.bootstrap` / index, the server writes an agent-agnostic usage
guide to `.project-memory/AGENT_GUIDE.md`. Any AI agent that opens the project
should read it first; it explains the available tools and conventions in a
vendor-neutral way.

The server also maintains a `.project-memory/change_log.json` snapshot of
indexed file hashes. On **every** query-tool call it compares the working
tree to the snapshot and attaches a `staleness_warning` field to the result
when files have changed / been added / been deleted. Agents should re-run
analysis when warned:

```text
project.check_staleness(project_path=".")
project.rescan_changed_files(project_path=".")
project.start_analysis_loop(project_path=".")
```

If local analysis is unavailable and the user permits agent-driven analysis:

```text
project.get_next_analysis_task(project_path=".", task_type="file")
project.submit_file_analysis(...)
project.get_next_analysis_task(project_path=".", task_type="symbol")
project.submit_symbol_analysis(...)
project.get_next_analysis_task(project_path=".", task_type="equation")
project.submit_equation_analysis(...)
```
