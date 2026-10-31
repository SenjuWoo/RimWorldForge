from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from .discovery import DLC_DIRS, game_version_short
from .util import ensure_dir, state_root, write_json
from .versions import (
    SUPPORTED_VERSIONS,
    active_package_ids,
    default_version_dir,
    relative_file_collisions,
    resolve_load_folders,
)

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class DefRecord:
    def_type: str
    def_name: str | None
    label: str | None
    parent_name: str | None
    source_pack: str
    source_file: str
    xml_tag_count: int
    abstract: bool = False
    may_require: str | None = None


def _iter_xml_files(root: Path) -> Iterable[Path]:
    if root.is_dir():
        yield from sorted(root.rglob("*.xml"))


def _read_defs(path: Path, source_pack: str) -> tuple[list[DefRecord], list[dict]]:
    records: list[DefRecord] = []
    errors: list[dict] = []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        if root.tag != "Defs":
            return records, errors
        for child in root:
            def_name = child.findtext("defName")
            label = child.findtext("label")
            records.append(
                DefRecord(
                    def_type=child.tag,
                    def_name=def_name.strip() if def_name else None,
                    label=label.strip() if label else None,
                    parent_name=child.attrib.get("ParentName"),
                    source_pack=source_pack,
                    source_file=str(path),
                    xml_tag_count=sum(1 for _ in child.iter()),
                    abstract=(child.attrib.get("Abstract", "").lower() == "true"),
                    may_require=child.attrib.get("MayRequire") or child.attrib.get("MayRequireAnyOf"),
                )
            )
    except (ET.ParseError, OSError) as exc:
        errors.append({"file": str(path), "error": str(exc)})
    return records, errors


def _defs_dir(folder: Path) -> Path | None:
    candidate = folder / "Defs"
    if candidate.is_dir():
        return candidate
    # A LoadFolders entry may point directly at a Defs folder.
    return folder if folder.name.lower() == "defs" and folder.is_dir() else None


def _mod_def_dirs(
    mod_dir: Path,
    active_version: str | None,
    active_ids: set[str] | None,
) -> tuple[list[Path], list[dict]]:
    """Def directories a mod actually loads, plus warnings about ambiguity.

    LoadFolders.xml supersedes the default version-folder rule. Without it the
    game loads root, Common and the highest version folder not newer than the
    running game (1.7 will happily load a 1.6 folder).
    """
    warnings: list[dict] = []
    folders, load_warnings = resolve_load_folders(mod_dir, active_version, active_ids)
    warnings.extend(load_warnings)
    if folders is not None:
        dirs = [d for d in (_defs_dir(folder) for folder in folders) if d]
        return dirs, warnings

    dirs: list[Path] = []
    flat = mod_dir / "Defs"
    if flat.is_dir():
        dirs.append(flat)
    common = mod_dir / "Common" / "Defs"
    if common.is_dir():
        dirs.append(common)
    if active_version is None:
        # No detected game version: index every supported version folder rather
        # than guessing which one the user runs.
        for version in SUPPORTED_VERSIONS:
            candidate = mod_dir / version / "Defs"
            if candidate.is_dir():
                dirs.append(candidate)
    else:
        chosen = default_version_dir(mod_dir, active_version)
        if chosen is not None:
            candidate = chosen / "Defs"
            if candidate.is_dir():
                dirs.append(candidate)
    return dirs, warnings


