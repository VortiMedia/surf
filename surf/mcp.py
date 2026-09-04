"""A small stdio MCP transport for the existing :mod:`surf.cli` commands.

This module deliberately contains no forecast, scoring, or source code.  MCP
clients get the same command output and source receipts as a CLI caller; the
transport only translates JSON-RPC arguments to an argv list.
"""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any, TextIO

from . import cli
from .sources import Reading

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "surf", "version": "0.1.0"}


def _property(kind: str, description: str) -> dict[str, Any]:
    return {"type": kind, "description": description}


_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "sources",
        "description": "Preflight forecast, observation, tide, and bathymetry sources.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "call",
        "description": "Choose one spot and surf window using the existing surf call command.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": _property("string", "Region prefix such as US-NY."),
                "spot": {"type": "array", "items": {"type": "string"}, "description": "Spot names or ids."},
                "days": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                "any_hour": _property("boolean", "Include dark hours in scoring."),
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "spot",
        "description": "Inspect one spot, its geometry, source receipts, and best hour.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": _property("string", "Spot name, id, or alias."), "days": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calibrate",
        "description": "Check the model against the session log.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "online": _property("boolean", "Opt in to filling the archive cache."),
                "refresh": _property("boolean", "Ignore cached conditions."),
                "no_matrix": _property("boolean", "Score without the response matrix."),
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "geometry",
        "description": "Derive per-spot beach slopes from bathymetry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spot": _property("string", "One spot id or name; omit for all."),
                "write": _property("boolean", "Persist derived slopes to the spot database."),
                "refresh": _property("boolean", "Ignore the geometry cache."),
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "session_add",
        "description": "Append one observed session to the session log.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": _property("string", "YYYY-MM-DD, YYYY-MM-DD?, or ????-MM-DD."),
                "spot": _property("string", "The spot name as recorded."),
                "time": _property("string", "HH:MM or a word such as early."),
                "rating": {"type": "integer", "minimum": 1, "maximum": 5},
                "notes": _property("string", "What it was actually like."),
                "path": _property("string", "Optional session file path."),
            },
            "required": ["date", "spot"],
            "additionalProperties": False,
        },
    },
    {
        "name": "exposure",
        "description": "Write a swell-exposure KMZ using the existing exposure command.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "coastline": _property("string", "Coastline GeoJSON path."),
                "swell": {"type": "number", "description": "Swell direction from, degrees true."},
                "output": _property("string", "Optional output KMZ path."),
                "land": _property("string", "Optional land-mask GeoJSON path."),
            },
            "required": ["coastline", "swell"],
            "additionalProperties": False,
        },
    },
)
_TOOL_NAMES = frozenset(tool["name"] for tool in _TOOLS)


def tools() -> tuple[dict[str, Any], ...]:
    """Return MCP tool descriptions as immutable-ish copies for callers."""
    return tuple(dict(tool) for tool in _TOOLS)


def _flag(argv: list[str], option: str, value: Any) -> None:
    if value:
        argv.append(option)


def _argv(name: str, arguments: Mapping[str, Any]) -> list[str]:
    """Translate validated MCP arguments to the corresponding CLI argv."""
    args = dict(arguments)
    if name == "sources":
        return ["sources"]
    if name == "call":
        out = ["call"]
        if args.get("region") is not None:
            out += ["--region", str(args["region"])]
        for spot in args.get("spot", ()):
            out += ["--spot", str(spot)]
        if args.get("days") is not None:
            out += ["--days", str(args["days"])]
        _flag(out, "--any-hour", args.get("any_hour"))
        return out
    if name == "spot":
        out = ["spot", str(args["name"])]
        if args.get("days") is not None:
            out += ["--days", str(args["days"])]
        return out
    if name == "calibrate":
        out = ["calibrate"]
        _flag(out, "--online", args.get("online"))
        _flag(out, "--refresh", args.get("refresh"))
        _flag(out, "--no-matrix", args.get("no_matrix"))
        return out
    if name == "geometry":
        out = ["geometry"]
        if args.get("spot"):
            out += ["--spot", str(args["spot"])]
        _flag(out, "--write", args.get("write"))
        _flag(out, "--refresh", args.get("refresh"))
        return out
    if name == "session_add":
        out = ["session", "add", "--date", str(args["date"]), "--spot", str(args["spot"])]
        for key, option in (("time", "--time"), ("rating", "--rating"), ("notes", "--notes"), ("path", "--path")):
            if args.get(key) is not None:
                out += [option, str(args[key])]
        return out
    if name == "exposure":
        out = ["exposure", str(args["coastline"]), "--swell", str(args["swell"])]
        for key, option in (("output", "--output"), ("land", "--land")):
            if args.get(key) is not None:
                out += [option, str(args[key])]
        return out
    raise KeyError(name)


