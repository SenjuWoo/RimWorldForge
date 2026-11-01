# Changelog

## 0.4.0 - 2026-11-01

Free, local procedural art and a one-command demo.

- Added `rwforge assets-generate`: deterministic Pillow drawings for buildings,
  weapons, apparel, items, icons, directional pawns and 640x360 previews. No
  network, no paid API; every output is hashed in `reports/assets-generated.json`.
- Added `rwforge assets-sheet`: one labelled contact sheet of every generated PNG
  for fast visual review.
- Added `rwforge demo --output <dir>`: creates a two-def mod, draws its art,
  validates it and builds a ZIP as a pipeline proof.
- Added `rw_assets_generate` to the MCP façade (12 tools).
- Validator recognises directional pawn outputs (`Pawn_south.png`, ...) instead
  of warning that the base target is missing.
- Installer creates an `rwforge` launcher and adds it to the user PATH; the
  uninstaller removes both.
- CI installs the package before testing so Pillow and packaging are exercised.
- 32 offline tests.

## 0.3.0 - 2026-10-31

RimWorld 1.7 (Waylith engine / .NET 10) support, with 1.6 behavior preserved.

- Discovery reads both the 1.6 `Player.log` and the 1.7 `Logs/Player.log` plus
  `harmony.log.txt`; Managed assemblies are probed by file rather than by a
  hardcoded executable or folder name.
- Def indexing follows the documented loader rules: root, `Common`, the highest
  compatible version folder (`1.7` loads `1.6` when no `1.7` exists), and
  `LoadFolders.xml` with `IfModActive` (OR), `IfModActiveAll` (AND) and
  `IfModNotActive`, evaluated against `ModsConfig.xml`. Same-relative-path
  collisions are reported as warnings.
- `inspect` returns the ParentName chain; Forge still does not claim to emulate
  `Verse.XmlInheritance` merging.
- Log triage de-mangles Harmony `_PatchN` wrapper frames, assigns failure phases,
  correlates `harmony.log.txt`, groups storm signatures, and can redact local
  paths, Steam IDs, IPs and emails.
- C# scaffolding is version-aware: 1.6 `net472` with Unity references, 1.7
  `net10.0` with `Assembly-CSharp`, `UnityStubs` and `Waylith`, outputs to
  `1.7/Assemblies` for 1.7. Builds use deterministic MSBuild flags.
- Staging writes a SHA-256 ownership manifest, backs up unowned files under
  `Mods/.rwforge-backups`, and adds `stage-rollback`.
- 28-test suite (was 11), including synthetic 1.6/1.7 fixtures.
- Deferred with reasons: full `Verse.XmlInheritance` emulation, reflection-backed
  XML field validation, SQLite FTS5 cache, FastMCP/Pydantic rewrite, Grok/Kimi
  wiring. Each needs the real game assemblies or is a rewrite without a verified
  user-facing gain.

## 0.2.1 - 2026-08-29

- Installer now repairs the Hermes `rimworld` profile to match `roblox`/`skyrim`: junction `plugins` -> default `hermes/plugins`, seed all bundled skills (rimworld profile was stuck at 15 skills vs 247), and repair the truncated `config.yaml` so default plugins/skills show up. Keeps the `rimworldforge` MCP and mirrors default-profile MCPs (github/context7/headroom). Future installs are self-healing; existing broken profiles are patched in place.

## 0.2.0 - 2026-08-29

Real-library hardening, proven against a 460+ mod Steam Workshop installation.

- mod Def indexing now reads versioned layouts: `1.6/`, `Common/`, flat `Defs/`,
  and `LoadFolders.xml` (v1.6 entries only). Legacy version dirs are skipped
  (1.6-focused, no wasted index).
- Player.log analyzer collapses identical repeated lines and reports
  `storms`: per-line repeat counts for the `[Ref XXXX] Duplicate stacktrace`
  pattern Unity uses to hide original stacks, plus the line number of the
  first (full-stack) block.
- framework detection expanded: Big & Small, VEF/VFEC, VFEC Core, Giddy-Up,
  RimJobWorld, RimTalk, HugsLib.
- 9-test suite (was 7), covering versioned-layout indexing and storm detection.

## 0.1.0-foundation - 2026-08-29

Initial working foundation.

- local RimWorld discovery with Steam library probing
- Core + Royalty + Ideology + Biotech + Anomaly + Odyssey Def indexing
- ranked Def search and raw source inspection
- installed-Def to typed-plan blueprint conversion
- local/Steam Workshop mod inventory with key framework detection
- production art-prompt emission from asset manifests
- transactional mod workspaces
- generic typed JSON-to-RimWorld-XML generation
- About.xml, dependency and LoadFolders generation
- static validation with evidence tiers
- local texture and declared-asset checks
- optional installed-game reference candidate checks
- deterministic mod folder/ZIP build with SHA-256 receipt
- Player.log classifier
- C# net472 scaffold against installed managed assemblies
- approval-gated compiler and live Mods staging
- 11-tool zero-dependency stdio MCP façade
- agent skill, modding/art/validation/extension docs
- Warden mech and Biotech xenotype teaching plans
- concept SVG art example
- self-contained unittest suite
