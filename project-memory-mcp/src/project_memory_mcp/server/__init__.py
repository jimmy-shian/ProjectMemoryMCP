"""MCP Server setup and configuration for Project Memory MCP."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from project_memory_mcp.db.connection import close_db, init_db
from project_memory_mcp.mcp_tools.edit import register_edit_tools
from project_memory_mcp.mcp_tools.manual import register_manual_tools
from project_memory_mcp.mcp_tools.memory import register_memory_tools
from project_memory_mcp.mcp_tools.query import register_query_tools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Application lifespan handler."""
    logger.info("Starting Project Memory MCP Server...")
    await init_db()
    logger.info("Database initialized")
    yield
    await close_db()
    logger.info("Project Memory MCP Server shutdown complete")


async def create_server() -> FastMCP:
    """Create and configure the MCP server using FastMCP.

    FastMCP provides the ``@server.tool()`` decorator that the register_*
    helpers rely on. The low-level ``mcp.server.Server`` has no such
    decorator, so using it left every tool unregistered. Async because the
    register_* helpers are coroutines and must be awaited.
    """
    server = FastMCP(
        "project-memory-mcp",
        lifespan=lifespan,
    )

    # Register tools
    await register_memory_tools(server)
    await register_query_tools(server)
    await register_edit_tools(server)
    await register_manual_tools(server)

    return server


async def run_stdio() -> None:
    """Run the server over stdio transport."""
    server = await create_server()
    await server.run_stdio_async()


async def run_http(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the server over Streamable HTTP transport."""
    server = await create_server()
    await server.run_streamable_http_async(host=host, port=port)


def main() -> None:
    """Console-script entry point for ``project-memory-mcp``.

    Honors an ``--http [host] [port]`` argument sequence; defaults to stdio.
    """
    import asyncio
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if len(sys.argv) > 1 and sys.argv[1] == "--http":
        host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 8000
        asyncio.run(run_http(host, port))
    else:
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
