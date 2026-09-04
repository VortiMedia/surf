from __future__ import annotations

import asyncio

from mcp import types
from starlette.testclient import TestClient

from surf import mcp_http


def test_remote_surface_is_read_only_and_decision_focused():
    assert {tool["name"] for tool in mcp_http.remote_tools()} == {
        "sources", "call", "spot", "lexicon",
    }


def test_remote_tool_schemas_are_valid_mcp_tools():
    assert all(types.Tool.model_validate(tool) for tool in mcp_http.remote_tools())


def test_remote_app_has_health_and_mcp_routes():
    app = mcp_http.create_app()
    assert {route.path for route in app.routes} == {"/health", "/mcp"}
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "server": "surf"}


def test_remote_server_rejects_write_tool():
    result = asyncio.run(mcp_http.call_remote_tool("session_add", {}))
    assert result.isError is True
    assert result.content[0].text == "tool not available remotely: session_add"
