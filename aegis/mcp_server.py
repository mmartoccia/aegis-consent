"""
Aegis MCP Server

Exposes the Aegis consent check as an MCP tool so any MCP-compatible
agent framework can call it natively.

Tool: check_consent(domain, action, confidence) → tier string

Usage (stdio transport):
    python -m aegis.mcp_server

Or via CLI:
    aegis mcp

MCP client config example (Claude Desktop / any MCP host):
    {
      "mcpServers": {
        "aegis": {
          "command": "python",
          "args": ["-m", "aegis.mcp_server"],
          "env": {
            "AEGIS_GRAPH_PATH": "/path/to/consent-graph.json"
          }
        }
      }
    }
"""

import os
import json
from typing import Any

from aegis.consent import check_consent, AegisConfig

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


def _build_config() -> AegisConfig:
    """Build AegisConfig from environment variables (for MCP subprocess context)."""
    kwargs: dict[str, Any] = {}
    if graph_path := os.environ.get("AEGIS_GRAPH_PATH"):
        kwargs["graph_path"] = graph_path
    if log_dir := os.environ.get("AEGIS_LOG_DIR"):
        kwargs["log_dir"] = log_dir
    if threshold := os.environ.get("AEGIS_CONFIDENCE_THRESHOLD"):
        kwargs["confidence_threshold"] = float(threshold)
    return AegisConfig(**kwargs)


def main() -> None:
    """Start the Aegis MCP server on stdio."""
    if not _MCP_AVAILABLE:
        raise ImportError(
            "The 'mcp' package is required to run the MCP server.\n"
            "Install it with: pip install mcp"
        )

    config = _build_config()
    server = Server("aegis-consent")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="check_consent",
                description=(
                    "Check whether an AI agent is permitted to execute an action. "
                    "Returns one of four tiers:\n"
                    "  SILENT  - Execute silently, log only. No notification needed.\n"
                    "  VISIBLE - Execute, then notify the operator what was done and why.\n"
                    "  FORCED  - Do NOT execute yet. Ask the operator for explicit approval first.\n"
                    "  BLOCKED - Absolutely prohibited. Never execute, regardless of confidence.\n\n"
                    "Call this BEFORE every external action. If the result is FORCED or BLOCKED, "
                    "stop and surface the result to the operator. Do not proceed autonomously."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "domain": {
                            "type": "string",
                            "description": (
                                "Logical category of the action. Examples: "
                                "'email', 'calendar', 'filesystem', 'web_search', "
                                "'messaging', 'home_automation', 'database'."
                            ),
                        },
                        "action": {
                            "type": "string",
                            "description": (
                                "The specific action to check. Should match entries in the "
                                "consent graph (e.g. 'send', 'delete', 'read', 'create_event'). "
                                "Use snake_case."
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": (
                                "Agent's confidence (0.0-1.0) that this action matches operator "
                                "intent. High confidence (>= 0.85) resolves 'requires_approval' "
                                "actions as VISIBLE (execute + notify). Low confidence resolves "
                                "them as FORCED (ask first)."
                            ),
                        },
                    },
                    "required": ["domain", "action", "confidence"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name != "check_consent":
            raise ValueError(f"Unknown tool: {name}")

        domain = arguments["domain"]
        action = arguments["action"]
        confidence = float(arguments["confidence"])

        tier = check_consent(domain, action, confidence, config=config)

        result = {
            "tier": tier,
            "domain": domain,
            "action": action,
            "confidence": confidence,
            "guidance": {
                "SILENT": "Proceed. Log the action.",
                "VISIBLE": "Proceed, then notify the operator.",
                "FORCED": "Stop. Request operator approval before executing.",
                "BLOCKED": "Stop. This action is prohibited. Alert the operator.",
            }[tier],
        }

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    import asyncio

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