def _record(reading: Reading[Any]) -> dict[str, Any]:
    return {
        "source": reading.source,
        "status": reading.status,
        "fetched_at": reading.fetched_at.isoformat(),
        "model_run": reading.model_run,
        "confidence": reading.confidence,
        "dropped": list(reading.dropped),
        **({"note": reading.note} if reading.note else {}),
    }


def _provenance(readings: Iterable[Reading[Any]], code: int) -> dict[str, Any]:
    records = tuple(_record(reading) for reading in readings)
    statuses = [record["status"] for record in records]
    if code != cli.EXIT_OK:
        status = "skipped" if statuses and all(item == "skipped" for item in statuses) else "failed"
    elif any(item in ("failed", "skipped") for item in statuses) or any(record["dropped"] for record in records):
        status = "degraded"
    else:
        status = "ok"
    return {
        "source": [record["source"] for record in records],
        "status": status,
        "fetched_at": [record["fetched_at"] for record in records],
        "model_run": [record["model_run"] for record in records if record["model_run"] is not None],
        "confidence": [record["confidence"] for record in records if record["confidence"] is not None],
        "dropped": [drop for record in records for drop in record["dropped"]],
        "readings": list(records),
    }


def call_tool(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    runner: Callable[..., int] = cli.main,
) -> dict[str, Any]:
    """Run one existing CLI command and return an MCP tool result."""
    if name not in _TOOL_NAMES:
        raise KeyError(f"unknown tool {name!r}")
    args = arguments or {}
    out, err = io.StringIO(), io.StringIO()
    console = cli.Console(out=out, err=err)
    try:
        code = int(runner(_argv(name, args), console=console))
    except SystemExit as exc:  # argparse errors become tool errors, not server death
        code = int(exc.code) if isinstance(exc.code, int) else cli.EXIT_USAGE
        print(f"surf {name}: invalid arguments", file=err)
    except Exception as exc:  # transport errors become tool errors, not server death
        code = cli.EXIT_FAILED
        print(f"surf {name}: {type(exc).__name__}: {exc}", file=err)
    text = out.getvalue()
    error_text = err.getvalue()
    content_text = text + (f"\n{error_text}" if error_text else "")
    return {
        "content": [{"type": "text", "text": content_text.rstrip()}],
        "isError": code != cli.EXIT_OK,
        "structuredContent": {
            "command": name,
            "exit_code": code,
            "stdout": text,
            "stderr": error_text,
            "provenance": _provenance(console.readings, code),
        },
    }


def _response(request_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    return response


def handle(request: Mapping[str, Any], *, runner: Callable[..., int] = cli.main) -> dict[str, Any] | None:
    """Handle one JSON-RPC request. Notifications intentionally have no reply."""
    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        if method == "notifications/initialized":
            return None
        return None
    if method == "initialize":
        return _response(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {"tools": list(tools())})
    if method == "tools/call":
        params = request.get("params")
        if not isinstance(params, Mapping) or not isinstance(params.get("name"), str):
            return _response(request_id, error={"code": -32602, "message": "tools/call requires params.name"})
        arguments = params.get("arguments", {})
        if not isinstance(arguments, Mapping):
            return _response(request_id, error={"code": -32602, "message": "params.arguments must be an object"})
        try:
            return _response(request_id, call_tool(params["name"], arguments, runner=runner))
        except KeyError as exc:
            return _response(request_id, error={"code": -32602, "message": str(exc)})
    return _response(request_id, error={"code": -32601, "message": f"method not found: {method}"})


def serve(
    incoming: TextIO = sys.stdin,
    outgoing: TextIO = sys.stdout,
    *,
    runner: Callable[..., int] = cli.main,
) -> None:
    """Serve newline-delimited JSON-RPC over stdio, as MCP clients expect."""
    for line in incoming:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, Mapping):
                raise ValueError("request must be a JSON object")
            response = handle(request, runner=runner)
        except (ValueError, json.JSONDecodeError) as exc:
            response = _response(None, error={"code": -32700, "message": str(exc)})
        if response is not None:
            outgoing.write(json.dumps(response, separators=(",", ":")) + "\n")
            outgoing.flush()


def main() -> int:
    serve()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
