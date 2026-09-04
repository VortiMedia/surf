"""Remote Streamable HTTP transport for the read-only Surf MCP tools."""

from __future__ import annotations

import os
from typing import Any

import anyio
import uvicorn
from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from . import mcp

READ_ONLY_TOOLS = frozenset({"sources", "call", "spot", "lexicon"})


def remote_tools() -> tuple[dict[str, Any], ...]:
    """Expose the bounded surface safe for an Internet-facing first deploy."""
    return tuple(tool for tool in mcp.tools() if tool["name"] in READ_ONLY_TOOLS)


async def call_remote_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    if name not in READ_ONLY_TOOLS:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"tool not available remotely: {name}")],
            isError=True,
        )
    result = await anyio.to_thread.run_sync(lambda: mcp.call_tool(name, arguments))
    return types.CallToolResult.model_validate(result)


class StreamableHttpApp:
    def __init__(self, session_manager: StreamableHTTPSessionManager):
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


def create_app() -> Starlette:
    server = Server(mcp.SERVER_INFO["name"], version=mcp.SERVER_INFO["version"])

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool.model_validate(tool) for tool in remote_tools()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return await call_remote_tool(name, arguments)

    manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=True,
        stateless=True,
    )
    transport = StreamableHttpApp(manager)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": mcp.SERVER_INFO["name"]})

    return Starlette(
        routes=[Route("/health", health), Route("/mcp", endpoint=transport)],
        lifespan=lambda _: manager.run(),
    )


def main() -> int:
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
