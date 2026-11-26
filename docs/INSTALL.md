# Install

Requirements: Windows 10/11, macOS, or Linux; Python 3.10+; Pillow is installed with the package; RimWorld 1.6 or 1.7 for game-aware operations.

## One click (Windows)

Double-click:

```text
START-HERE.bat
```

or run:

```powershell
.\Install.ps1
```

The installer creates `.venv`, installs RimWorldForge, runs its self-tests, creates an
`rwforge` launcher in `%LOCALAPPDATA%\RimWorldForge\bin` and adds that folder to your user
PATH (open a new shell afterwards). Then it wires up every agent CLI it finds on the machine:

| Agent | What it does |
|---|---|
| **Hermes** | Creates a dedicated `rimworld` profile (`hermes -p rimworld`) if it does not exist, adds the rimworldforge MCP server **only in that profile** and installs the skill there — zero token cost in other profiles. It never seeds skills from other profiles, never borrows another forge's config and never rewrites Hermes YAML by text substitution |
| **Claude Code** | Registers the MCP at user scope (`claude mcp add --scope user`) and installs the skill to `~/.claude/skills` |
| **Codex CLI** | Copies the skill to `~/.codex/skills` (Codex has no project-scoped MCP config; point it at the server command manually if wanted) |

Integration is additive: an existing MCP registration or skill is left untouched, a config
file is backed up before a registration is added and restored if the client command fails,
and no other profile directory is deleted or replaced. No RimWorld files, mod lists or saves
are touched.

Installer switches:

| Switch | Effect |
|---|---|
| `-DryRun` | print what would happen; change nothing |
| `-NoAgentIntegration` | standalone install; Hermes, Claude Code and Codex are not touched |
| `-SkipTests` | skip the self-test run after `pip install` |

### Uninstall

`Uninstall.ps1` removes the rimworldforge MCP from Claude Code's user config (keep it with
`-KeepMcp`), the skill copies in `~/.claude/skills`, `~/.codex/skills` and the Hermes
`rimworld` profile, the `rwforge` launcher and its PATH entry, and the local `.venv`. The
Hermes `rimworld` profile itself and its MCP entry are left in place; remove the profile
with Hermes' own profile commands if you no longer want it. Generated workspaces stay
where you created them, and no RimWorld files, saves or active mod configuration are removed.

## Manual

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e .      # Windows
# .venv/bin/python -m pip install -e .        # Linux/macOS

rwforge doctor
rwforge capabilities
```

If automatic discovery misses your install:

```powershell
$env:RIMWORLD_ROOT = 'D:\SteamLibrary\steamapps\common\RimWorld'
rwforge doctor
```

## Environment variables (all optional)

| Variable | Purpose |
|---|---|
| `RIMWORLD_ROOT` | RimWorld install root, if registry/Steam discovery fails |
| `RIMWORLD_WORKSHOP_ROOT` | Extra Steam Workshop content root(s) to scan for mods (`os.pathsep`-separated for several). Each may be either the `steamapps/workshop/content/294100` folder itself or its parent `steamapps/workshop` folder |
| `RIMWORLD_MODS_ROOT` | Additional mods directory beyond the game's own `Mods` folder |
| `RIMWORLD_FORGE_HOME` | Where the index is stored (defaults to the platform data directory) |
| `RIMWORLD_FORGE_OFFLINE` | Set to `1` to skip Steam library auto-discovery (used by the offline tests) |
| `RWFORGE_DEBUG` | Set to `1` to write `rwforge.log` in the forge's state folder (`%LOCALAPPDATA%\RimWorldForge` on Windows); off by default, never records file contents |

`rwforge index` auto-discovers mods from the game's `Mods` folder plus **every Steam
library's** Workshop content root found via `libraryfolders.vdf` — multi-drive Steam
setups need no configuration. Pass `--mods-root` explicitly to replace auto-discovery.
