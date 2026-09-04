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
        "sources", "call", "spot", "climate", "lexicon", "terrain", "imagery",
        "wave_state", "calibrate", "geometry", "session_add", "session_audit",
        "snapshot_issue", "snapshot_verify", "watch_save", "watch_run", "exposure",
    }


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("sources", {}, ["sources"]),
        ("call", {"region": "US-NY", "spot": ["lido"], "days": 4, "any_hour": True}, ["call", "--region", "US-NY", "--spot", "lido", "--days", "4", "--any-hour"]),
        ("spot", {"name": "lido", "days": 2}, ["spot", "lido", "--days", "2"]),
        ("climate", {"zone": "US-NY", "start": "2024-01-01", "end": "2024-01-31", "refresh": True}, ["climate", "--zone", "US-NY", "--start", "2024-01-01", "--end", "2024-01-31", "--refresh"]),
        ("lexicon", {"phrase": "grovel"}, ["lexicon", "grovel"]),
        ("terrain", {"zone": "z", "bbox": "1,2,3,4", "step": 0.1}, ["terrain", "--zone", "z", "--bbox", "1,2,3,4", "--step", "0.1"]),
        ("imagery", {"zone": "z", "bbox": "1,2,3,4", "frames": "static.json"}, ["imagery", "--zone", "z", "--bbox", "1,2,3,4", "--frames", "static.json"]),
        ("wave_state", {"zone": "z", "bbox": "1,2,3,4", "frames": "waves.json"}, ["wave-state", "--zone", "z", "--bbox", "1,2,3,4", "--frames", "waves.json"]),
        ("calibrate", {"online": True, "refresh": True, "no_matrix": True, "path": "sessions.tsv"}, ["calibrate", "--online", "--refresh", "--no-matrix", "--path", "sessions.tsv"]),
        ("geometry", {"spot": "lido", "write": True, "refresh": True}, ["geometry", "--spot", "lido", "--write", "--refresh"]),
        ("session_add", {"date": "2026-09-03", "spot": "lido", "rating": 4, "regime": "ground"}, ["session", "add", "--date", "2026-09-03", "--spot", "lido", "--rating", "4", "--regime", "ground"]),
        ("session_audit", {"path": "sessions.tsv", "years": "2023,2024", "online": True, "dry_run": True}, ["session", "audit", "--path", "sessions.tsv", "--years", "2023,2024", "--online", "--dry-run"]),
        ("snapshot_issue", {"path": "snapshots.jsonl", "spot": "lido", "valid_at": "2026-09-04T12:00Z", "model_run": "run", "height_quantity": "nearshore_hs"}, ["snapshot", "issue", "--path", "snapshots.jsonl", "--spot", "lido", "--valid-at", "2026-09-04T12:00Z", "--model-run", "run", "--height-quantity", "nearshore_hs"]),
        ("snapshot_verify", {"path": "snapshots.jsonl", "observations": "buoy.jsonl", "sessions": "sessions.tsv"}, ["snapshot", "verify", "--path", "snapshots.jsonl", "--observations", "buoy.jsonl", "--sessions", "sessions.tsv"]),
        ("watch_save", {"path": "setup.json", "name": "reef", "spot": ["one", "two"], "conditions": "conditions.json"}, ["watch", "save", "--path", "setup.json", "--name", "reef", "--spot", "one", "--spot", "two", "--conditions", "conditions.json"]),
        ("watch_run", {"path": "setup.json", "model_run": "run-1", "snapshots": "snapshots.jsonl"}, ["watch", "run", "--path", "setup.json", "--model-run", "run-1", "--snapshots", "snapshots.jsonl"]),
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


def test_degraded_receipt_without_dropped_fields_stays_degraded():
    def runner(argv, *, console):
        console.record(Reading(True, "forecast", "degraded", NOW))
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
    assert len(messages[1]["result"]["tools"]) == 17
    assert messages[2]["result"]["structuredContent"]["provenance"]["status"] == "ok"


def test_unknown_method_and_tool_are_json_rpc_errors():
    unknown_method = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})
    assert unknown_method["error"]["code"] == -32601
    unknown_tool = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope"}})
    assert unknown_tool["error"]["code"] == -32602
