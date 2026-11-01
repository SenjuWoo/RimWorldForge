---
name: rimworld-forge
description: Build, inspect, validate, debug, and package RimWorld 1.6 and 1.7 mods with RimWorldForge. Use for RimWorld NPCs, pawn kinds, weapons, apparel, buildings, factions, genes, xenotypes, mechanoids, HAR races, C# mods, Harmony work, Def/Patch XML, art asset planning, or Player.log diagnosis.
---

# RimWorldForge agent skill

Use RimWorldForge as the execution and evidence layer. Do not answer a concrete mod-building request from memory when the installed game can settle the XML shape.

**Forge-first:** on any RimWorld modding request, run `rwforge doctor`, ensure an index exists, and prefer Forge's search/validate/build loop over recalled XML. If the CLI is not on PATH, use the project's `.venv\Scripts\rwforge.exe`.

## Default sequence

1. `rw_doctor`.
2. Ensure a Def index exists for the current game/DLC set.
3. Search several close vanilla/DLC examples with `rw_def_search`.
4. Inspect exact XML with `rw_def_inspect` before using unfamiliar parents/fields.
5. Choose the least-powerful surface that works: Defs, PatchOperations, established framework, C#, then Harmony.
6. Create/reuse a Forge workspace.
7. Write a JSON plan under `plans/` and run `rw_plan_validate`.
8. `rw_generate`.
9. `rw_validate` using the real Def index.
10. Resolve errors and meaningful warnings before `rw_build`.
11. If code is required, use the CLI C# scaffold/build commands and distinguish compiler evidence from runtime evidence.
12. After the user tests the mod in RimWorld, use `rw_log_analyze` on Player.log and repair relevant failures. 1.7 also writes `Logs/Player.log` and `harmony.log.txt`; Forge reads both and de-mangles Harmony wrapper frames.

## 1.6 vs 1.7

- 1.6: `net472`, Harmony 2.4.3, `LocalLow/.../Player.log`.
- 1.7: `net10.0` on the Waylith engine, Harmony 3, `Logs/Player.log` plus `harmony.log.txt`.
- Most 1.6 mods load on 1.7 unchanged. Do not force a rebuild without evidence that the assembly actually needs one.
- `rwforge csharp-scaffold --version 1.7` generates the 1.7 reference set; 1.7 assemblies land in `source/1.7/Assemblies`.
- Declare only the versions actually tested in `About.xml`. 1.7 was an unstable branch in October 2026.

## Routing

- Normal content: vanilla XML Defs first.
- Existing-content edits: PatchOperations instead of overriding entire vanilla Defs.
- Human NPC archetypes: PawnKindDef + faction/equipment/backstory integration.
- Biotech species concepts: GeneDef/XenotypeDef if genes can represent it.
- Full custom humanoid race graphics/restrictions: current Humanoid Alien Races when the user accepts that dependency. Inspect current framework docs/examples, never guess HAR fields.
- Custom behavior: inspect Comp/ability/job/framework options before Harmony.
- Harmony: only for behavior that truly requires patching existing methods.

## Art

Read `docs/ART-PIPELINE.md`. Create/update `plans/ASSETS-NEEDED.json` before generating art. Ask an image system for individual transparent game assets, not a collage. Preserve direction, scale, anchor and naming across multi-direction sprites. A concept image is not a validated game texture.

### Free procedural art (default)

When no paid image model is available, use the built-in local generator:

```text
rwforge assets-generate <workspace>
rwforge assets-generate <workspace> --force --seed my-mod-v1
```

It draws buildings, weapons, apparel, items, icons, directional pawns and 640x360 previews with Pillow. It is deterministic, offline and free. Inspect the PNG at 1:1 and in game; the generator proves presence and hashes, not visual correctness.

### Golden path

`rwforge demo --output Workspaces/Demo` creates a small two-def mod, draws its art, validates it and builds a ZIP. Use it to prove the local toolchain, then replace the demo content with the real plan.

## Evidence language

Never call a mod "working" because XML parsed.

Report the strongest proven tier only:

- syntax_valid
- references_valid
- compiled
- load_tested
- runtime_tested
- visual_tested

The foundation automates only the earlier tiers. If the user has not launched RimWorld, say load/runtime testing has not occurred.

## Docs

Read only the relevant file:

- `docs/MODDING-GUIDE.md` for mod/XML structure
- `docs/CONTENT-RECIPES.md` for NPCs, factions, xenotypes, HAR races, animals, mechs, gear and buildings
- `docs/ART-PIPELINE.md` for textures and generated art
- `docs/VALIDATION.md` for evidence
- `docs/EXTENDING.md` when adding Forge capabilities
- `knowledge/SOURCES.md` for source hierarchy and freshness rules
