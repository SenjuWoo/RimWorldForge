"""Classify and de-duplicate RimWorld logs from 1.6 and 1.7.

1.7 keeps Player.log in a `Logs/` subfolder and Harmony 3 writes
`harmony.log.txt` beside it. Forge reads both, collapses repeated storm lines,
de-mangles Harmony's dynamic-method wrappers, assigns a coarse failure phase, and
can redact local paths/IDs for shareable reports.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# First matching pattern wins for the coarse phase, so specific XML/Harmony
# signatures are listed before the generic exception catch-all.
PATTERNS = [
    ("cross_reference", re.compile(r"Could not resolve cross-reference|Failed to find a named object", re.I)),
    ("xml_inheritance", re.compile(r"Could not register node|GetBestParentFor|CheckForDuplicateNodes|XmlInheritance", re.I)),
    ("xpath", re.compile(r"Failed to find a node with the given xpath|PatchOperation.*(?:failed|error)|XML patch operation", re.I)),
    ("def_error", re.compile(r"\[Def Error\]", re.I)),
    ("xml", re.compile(r"XML error|XML loader", re.I)),
    ("type_load", re.compile(r"TypeLoadException|ReflectionTypeLoadException|Could not load type", re.I)),
    ("assembly", re.compile(r"Could not load file or assembly|FileNotFoundException.*\.dll", re.I)),
    ("harmony", re.compile(r"Harmony.*(exception|error|failed)|Patching exception", re.I)),
    ("harmony_wrapper", re.compile(r"\(wrapper dynamic-method\)|_Patch\d+", re.I)),
    ("texture", re.compile(r"Could not load UnityEngine\.Texture|Failed to load texture|Could not load texture", re.I)),
    ("exception", re.compile(r"\b(?:NullReferenceException|InvalidCastException|ArgumentException|InvalidOperationException|Exception:)\b", re.I)),
]

PHASES = {
    "cross_reference": "def_deserialization",
    "xml_inheritance": "xml_inheritance",
    "xpath": "xpath_patching",
    "def_error": "def_deserialization",
    "xml": "xml_registration",
    "type_load": "harmony_init",
    "assembly": "harmony_init",
    "harmony": "harmony_init",
    "harmony_wrapper": "harmony_init",
    "texture": "render_loop",
    "exception": "runtime_tick",
}

# Lines that only matter in aggregate: dozens of identical "Duplicate stacktrace"
# lines mean a per-tick or per-frame thrower, and the original stack is in the
# first block.
AGGREGATE_PATTERNS = {
    "duplicate_stack_ref": re.compile(r"\[Ref [0-9A-Fa-f]+\]\s*(Duplicate stacktrace, see ref for original)?"),
}

# Harmony 2.4+/3 emits dynamic wrapper frames such as
# (wrapper dynamic-method) MonoMod.Utils.DynamicMethodDefinition:Verse.LoadedModManager.ParseAndProcessXML_Patch7
WRAPPER_RE = re.compile(r"\(wrapper dynamic-method\)[^:]*:(?P<method>[A-Za-z0-9_.`+]+?)_Patch\d+")
PATCH_SUFFIX_RE = re.compile(r"_Patch\d+")

_HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]+\b")
_NUMBER_RE = re.compile(r"\b\d+\b")
_SPACE_RE = re.compile(r"\s+")


def _kinds(text: str) -> list[str]:
    return [name for name, pattern in PATTERNS if pattern.search(text)]


def _phase(kinds: list[str]) -> str:
    for kind in kinds:
        phase = PHASES.get(kind)
        if phase:
            return phase
    return "unknown"


def demangle_methods(text: str) -> list[str]:
    """Extract the real patched methods from Harmony wrapper frames."""
    return sorted({match.group("method") for match in WRAPPER_RE.finditer(text)})


def storm_signature(text: str) -> str:
    """Stable grouping key for repeated lines that differ only by ids/offsets."""
    value = AGGREGATE_PATTERNS["duplicate_stack_ref"].sub("[ref]", text)
    value = WRAPPER_RE.sub(lambda m: m.group("method"), value)
    value = PATCH_SUFFIX_RE.sub("", value)
    value = _HEX_RE.sub("0x#", value)
    value = _NUMBER_RE.sub("#", value)
    value = _SPACE_RE.sub(" ", value).strip().lower()
    return value[:240]


def redact_text(text: str) -> str:
    """Remove local user paths, Steam ids, IPs and emails from exported reports."""
    home = os.environ.get("USERPROFILE") or str(Path.home())
    if home:
        text = re.sub(re.escape(home), "%USERPROFILE%", text, flags=re.I)
    text = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", r"%USERPROFILE%", text, flags=re.I)
    text = re.sub(r"/home/[^/\s]+", "$HOME", text)
    text = re.sub(r"\b\d{17}\b", "<steamid>", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", text)
    text = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", "<email>", text)
    return text


def _dedupe_storms(
    lines: list[str],
    max_hits: int,
    source: str = "Player.log",
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """Collapse identical repeats. Returns (hits, collapsed_count, storms)."""
    def _stormy(text: str) -> bool:
        return bool(_kinds(text)) or bool(AGGREGATE_PATTERNS["duplicate_stack_ref"].search(text))

    counts: dict[str, int] = {}
    for line in lines:
        t = line.strip()
        if t:
            counts[t] = counts.get(t, 0) + 1

    hits: list[dict[str, Any]] = []
    collapsed = 0
    for i, line in enumerate(lines):
        kinds = _kinds(line)
        if not kinds:
            continue
        text = line.strip()
        if counts[text] > 1:
            collapsed += 1
            if hits and hits[-1]["text"] == text:
                continue  # consecutive identical repeat -> already captured with context
        lo = max(0, i - 1)
        hi = min(len(lines), i + 2)
        methods = demangle_methods(text)
        hits.append({
            "line": i + 1,
            "kinds": kinds,
            "phase": _phase(kinds),
            "text": text,
            "context": lines[lo:hi],
            "source": source,
            **({"harmony_methods": methods} if methods else {}),
        })
        if len(hits) >= max_hits:
            break

    storms: list[dict[str, Any]] = []
    for text, n in counts.items():
        if n >= 25 and _stormy(text):
            first = next(i + 1 for i, l in enumerate(lines) if l.strip() == text)
            kinds = _kinds(text)
            methods = demangle_methods(text)
            storms.append({
                "line": first,
                "text": text,
                "repeats": n,
                "kinds": kinds,
                "phase": _phase(kinds) if kinds else "duplicate_stack_ref",
                "signature": storm_signature(text),
                "source": source,
                **({"harmony_methods": methods} if methods else {}),
            })
    storms.sort(key=lambda s: -s["repeats"])
    return hits, collapsed, storms


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def analyze_log(
    path: Path,
    context: int = 1,
    max_hits: int = 200,
    harmony_log: Path | None = None,
    redact: bool = False,
) -> dict[str, Any]:
    """Analyze Player.log plus the Harmony log that sits beside it.

    `harmony_log=None` auto-detects `harmony.log.txt` next to Player.log. Pass an
    explicit path to force one, or a non-existent path to skip it.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    harmony = harmony_log if harmony_log is not None else path.parent / "harmony.log.txt"
    if not harmony.is_file():
        harmony = None

    lines = _read_lines(path)
    hits, collapsed, storms = _dedupe_storms(lines, max_hits, source=path.name)
    harmony_lines = _read_lines(harmony) if harmony else []
    harmony_hits, harmony_collapsed, harmony_storms = _dedupe_storms(
        harmony_lines, max_hits, source=harmony.name if harmony else "harmony.log.txt"
    )
    hits.extend(harmony_hits)
    storms.extend(harmony_storms)
    storms.sort(key=lambda s: -s["repeats"])
    collapsed += harmony_collapsed

    counts: dict[str, int] = {}
    for hit in hits:
        for kind in hit["kinds"]:
            counts[kind] = counts.get(kind, 0) + 1
    # storm kinds counted from full-text frequency, not the capped hit list
    for storm in storms:
        kinds = storm["kinds"] or ["duplicate_stack_ref"]
        for kind in kinds:
            counts[kind] = counts.get(kind, 0) + storm["repeats"] - 1

    phases: dict[str, int] = {}
    for hit in hits:
        phases[hit["phase"]] = phases.get(hit["phase"], 0) + 1
    for storm in storms:
        phases[storm["phase"]] = phases.get(storm["phase"], 0) + storm["repeats"] - 1

    result: dict[str, Any] = {
        "ok": True,
        "file": str(path),
        "harmony_log": str(harmony) if harmony else None,
        "lines": len(lines),
        "harmony_lines": len(harmony_lines),
        "hits": hits,
        "counts": counts,
        "phases": phases,
        "storms": storms,
        "duplicate_lines_collapsed": collapsed,
        "truncated": len(hits) >= max_hits,
        "redacted": redact,
        "notes": [],
    }
    if storms:
        result["notes"].append(
            "Storm lines repeat identically; the FIRST block in the log holds the original stack."
        )
    if harmony:
        result["notes"].append(
            "Harmony 3 writes harmony.log.txt beside Player.log; wrapper frames are de-mangled to the patched method."
        )
    if redact:
        result["file"] = redact_text(result["file"])
        result["harmony_log"] = redact_text(result["harmony_log"]) if result["harmony_log"] else None
        for hit in result["hits"]:
            hit["text"] = redact_text(hit["text"])
            hit["context"] = [redact_text(line) for line in hit["context"]]
        for storm in result["storms"]:
            storm["text"] = redact_text(storm["text"])
    return result
