"""MCP Server entry point for Project Memory MCP."""

from project_memory_mcp.server import run_http, run_stdio


async def main():
    """Main entry point for the MCP server."""
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--http":
        host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 8000
        await run_http(host, port)
    else:
        await run_stdio()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
