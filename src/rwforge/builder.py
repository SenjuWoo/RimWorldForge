"""Build, package and stage a mod without silently destroying user files.

`build` writes only inside the workspace. `stage` copies into RimWorld/Mods, so it
first checks a SHA-256 ownership manifest: files Forge wrote earlier may be
replaced, but an unowned file that would be overwritten or deleted triggers a
full timestamped backup under Mods/.rwforge-backups before the copy.
"""

from __future__ import annotations

import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .util import copytree_clean, ensure_dir, read_json, safe_slug, sha256_file, write_json
from .validator import validate_workspace

MANIFEST_NAME = ".rwforge-manifest.json"


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != MANIFEST_NAME
    }


def _read_manifest(target: Path) -> dict[str, str]:
    path = target / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
    except Exception:
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def _backup_target(target: Path, mods: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = mods / ".rwforge-backups" / f"{target.name}-{stamp}"
    ensure_dir(backup.parent)
    shutil.copytree(target, backup)
    return backup


def build_project(workspace: Path, vanilla_index: Path | None = None) -> dict[str, Any]:
    workspace = workspace.resolve()
    config_path = workspace / "forge.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Not a RimWorldForge workspace: {workspace}")
    validation = validate_workspace(workspace, vanilla_index)
    if not validation["ok"]:
        return {"ok": False, "stage": "validate", "validation": validation}
    config = read_json(config_path)
    name = safe_slug(config.get("name", "RimWorldMod"))
    source = workspace / config.get("source", "source")
    build_root = ensure_dir(workspace / config.get("build", "build"))
    mod_root = build_root / name
    copytree_clean(source, mod_root)
    receipt_files: list[dict[str, Any]] = []
    for path in sorted(p for p in mod_root.rglob("*") if p.is_file()):
        receipt_files.append({
            "path": str(path.relative_to(mod_root)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    zip_path = build_root / f"{name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(p for p in mod_root.rglob("*") if p.is_file()):
            zf.write(path, arcname=f"{name}/{path.relative_to(mod_root).as_posix()}")
    receipt = {
        "schema": 1,
        "built_unix": int(time.time()),
        "workspace": str(workspace),
        "mod_root": str(mod_root),
        "archive": str(zip_path),
        "archive_sha256": sha256_file(zip_path),
        "files": receipt_files,
        "validation": validation,
        "evidence": {
            "syntax_valid": True,
            "references_valid": validation["evidence"]["references_valid"],
            "compiled": None,
            "load_tested": False,
            "runtime_tested": False,
            "visual_tested": False,
        },
    }
    write_json(workspace / "reports" / "build-receipt.json", receipt)
    return {"ok": True, "mod_root": str(mod_root), "archive": str(zip_path), "receipt": str(workspace / "reports" / "build-receipt.json")}


def stage_project(workspace: Path, game_root: Path, approve: bool = False) -> dict[str, Any]:
    if not approve:
        return {"ok": False, "refused": True, "reason": "Staging writes into RimWorld/Mods and requires --approve."}
    workspace = workspace.resolve()
    config = read_json(workspace / "forge.json")
    name = safe_slug(config.get("name", "RimWorldMod"))
    built = workspace / config.get("build", "build") / name
    if not built.is_dir():
        raise FileNotFoundError("No built mod folder. Run `rwforge build` first.")
    mods = game_root / "Mods"
    if not mods.is_dir():
        raise FileNotFoundError(f"RimWorld Mods directory not found: {mods}")
    target = mods / name
    built_hashes = _file_hashes(built)
    target_hashes = _file_hashes(target) if target.is_dir() else {}
    owned = _read_manifest(target)
    unowned_conflicts: list[dict[str, str]] = []
    for relative, digest in built_hashes.items():
        existing = target_hashes.get(relative)
        if existing is None or existing == digest:
            continue
        if owned.get(relative) != existing:
            unowned_conflicts.append({"path": relative, "reason": "unowned file would be overwritten"})
    for relative in target_hashes:
        if relative not in built_hashes and relative not in owned:
            unowned_conflicts.append({"path": relative, "reason": "unowned file would be deleted"})
    backup = _backup_target(target, mods) if (target.is_dir() and unowned_conflicts) else None
    copytree_clean(built, target)
    write_json(target / MANIFEST_NAME, {
        "schema": 1,
        "packageId": config.get("packageId"),
        "workspace": str(workspace),
        "updated_unix": int(time.time()),
        "files": built_hashes,
    })
    return {
        "ok": True,
        "staged": str(target),
        "files": len(built_hashes),
        "backup": str(backup) if backup else None,
        "unowned_conflicts": unowned_conflicts,
        "note": "Game files outside the mod folder were not modified.",
    }


def rollback_stage(workspace: Path, game_root: Path) -> dict[str, Any]:
    """Restore the newest stage backup for this workspace's mod name."""
    config = read_json(workspace.resolve() / "forge.json")
    name = safe_slug(config.get("name", "RimWorldMod"))
    mods = game_root / "Mods"
    backups = sorted((mods / ".rwforge-backups").glob(f"{name}-*")) if (mods / ".rwforge-backups").is_dir() else []
    if not backups:
        raise FileNotFoundError(f"No stage backup found for {name} under {mods / '.rwforge-backups'}")
    backup = backups[-1]
    target = mods / name
    copytree_clean(backup, target)
    return {"ok": True, "restored": str(target), "from": str(backup)}
