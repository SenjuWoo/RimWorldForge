from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable

from .util import json_result
from .versions import normalize_version

DLC_DIRS = ("Core", "Royalty", "Ideology", "Biotech", "Anomaly", "Odyssey")


def _steam_roots_windows() -> Iterable[Path]:
    seen: set[Path] = set()
    candidates: list[Path] = []
    try:
        import winreg  # type: ignore
        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as h:
                    for value_name in ("SteamPath", "InstallPath"):
                        try:
                            value, _ = winreg.QueryValueEx(h, value_name)
                            candidates.append(Path(value))
                        except OSError:
                            pass
            except OSError:
                pass
    except Exception:
        pass
    candidates += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    for root in candidates:
        root = root.expanduser()
        if root in seen:
            continue
        seen.add(root)
        yield root
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                    p = Path(match.group(1).replace("\\\\", "\\"))
                    if p not in seen:
                        seen.add(p)
                        yield p
            except OSError:
                pass


def candidate_game_roots() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("RIMWORLD_ROOT")
    if env:
        out.append(Path(env).expanduser())
    if os.name == "nt":
        for steam in _steam_roots_windows():
            out.append(steam / "steamapps" / "common" / "RimWorld")
    elif sys.platform == "darwin":
        out += [
            Path.home() / "Library/Application Support/Steam/steamapps/common/RimWorld/RimWorldMac.app",
            Path.home() / "Library/Application Support/Steam/steamapps/common/RimWorld",
        ]
    else:
        out += [
            Path.home() / ".steam/steam/steamapps/common/RimWorld",
            Path.home() / ".local/share/Steam/steamapps/common/RimWorld",
        ]
    unique: list[Path] = []
    seen: set[str] = set()
    for p in out:
        key = str(p).lower() if os.name == "nt" else str(p)
        if key not in seen:
            unique.append(p)
            seen.add(key)
    return unique


def validate_game_root(root: Path) -> bool:
    data = root / "Data"
    return data.is_dir() and (data / "Core" / "Defs").is_dir()


def discover_game(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        return p if validate_game_root(p) else None
    for p in candidate_game_roots():
        if validate_game_root(p):
            return p.resolve()
    return None


def game_version(root: Path) -> str | None:
    for candidate in (root / "Version.txt", root / "version.txt"):
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                return text.splitlines()[0].strip()
    return None


def game_version_short(root: Path) -> str | None:
    return normalize_version(game_version(root))


def _walk_find(root: Path, filename: str, max_depth: int = 4) -> Path | None:
    """Bounded search for a file whose folder moved between game versions."""
    root = root.resolve()
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth >= max_depth:
            dirs[:] = []
            continue
        if filename in files:
            return current_path / filename
        # Do not wander into saves, logs, mods or workshop content.
        dirs[:] = [d for d in dirs if d.lower() not in {"mods", "saves", "logs", "workshop", "steamapps"}]
    return None


def managed_dir(root: Path) -> Path | None:
    candidates = [
        root / "RimWorldWin64_Data" / "Managed",
        root / "RimWorldLinux_Data" / "Managed",
        root / "RimWorldMac.app" / "Contents" / "Resources" / "Data" / "Managed",
        root / "Contents" / "Resources" / "Data" / "Managed",
        root / "Data" / "Managed",
    ]
    for p in candidates:
        if p.is_dir() and (p / "Assembly-CSharp.dll").is_file():
            return p
    # 1.7 can reorganise the data folder; find the assembly wherever it lives.
    found = _walk_find(root, "Assembly-CSharp.dll")
    return found.parent if found else None


def _log_bases() -> list[Path]:
    if os.name == "nt":
        base = Path(os.environ.get("USERPROFILE", Path.home()))
        return [base / "AppData/LocalLow/Ludeon Studios/RimWorld by Ludeon Studios"]
    if sys.platform == "darwin":
        return [Path.home() / "Library/Logs/Unity", Path.home() / "Library/Application Support/RimWorld"]
    return [
        Path.home() / ".config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios",
        Path.home() / ".local/share/RimWorld",
    ]


def player_log_candidates() -> list[Path]:
    """Player.log locations, newest convention first (1.7 before 1.6)."""
    out: list[Path] = []
    for base in _log_bases():
        out.append(base / "Logs" / "Player.log")  # 1.7+
        out.append(base / "Player.log")           # 1.6 and earlier
    unique: list[Path] = []
    seen: set[str] = set()
    for p in out:
        key = str(p).lower() if os.name == "nt" else str(p)
        if key not in seen:
            unique.append(p)
            seen.add(key)
    return unique


def player_log_path() -> Path:
    """First existing Player.log, else the 1.7 default path for diagnostics."""
    candidates = player_log_candidates()
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def harmony_log_path(player_log: Path | None = None) -> Path:
    """Harmony 3 writes harmony.log.txt beside Player.log by default."""
    log = player_log or player_log_path()
    return log.parent / "harmony.log.txt"


def doctor(explicit: str | None = None) -> dict:
    root = discover_game(explicit)
    if not root:
        return json_result(False, game_found=False, candidates=[str(p) for p in candidate_game_roots()])
    data = root / "Data"
    packs = {name: (data / name).is_dir() for name in DLC_DIRS}
    managed = managed_dir(root)
    mods = root / "Mods"
    logs = [{"path": str(p), "exists": p.is_file()} for p in player_log_candidates()]
    chosen = player_log_path()
    harmony = harmony_log_path(chosen)
    exe_candidates = sorted(p.name for p in root.glob("*.exe")) if root.is_dir() else []
    return json_result(
        True,
        game_found=True,
        root=str(root),
        version=game_version(root),
        version_short=game_version_short(root),
        data=str(data),
        mods=str(mods),
        managed=str(managed) if managed else None,
        managed_found=bool(managed),
        dlc=packs,
        logs=logs,
        player_log=str(chosen),
        player_log_exists=chosen.is_file(),
        harmony_log=str(harmony),
        harmony_log_exists=harmony.is_file(),
        exe_candidates=exe_candidates,
    )
