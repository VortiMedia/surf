from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from surf import mcp
from surf.sources import Reading

NOW = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)


def test_tools_map_to_all_existing_cli_surfaces():
    assert {tool["name"] for tool in mcp.tools()} == {
        "sources", "call", "spot", "calibrate", "geometry", "session_add", "exposure"
    }


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("sources", {}, ["sources"]),
        ("call", {"region": "US-NY", "spot": ["lido"], "days": 4, "any_hour": True}, ["call", "--region", "US-NY", "--spot", "lido", "--days", "4", "--any-hour"]),
        ("spot", {"name": "lido", "days": 2}, ["spot", "lido", "--days", "2"]),
        ("calibrate", {"online": True, "refresh": True, "no_matrix": True}, ["calibrate", "--online", "--refresh", "--no-matrix"]),
        ("geometry", {"spot": "lido", "write": True, "refresh": True}, ["geometry", "--spot", "lido", "--write", "--refresh"]),
        ("session_add", {"date": "2026-09-03", "spot": "lido", "rating": 4}, ["session", "add", "--date", "2026-09-03", "--spot", "lido", "--rating", "4"]),
        ("exposure", {"coastline": "coast.json", "swell": 180, "output": "coast.kmz"}, ["exposure", "coast.json", "--swell", "180", "--output", "coast.kmz"]),
    ],
)
def test_tool_arguments_are_only_translated_to_cli_argv(name, arguments, expected):
    assert mcp._argv(name, arguments) == expected


def test_call_tool_keeps_human_output_and_source_receipt():
    def runner(argv, *, console):
        assert argv == ["call", "--days", "2"]
        console.say("CALL  LIDO")
        console.record(Reading(
            {"forecast": "usable"}, "gwam", "degraded", NOW,
            model_run="2026-09-03T06:00Z", confidence=0.4, dropped=("wind",),
        ))
        return 0

    result = mcp.call_tool("call", {"days": 2}, runner=runner)
    assert result["isError"] is False
    assert result["content"][0]["text"] == "CALL  LIDO"
    provenance = result["structuredContent"]["provenance"]
    assert provenance["status"] == "degraded"
    assert provenance["source"] == ["gwam"]
    assert provenance["fetched_at"] == [NOW.isoformat()]
    assert provenance["model_run"] == ["2026-09-03T06:00Z"]
    assert provenance["confidence"] == [0.4]
    assert provenance["dropped"] == ["wind"]


def test_degraded_tool_answer_is_not_a_transport_error():
    def runner(argv, *, console):
        console.record(Reading(None, "ndbc", "failed", NOW, note="offline"))
        return 0

    result = mcp.call_tool("sources", runner=runner)
    assert result["isError"] is False
    assert result["structuredContent"]["provenance"]["status"] == "degraded"


def test_json_rpc_lifecycle_and_tool_call():
    incoming = io.StringIO("\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "sources", "arguments": {}}}),
        "",
    ]))
    outgoing = io.StringIO()

    def runner(argv, *, console):
        console.say("source status")
        return 0

    mcp.serve(incoming, outgoing, runner=runner)
    messages = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert [message["id"] for message in messages] == [1, 2, 3]
    assert messages[0]["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION
    assert len(messages[1]["result"]["tools"]) == 7
    assert messages[2]["result"]["structuredContent"]["provenance"]["status"] == "ok"


def test_unknown_method_and_tool_are_json_rpc_errors():
    unknown_method = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})
    assert unknown_method["error"]["code"] == -32601
    unknown_tool = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope"}})
    assert unknown_tool["error"]["code"] == -32602
