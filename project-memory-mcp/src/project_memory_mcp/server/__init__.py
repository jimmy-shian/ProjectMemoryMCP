"""MCP Server setup and configuration for Project Memory MCP."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import PromptsCapability, ResourcesCapability, ServerCapabilities, ToolsCapability

from project_memory_mcp.db.connection import close_db, init_db
from project_memory_mcp.mcp_tools.edit import register_edit_tools
from project_memory_mcp.mcp_tools.manual import register_manual_tools
from project_memory_mcp.mcp_tools.memory import register_memory_tools
from project_memory_mcp.mcp_tools.query import register_query_tools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: Server) -> AsyncIterator[None]:
    """Application lifespan handler."""
    logger.info("Starting Project Memory MCP Server...")
    await init_db()
    logger.info("Database initialized")
    yield
    await close_db()
    logger.info("Project Memory MCP Server shutdown complete")


def create_server() -> Server:
    """Create and configure the MCP server."""
    server = Server(
        "project-memory-mcp",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register tools
    register_memory_tools(server)
    register_query_tools(server)
    register_edit_tools(server)
    register_manual_tools(server)

    # Register resources - commented out as not implemented yet
    # register_memory_resources(server)
    # register_project_resources(server)

    # Register prompts - commented out as not implemented yet
    # register_code_review_prompts(server)
    # register_debug_session_prompts(server)

    return server


async def run_stdio() -> None:
    """Run the server over stdio transport."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="project-memory-mcp",
                server_version="0.1.0",
                capabilities=ServerCapabilities(
                    tools=ToolsCapability(list_changed=True),
                    resources=ResourcesCapability(subscribe=True, list_changed=True),
                    prompts=PromptsCapability(list_changed=True),
                ),
            ),
        )


async def run_http(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the server over Streamable HTTP transport."""
    import uvicorn
    from mcp.server.streamable_http import create_streamable_http_server

    server = create_server()
    app = create_streamable_http_server(server)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


if __name__ == "__main__":
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
