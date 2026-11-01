from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rwforge import __version__
from rwforge.builder import build_project
from rwforge.cli import capabilities
from rwforge.discovery import discover_game, doctor
from rwforge.generator import apply_plan, validate_plan
from rwforge.indexer import build_index, inspect_def, search_index
from rwforge.logs import analyze_log
from rwforge.project import new_project
from rwforge.util import read_json
from rwforge.validator import validate_workspace


def schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    out = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


TOOLS = [
    {"name": "rw_doctor", "description": "Detect RimWorld 1.6/1.7, DLCs, Managed assemblies, Mods folder, Player.log and harmony.log.txt.", "inputSchema": schema({"game": {"type": "string"}})},
    {"name": "rw_capabilities", "description": "Return honest implemented/unsupported capability matrix and evidence tiers.", "inputSchema": schema({})},
    {"name": "rw_index", "description": "Build a searchable Def index from Core + installed DLC, honoring 1.6/1.7 version folders and LoadFolders.xml. By default auto-discovers mods: game Mods folder plus every Steam library Workshop root.", "inputSchema": schema({"game": {"type": "string"}, "mods_root": {"type": "string"}, "output": {"type": "string"}, "version": {"type": "string", "enum": ["1.6", "1.7"]}})},
    {"name": "rw_def_search", "description": "Search the indexed vanilla/DLC Def corpus before inventing XML.", "inputSchema": schema({"query": {"type": "string"}, "def_type": {"type": "string"}, "index": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["query"])},
    {"name": "rw_def_inspect", "description": "Inspect one indexed Def and return its source plus raw XML when available.", "inputSchema": schema({"def_name": {"type": "string"}, "index": {"type": "string"}}, ["def_name"])},
    {"name": "rw_project_new", "description": "Create a transactional RimWorld mod workspace outside the live game.", "inputSchema": schema({"name": {"type": "string"}, "package_id": {"type": "string"}, "author": {"type": "string"}, "description": {"type": "string"}, "workspace": {"type": "string"}}, ["name", "package_id"])},
    {"name": "rw_plan_validate", "description": "Validate a typed RimWorldForge generation plan without writing files.", "inputSchema": schema({"plan": {"type": "string"}}, ["plan"])},
    {"name": "rw_generate", "description": "Apply a validated generation plan to a Forge workspace: About.xml, Def XML, LoadFolders, asset manifest.", "inputSchema": schema({"workspace": {"type": "string"}, "plan": {"type": "string"}}, ["workspace", "plan"])},
    {"name": "rw_validate", "description": "Static-validate About.xml, Def/Patch XML, duplicate names, texture paths and conservative reference candidates.", "inputSchema": schema({"workspace": {"type": "string"}, "index": {"type": "string"}}, ["workspace"])},
    {"name": "rw_build", "description": "Build a clean mod folder + deterministic ZIP + SHA-256 receipt after validation.", "inputSchema": schema({"workspace": {"type": "string"}, "index": {"type": "string"}}, ["workspace"])},
    {"name": "rw_log_analyze", "description": "Analyze Player.log plus harmony.log.txt for XML inheritance, XPath, Harmony, texture and exception failures; optional PII redaction.", "inputSchema": schema({"log": {"type": "string"}, "context": {"type": "integer"}, "max_hits": {"type": "integer"}, "harmony_log": {"type": "string"}, "redact": {"type": "boolean"}}, ["log"])},
    {"name": "rw_assets_generate", "description": "Generate the workspace's declared textures locally with deterministic procedural art (free, no network). Inspect the PNGs afterwards.", "inputSchema": schema({"workspace": {"type": "string"}, "force": {"type": "boolean"}, "seed": {"type": "string"}}, ["workspace"])},
]


def call_tool(name: str, a: dict[str, Any]) -> dict[str, Any]:
    if name == "rw_doctor":
        return doctor(a.get("game"))
    if name == "rw_capabilities":
        return capabilities()
    if name == "rw_index":
        root = discover_game(a.get("game"))
        if not root:
            raise FileNotFoundError("RimWorld installation not found")
        return build_index(root, Path(a["mods_root"]) if a.get("mods_root") else None, Path(a["output"]) if a.get("output") else None, active_version=a.get("version"))
    if name == "rw_def_search":
        return {"ok": True, "results": search_index(a["query"], a.get("def_type"), Path(a["index"]) if a.get("index") else None, int(a.get("limit", 20)))}
    if name == "rw_def_inspect":
        found = inspect_def(a["def_name"], Path(a["index"]) if a.get("index") else None)
        return {"ok": bool(found), "def": found}
    if name == "rw_project_new":
        return new_project(a["name"], a["package_id"], a.get("author", ""), a.get("description", "Generated with RimWorldForge."), Path(a["workspace"]) if a.get("workspace") else None)
    if name == "rw_plan_validate":
        return validate_plan(read_json(Path(a["plan"])))
    if name == "rw_generate":
        return apply_plan(Path(a["workspace"]), Path(a["plan"]))
    if name == "rw_validate":
        return validate_workspace(Path(a["workspace"]), Path(a["index"]) if a.get("index") else None)
    if name == "rw_build":
        return build_project(Path(a["workspace"]), Path(a["index"]) if a.get("index") else None)
    if name == "rw_log_analyze":
        return analyze_log(
            Path(a["log"]), int(a.get("context", 1)), int(a.get("max_hits", 200)),
            harmony_log=Path(a["harmony_log"]) if a.get("harmony_log") else None,
            redact=bool(a.get("redact", False)),
        )
    if name == "rw_assets_generate":
        from rwforge.artgen import generate_assets
        return generate_assets(Path(a["workspace"]), force=bool(a.get("force", False)), seed=a.get("seed"))
    raise KeyError(name)


def response(req_id: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    out = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        protocol = params.get("protocolVersion") or "2025-06-18"
        return response(req_id, {"protocolVersion": protocol, "capabilities": {"tools": {}}, "serverInfo": {"name": "rimworldforge", "version": __version__}})
    if method == "ping":
        return response(req_id, {})
    if method == "tools/list":
        return response(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            data = call_tool(name, arguments)
            text = json.dumps(data, ensure_ascii=False, indent=2)
            return response(req_id, {"content": [{"type": "text", "text": text}], "isError": not data.get("ok", True)})
        except Exception as exc:
            text = json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
            return response(req_id, {"content": [{"type": "text", "text": text}], "isError": True})
    if req_id is not None:
        return response(req_id, error={"code": -32601, "message": f"Method not found: {method}"})
    return None


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
            out = handle(msg)
            if out is not None:
                print(json.dumps(out, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps(response(None, error={"code": -32603, "message": str(exc)})), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
