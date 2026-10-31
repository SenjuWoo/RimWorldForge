"""Version and LoadFolders resolution shared by indexing, validation and C# builds.

RimWorld 1.6 and 1.7 can live in the same mod folder but load different subsets of
it. This module implements the documented loader rules instead of guessing at
Verse internals:

- Without LoadFolders.xml: root + Common + the highest versioned folder that is
  not newer than the running game.
- LoadFolders.xml supersedes those defaults and lists folders in load order.
- IfModActive is an OR over a comma list, IfModActiveAll is an AND (1.6+), and
  IfModNotActive is the negation.
- When two loaded folders contain the same relative file, the later folder wins.

No game files are written here; every helper is pure filesystem inspection.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

# Versions Forge understands today. Unknown future versions are still probed by
# discovery; this list only drives defaults and validation messages.
SUPPORTED_VERSIONS = ("1.6", "1.7")

_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)")
_FOLDER_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")


def normalize_version(text: str | None) -> str | None:
    """'1.7.2600 rev123' -> '1.7'; anything without a major.minor pair -> None."""
    if not text:
        return None
    match = _VERSION_RE.match(text)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def version_tuple(version: str | None) -> tuple[int, int]:
    normalized = normalize_version(version)
    if not normalized:
        return (0, 0)
    major, minor = normalized.split(".")
    return (int(major), int(minor))


def config_dir() -> Path:
    """Per-user RimWorld config directory (ModsConfig.xml lives here)."""
    if os.name == "nt":
        base = Path(os.environ.get("USERPROFILE", Path.home()))
        return base / "AppData" / "LocalLow" / "Ludeon Studios" / "RimWorld by Ludeon Studios" / "Config"
    if os.sys.platform == "darwin":
        return Path.home() / "Library/Application Support/RimWorld/Config"
    return Path.home() / ".config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config"


def mods_config_path() -> Path:
    override = os.environ.get("RWFORGE_MODS_CONFIG")
    if override:
        return Path(override).expanduser()
    return config_dir() / "ModsConfig.xml"


def active_package_ids(path: Path | None = None) -> set[str] | None:
    """Lowercased packageIds from ModsConfig.xml, or None when it is unavailable.

    None is not "no mods active": it means conditional LoadFolders entries cannot
    be evaluated, so callers must include them and say so.
    """
    target = path or mods_config_path()
    if not target.is_file():
        return None
    try:
        root = ET.parse(target).getroot()
    except (ET.ParseError, OSError):
        return None
    ids = {(li.text or "").strip().lower() for li in root.iter("li") if (li.text or "").strip()}
    return ids


def _version_dirs(mod_dir: Path) -> list[tuple[tuple[int, int], Path]]:
    found: list[tuple[tuple[int, int], Path]] = []
    try:
        children = list(mod_dir.iterdir())
    except OSError:
        return found
    for child in children:
        if child.is_dir():
            match = _FOLDER_VERSION_RE.match(child.name)
            if match:
                found.append(((int(match.group(1)), int(match.group(2))), child))
    return found


def default_version_dir(mod_dir: Path, active_version: str | None) -> Path | None:
    """Highest versioned folder not newer than the running game (documented rule)."""
    candidates = _version_dirs(mod_dir)
    if not candidates:
        return None
    if active_version is None:
        # No detected game: index every known version folder rather than silently
        # choosing one. build_index() adds the rest explicitly.
        return None
    limit = version_tuple(active_version)
    compatible = [(ver, path) for ver, path in candidates if ver <= limit]
    if not compatible:
        return None
    return max(compatible, key=lambda item: item[0])[1]


def load_folders_file(mod_dir: Path) -> Path | None:
    """LoadFolders.xml is case-insensitive in the game; match that here."""
    try:
        for child in mod_dir.iterdir():
            if child.is_file() and child.name.lower() == "loadfolders.xml":
                return child
    except OSError:
        pass
    return None


def _split_ids(value: str | None) -> list[str]:
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def _entry_active(entry: ET.Element, active_ids: set[str] | None) -> tuple[bool, bool]:
    """Return (active, resolved). resolved=False means ModsConfig was unavailable."""
    required_any = _split_ids(entry.attrib.get("IfModActive"))
    required_all = _split_ids(entry.attrib.get("IfModActiveAll"))
    forbidden = _split_ids(entry.attrib.get("IfModNotActive"))
    if not (required_any or required_all or forbidden):
        return True, True
    if active_ids is None:
        return True, False
    if required_any and not any(pid in active_ids for pid in required_any):
        return False, True
    if required_all and not all(pid in active_ids for pid in required_all):
        return False, True
    if any(pid in active_ids for pid in forbidden):
        return False, True
    return True, True


def _select_version_block(root: ET.Element, active_version: str | None) -> tuple[ET.Element | None, str | None]:
    blocks: list[tuple[tuple[int, int], ET.Element]] = []
    for node in root:
        normalized = normalize_version(node.tag.lstrip("vV"))
        if normalized:
            blocks.append((version_tuple(normalized), node))
    if not blocks:
        return None, None
    if active_version:
        wanted = version_tuple(active_version)
        for ver, node in blocks:
            if ver == wanted:
                return node, None
        compatible = [(ver, node) for ver, node in blocks if ver <= wanted]
        if compatible:
            ver, node = max(compatible, key=lambda item: item[0])
            return node, f"LoadFolders.xml has no v{active_version} block; using v{ver[0]}.{ver[1]}"
        return None, f"LoadFolders.xml has no block compatible with RimWorld {active_version}"
    # No detected version: use the newest block as a best-effort superset.
    ver, node = max(blocks, key=lambda item: item[0])
    return node, f"No RimWorld version detected; LoadFolders.xml v{ver[0]}.{ver[1]} used for indexing"


def resolve_load_folders(
    mod_dir: Path,
    active_version: str | None,
    active_ids: set[str] | None,
) -> tuple[list[Path] | None, list[dict]]:
    """Return loaded folders for a mod, or (None, warnings) when no LoadFolders.xml.

    A returned list preserves load order; '/' resolves to the mod root. Conditions
    that cannot be evaluated (no ModsConfig.xml) are included and reported.
    """
    warnings: list[dict] = []
    path = load_folders_file(mod_dir)
    if path is None:
        return None, warnings
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        warnings.append({"code": "loadfolders.parse", "file": str(path), "message": str(exc)})
        return None, warnings
    if root.tag.lower() != "loadfolders":
        warnings.append({"code": "loadfolders.root", "file": str(path), "message": "LoadFolders.xml root must be <loadFolders>"})
        return None, warnings
    block, block_warning = _select_version_block(root, active_version)
    if block_warning:
        warnings.append({"code": "loadfolders.version", "file": str(path), "message": block_warning})
    if block is None:
        return [], warnings
    folders: list[Path] = []
    for entry in block.findall("li"):
        active, resolved = _entry_active(entry, active_ids)
        text = (entry.text or "").strip()
        if not active:
            continue
        if not resolved:
            warnings.append({
                "code": "loadfolders.conditions_unresolved",
                "file": str(path),
                "message": f"ModsConfig.xml unavailable; conditional folder '{text}' indexed as active",
            })
        relative = text.strip("./").strip("/")
        folder = mod_dir if relative in ("", ".") else mod_dir / relative
        if folder.is_dir() and folder not in folders:
            folders.append(folder)
        elif not folder.is_dir():
            warnings.append({"code": "loadfolders.missing", "file": str(path), "message": f"Load folder does not exist: {text or '/'}"})
    return folders, warnings


def relative_file_collisions(folders: Iterable[Path], suffixes: tuple[str, ...] = (".xml",)) -> list[dict]:
    """Same relative path in several loaded folders: the later folder wins.

    This is legal RimWorld behavior, not a loader bug, but it silently hides a
    file the author probably expected to load. Report it as a warning.
    """
    seen: dict[str, Path] = {}
    collisions: list[dict] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            key = path.relative_to(folder).as_posix().lower()
            previous = seen.get(key)
            if previous is not None and previous != path:
                collisions.append({
                    "code": "loadfolder.collision",
                    "relative_path": key,
                    "earlier": str(previous),
                    "winner": str(path),
                    "message": f"{key} exists in two loaded folders; the later file wins",
                })
            seen[key] = path
    return collisions