def build_index(
    game_root: Path,
    include_mods: list[Path] | Path | None = None,
    output: Path | None = None,
    active_version: str | None = None,
) -> dict:
    version = active_version or game_version_short(game_root)
    ids = active_package_ids()
    records: list[DefRecord] = []
    errors: list[dict] = []
    warnings: list[dict] = []
    data = game_root / "Data"
    for pack in DLC_DIRS:
        defs_dir = data / pack / "Defs"
        for path in _iter_xml_files(defs_dir):
            found, bad = _read_defs(path, pack)
            records.extend(found)
            errors.extend(bad)
    if include_mods is None:
        from .mods import mod_roots
        mod_dirs = [root for origin, root in mod_roots(game_root)]
    elif isinstance(include_mods, Path):
        mod_dirs = [include_mods]
    else:
        mod_dirs = list(include_mods)
    for mods_dir in mod_dirs:
        if not mods_dir.is_dir():
            continue
        for mod in sorted(p for p in mods_dir.iterdir() if p.is_dir()):
            dirs, mod_warnings = _mod_def_dirs(mod, version, ids)
            warnings.extend({"mod": mod.name, **warning} for warning in mod_warnings)
            for collision in relative_file_collisions(dirs):
                warnings.append({"mod": mod.name, "severity": "warning", **collision})
            for defs_dir in dirs:
                for path in _iter_xml_files(defs_dir):
                    found, bad = _read_defs(path, f"mod:{mod.name}")
                    records.extend(found)
                    errors.extend(bad)
    destination = output or (ensure_dir(state_root() / "indexes") / "defs-index.json")
    payload = {
        "schema": 1,
        "game_root": str(game_root),
        "game_version": version,
        "mods_config_resolved": ids is not None,
        "record_count": len(records),
        "errors": errors,
        "warnings": warnings,
        "records": [asdict(r) for r in records],
    }
    write_json(destination, payload)
    return {
        "ok": True,
        "index": str(destination),
        "records": len(records),
        "parse_errors": len(errors),
        "warnings": len(warnings),
        "game_version": version,
    }


def load_index(path: Path | None = None) -> dict:
    target = path or (state_root() / "indexes" / "defs-index.json")
    if not target.is_file():
        raise FileNotFoundError(f"Def index not found: {target}. Run `rwforge index` first.")
    with target.open("r", encoding="utf-8") as f:
        return json.load(f)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in TOKEN_RE.findall(text)}


def search_index(query: str, def_type: str | None = None, index_path: Path | None = None, limit: int = 20) -> list[dict]:
    data = load_index(index_path)
    q = query.strip().lower()
    qt = _tokens(q)
    scored: list[tuple[float, dict]] = []
    for rec in data.get("records", []):
        if def_type and rec.get("def_type", "").lower() != def_type.lower():
            continue
        name = (rec.get("def_name") or "")
        label = (rec.get("label") or "")
        hay = f"{name} {label} {rec.get('def_type','')} {rec.get('source_pack','')}".lower()
        score = 0.0
        if name.lower() == q:
            score += 100
        if label.lower() == q:
            score += 80
        if q and q in name.lower():
            score += 35
        if q and q in label.lower():
            score += 25
        overlap = qt & _tokens(hay)
        score += 8 * len(overlap)
        if qt:
            score += 4 * len(overlap) / math.sqrt(len(qt))
        if score > 0:
            scored.append((score, rec))
    scored.sort(key=lambda x: (-x[0], x[1].get("def_name") or ""))
    return [{"score": round(score, 2), **rec} for score, rec in scored[: max(1, limit)]]


def _parent_chain(record: dict, by_name: dict[str, dict]) -> list[dict]:
    """Walk ParentName through the index so agents can see the inheritance path."""
    chain: list[dict] = []
    seen: set[str] = set()
    current = record
    while True:
        parent_name = (current.get("parent_name") or "").strip()
        if not parent_name or parent_name.lower() in seen:
            break
        seen.add(parent_name.lower())
        parent = by_name.get(parent_name.lower())
        if not parent:
            chain.append({"name": parent_name, "found": False})
            break
        chain.append({
            "name": parent_name,
            "found": True,
            "def_type": parent.get("def_type"),
            "source_pack": parent.get("source_pack"),
            "source_file": parent.get("source_file"),
            "abstract": parent.get("abstract", False),
        })
        current = parent
    return chain


def inspect_def(def_name: str, index_path: Path | None = None) -> dict | None:
    data = load_index(index_path)
    records = data.get("records", [])
    by_name = {(r.get("def_name") or "").lower(): r for r in records if r.get("def_name")}
    for rec in records:
        if (rec.get("def_name") or "").lower() == def_name.lower():
            source = Path(rec["source_file"])
            xml = None
            try:
                tree = ET.parse(source)
                for child in tree.getroot():
                    if (child.findtext("defName") or "").lower() == def_name.lower():
                        xml = ET.tostring(child, encoding="unicode")
                        break
            except Exception:
                pass
            return {
                **rec,
                "game_version": data.get("game_version"),
                "xml": xml,
                "parent_chain": _parent_chain(rec, by_name),
                "note": "Raw XML plus the ParentName chain. Forge does not emulate Verse.XmlInheritance merging; inherited fields must be read from the parent records.",
            }
    return None
