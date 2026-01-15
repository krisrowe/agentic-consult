"""Stdio transport for MCP server."""
from .server import mcp


def run_server():
    """Run the MCP server with stdio transport."""
    mcp.run()


if __name__ == "__main__":
    run_server()
