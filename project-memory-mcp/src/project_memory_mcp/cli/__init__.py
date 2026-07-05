"""CLI for Project Memory MCP Server."""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from project_memory_mcp.mcp_tools.query import (
    QueryEquationInput,
    QueryFileInput,
    QuerySymbolInput,
)
from project_memory_mcp.server import run_http, run_stdio
from project_memory_mcp.workflows.delete_safety import analyze_delete_safety
from project_memory_mcp.workflows.generate_manual import generate_manual
from project_memory_mcp.workflows.impact_analysis import query_impact
from project_memory_mcp.workflows.index_repository import index_repository, auto_index_repository
from project_memory_mcp.workflows.rescan_changed_files import rescan_changed_files

app = typer.Typer(
    name="project-memory-mcp",
    help="Project Memory MCP Server - Knowledge graph for code understanding",
    add_completion=False,
)

console = Console()


def _load_config_if_provided(config: Optional[str]) -> dict | None:
    """Load configuration from file if provided."""
    if config:
        from project_memory_mcp.utils.config import load_config
        return load_config(config)
    return None


@app.command()
def init(
    project_path: str = typer.Argument(".", help="Project root directory"),
    mode: str = typer.Option("server_driven", help="LLM mode: agent_driven or server_driven"),
    no_vector: bool = typer.Option(True, help="Disable vector similarity search"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to configuration file (YAML or JSON)"),
):
    """Initialize project memory for a project."""
    console.print(f"[bold blue]Initializing Project Memory in {project_path}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        
        config_dict = _load_config_if_provided(config)
        if config_dict:
            # Merge config file settings with CLI options (CLI takes precedence)
            config_dict.update({
                "llm_mode": mode,
                "use_vector_similarity": not no_vector,
            })
        else:
            config_dict = {
                "llm_mode": mode,
                "use_vector_similarity": not no_vector,
            }
        
        result = await index_repository(project_path, config_dict)
        console.print(f"[green]✓[/green] Files scanned: {result.get('files_scanned', 0)}")
        console.print(f"[green]✓[/green] Files indexed: {result.get('files_indexed', 0)}")
        console.print(f"[green]✓[/green] Symbols extracted: {result.get('symbols_extracted', 0)}")
        console.print(f"[green]✓[/green] Equations found: {result.get('equations_found', 0)}")
        console.print(f"[green]✓[/green] Analysis tasks created: {result.get('analysis_tasks_created', 0)}")
        console.print("\n[bold]Next steps:[/bold]")
        console.print("1. Start the MCP server with 'project-memory-mcp'")
        console.print("2. Call project.start_analysis_loop to use local http://localhost:4000/v1")
        console.print("3. If local LLM is unavailable, ask before using agent-driven analysis")

    asyncio.run(run())


@app.command()
def index(
    project_path: str = typer.Argument(".", help="Project root directory"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to configuration file (YAML or JSON)"),
):
    """Run full repository indexing."""
    console.print(f"[bold blue]Indexing repository: {project_path}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        config_dict = _load_config_if_provided(config)
        result = await index_repository(project_path, config_dict)
        console.print(f"[green]✓[/green] Completed: {result}")

    asyncio.run(run())


@app.command()
def rescan(
    project_path: str = typer.Argument(".", help="Project root directory"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to configuration file (YAML or JSON)"),
):
    """Rescan only changed files."""
    console.print(f"[bold blue]Rescanning changed files in: {project_path}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        config_dict = _load_config_if_provided(config)
        result = await rescan_changed_files(project_path)
        console.print(f"[green]✓[/green] Files checked: {result.get('files_checked', 0)}")
        console.print(f"[green]✓[/green] Files changed: {result.get('files_changed', 0)}")
        console.print(f"[green]✓[/green] Files added: {result.get('files_added', 0)}")
        console.print(f"[green]✓[/green] Files deleted: {result.get('files_deleted', 0)}")

    asyncio.run(run())


@app.command()
def auto(
    project_path: str = typer.Argument(".", help="Project root directory"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to configuration file (YAML or JSON)"),
    skip_index: bool = typer.Option(False, help="Skip indexing step"),
    skip_graph: bool = typer.Option(False, help="Skip graph building step"),
    skip_manual: bool = typer.Option(False, help="Skip manual generation step"),
):
    """Run fully automated workflow: index → build graph → generate manual."""
    console.print(f"[bold blue]Running automated workflow for: {project_path}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        
        if config:
            # Use config file for fully automated execution
            result = await auto_index_repository(config)
        else:
            # Use default workflow with optional step skipping
            config_dict = {
                "workflow_auto_index": not skip_index,
                "workflow_auto_build_graph": not skip_graph,
                "workflow_auto_generate_manual": not skip_manual,
            }
            result = await index_repository(project_path, config_dict)
        console.print(f"[green]✓[/green] Completed: {result}")

    asyncio.run(run())


@app.command()
def query_file(
    file_path: str = typer.Argument(..., help="Path to the file"),
    project_path: str = typer.Option(".", help="Project root directory"),
):
    """Query file information."""
    console.print(f"[bold blue]Querying file: {file_path}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        from project_memory_mcp.mcp_tools.query import project_query_file
        result = await project_query_file(QueryFileInput(
            project_path=project_path,
            file_path=file_path,
        ))

        if not result.found:
            console.print("[red]File not found in knowledge graph[/red]")
            return

        console.print(f"\n[bold]File:[/bold] {result.file_info['path']}")
        console.print(f"[bold]Language:[/bold] {result.file_info['language']}")
        console.print(f"[bold]Purpose:[/bold] {result.file_info['purpose']}")
        console.print(f"[bold]Summary:[/bold] {result.file_info['llm_summary']}")
        console.print(f"[bold]Core:[/bold] {result.file_info['is_core']}")

        if result.symbols:
            console.print(f"\n[bold]Symbols ({len(result.symbols)}):[/bold]")
            table = Table()
            table.add_column("Name")
            table.add_column("Type")
            table.add_column("Lines")
            table.add_column("Responsibility")
            for s in result.symbols:
                table.add_row(
                    s["name"],
                    s["type"],
                    f"{s['start_line']}-{s['end_line']}",
                    s.get("responsibility", "")[:50]
                )
            console.print(table)

        if result.equations:
            console.print(f"\n[bold]Equations ({len(result.equations)}):[/bold]")
            for e in result.equations:
                console.print(f"  • {e['name']} ({e['type']}): {e['expression'][:80]}...")

    asyncio.run(run())


@app.command()
def query_symbol(
    symbol_name: str = typer.Argument(..., help="Symbol name"),
    qualified_name: str | None = typer.Option(None, help="Qualified name"),
    project_path: str = typer.Option(".", help="Project root directory"),
):
    """Query symbol information."""
    console.print(f"[bold blue]Querying symbol: {symbol_name}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        from project_memory_mcp.mcp_tools.query import project_query_symbol
        result = await project_query_symbol(QuerySymbolInput(
            project_path=project_path,
            symbol_name=symbol_name,
            qualified_name=qualified_name,
        ))

        if not result.found:
            console.print("[red]Symbol not found[/red]")
            return

        console.print(f"\n[bold]Symbol:[/bold] {result.symbol_info['name']}")
        console.print(f"[bold]Qualified:[/bold] {result.symbol_info['qualified_name']}")
        console.print(f"[bold]Type:[/bold] {result.symbol_info['type']}")
        console.print(f"[bold]Responsibility:[/bold] {result.symbol_info['responsibility']}")

        if result.callers:
            console.print(f"\n[bold]Callers ({len(result.callers)}):[/bold]")
            for c in result.callers[:10]:
                console.print(f"  • {c['qualified_name']}")

        if result.callees:
            console.print(f"\n[bold]Callees ({len(result.callees)}):[/bold]")
            for c in result.callees[:10]:
                console.print(f"  • {c['qualified_name']}")

    asyncio.run(run())


@app.command()
def query_equation(
    keyword: str = typer.Argument(..., help="Keyword to search in equations"),
    equation_name: str | None = typer.Option(None, help="Specific equation name"),
    project_path: str = typer.Option(".", help="Project root directory"),
):
    """Query equations by keyword."""
    console.print(f"[bold blue]Querying equations with keyword: {keyword}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        from project_memory_mcp.mcp_tools.query import project_query_equation
        result = await project_query_equation(QueryEquationInput(
            project_path=project_path,
            keyword=keyword,
            equation_name=equation_name,
        ))

        if not result.found:
            console.print("[red]No equations found[/red]")
            return

        console.print(f"\n[bold]Found {len(result.equations)} equations:[/bold]")
        for e in result.equations:
            console.print(f"\n  [bold]{e['name']}[/bold] ({e['type']})")
            console.print(f"  Expression: {e['expression'][:100]}...")
            console.print(f"  Meaning: {e['mathematical_meaning'][:100]}...")
            if e['inputs']:
                console.print(f"  Inputs: {e['inputs']}")
            if e['outputs']:
                console.print(f"  Outputs: {e['outputs']}")

    asyncio.run(run())


@app.command()
def impact(
    target_type: str = typer.Argument(..., help="Type: file, symbol, equation"),
    target_name: str = typer.Argument(..., help="Name of target"),
    operation: str = typer.Option("modify", help="Operation: modify, delete, refactor"),
    project_path: str = typer.Option(".", help="Project root directory"),
):
    """Analyze impact of a proposed change."""
    console.print(f"[bold blue]Impact analysis for {target_type}: {target_name}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        result = await query_impact(
            target_type=target_type,
            target_name=target_name,
            target_path=target_name,
            operation_type=operation,
        )

        if not result.get("success"):
            console.print(f"[red]Error: {result.get('error')}[/red]")
            return

        console.print("[green]Impact analysis task created. Next steps:[/green]")
        console.print("1. Agent analyzes and submits result via project.submit_impact_analysis")
        console.print("2. Review the risk assessment")
        console.print("3. Proceed with edit if acceptable")

    asyncio.run(run())


@app.command()
def manual(
    project_path: str = typer.Argument(".", help="Project root directory"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to configuration file (YAML or JSON)"),
):
    """Generate PROJECT_AGENT_MANUAL.md"""
    console.print(f"[bold blue]Generating manual for: {project_path}[/bold blue]")

    async def run():
        from project_memory_mcp.db.connection import init_db
        await init_db()
        config_dict = _load_config_if_provided(config)
        result = await generate_manual(project_path)
        console.print(f"[green]✓[/green] Manual generated with {result.get('sections', 0)} sections")
        console.print(f"[green]✓[/green] Path: {result.get('manual_path', 'N/A')}")

    asyncio.run(run())


@app.command()
def serve(
    http: bool = typer.Option(False, help="Run HTTP server instead of stdio"),
    host: str = typer.Option("127.0.0.1", help="Host for HTTP server"),
    port: int = typer.Option(8000, help="Port for HTTP server"),
):
    """Run the MCP server."""
    if http:
        console.print(f"[bold blue]Starting HTTP server on {host}:{port}[/bold blue]")
        asyncio.run(run_http(host, port))
    else:
        console.print("[bold blue]Starting MCP server (stdio)[/bold blue]")
        asyncio.run(run_stdio())


if __name__ == "__main__":
    app()
