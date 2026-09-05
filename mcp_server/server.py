"""Entrypoint: wires up the FastMCP server and registers every tool
module. Run directly (`python -m mcp_server.server`) or via the Docker
image built from docker/Dockerfile.mcp.

Transport is env-driven (see config.py):
  - MCP_TRANSPORT=stdio            -> for Claude Desktop's local config
                                       (claude_config/mcp_config.json)
  - MCP_TRANSPORT=streamable-http  -> for headless VPS deployment, so an
                                       Agent SDK client (or Claude Desktop's
                                       remote MCP support) can connect over
                                       HTTP to this container.
"""

from mcp.server.fastmcp import FastMCP

from .config import settings
from .tools import broker_kite, market_data, risk, sentiment

mcp = FastMCP("algo-trading-bot", host=settings.MCP_HOST, port=settings.MCP_PORT)

broker_kite.register(mcp)
market_data.register(mcp)
risk.register(mcp)
sentiment.register(mcp)


def main() -> None:
    mcp.run(transport=settings.MCP_TRANSPORT)


if __name__ == "__main__":
    main()
