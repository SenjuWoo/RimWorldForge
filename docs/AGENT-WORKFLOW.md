# Agent workflow

This is the default operating loop for an AI agent using RimWorldForge.

## Golden path first

If the user asks for a complete mod and the local toolchain is unproven, run
`rwforge demo --output Workspaces/Demo` once. It creates a small mod, draws its
art locally, validates it and builds a ZIP. Then replace the demo plan with the
real design. This proves the install before spending tokens on content.

## Before authoring

1. Run `rw_doctor` / `rwforge doctor`.
2. Run or refresh the Def index if the game path/build/DLC set changed.
3. Search two to five semantically close vanilla/DLC examples.
4. Inspect at least one exact source Def before inventing an unfamiliar field or parent.
5. Decide the least-powerful implementation surface that can express the feature.

Preferred order:

```text
Defs -> PatchOperations -> established framework -> C# -> Harmony patch
```

Do not use C# just because it feels more programmable.

## Content routing

### Items, apparel, weapons, buildings, plants, recipes, research
Start with vanilla Defs. Copy structure, not defNames or balance blindly.

### Human NPC archetypes
Start with `PawnKindDef`, backstories, faction/pawn group integration and normal equipment definitions.

### Biotech-style species concepts
If the behavior can be expressed through genes, use `GeneDef` and `XenotypeDef`. Search installed Biotech examples first.

### Full humanoid races
If the user accepts a framework dependency and needs custom body graphics, tails, race restrictions or similar race-level behavior, inspect current Humanoid Alien Races documentation and installed examples. Add HAR as an explicit dependency in About.xml. Never assume a HAR XML field from memory if the framework can be inspected.

### Mechanoids
Search installed Biotech/Core mechanoids and determine whether the desired unit is a pawn/mech race, a `PawnKindDef`, equipment/projectile set, or a custom code behavior. The bundled Warden example is a plan-shape example, not a universal mech recipe.

### New behavior
Try `CompProperties`, `DefModExtension`, jobs, abilities or framework facilities before Harmony. Use Harmony only when a stable hook into existing behavior is actually required.

## Art

Create an asset manifest before generating images. The manifest defines role, target path, transparency, directions, framing and symmetry constraints. Generate game assets individually, not as a sticker sheet.

If no paid image model is available, use the free local generator:

```text
rwforge assets-generate <workspace>
rwforge assets-sheet <workspace>
```

It draws buildings, weapons, apparel, items, icons, directional pawns and
previews with Pillow. `assets-sheet` combines them into one labelled image.
Inspect the PNGs at 1:1; generation is not visual proof.

After assets land, run validation again. Then test in-game at the actual draw scale.

## Build and test

1. `plan-validate`
2. `generate`
3. `assets-generate` when the plan declares art
4. `validate --index <real index>`
5. optional `csharp-build --approve`
6. `build`
7. `stage --approve` only after the user intends to test
8. user launches RimWorld and enables the mod
9. `log-analyze`
10. repair and repeat

Do not claim success before the evidence tier required by the user's request exists.

## What to report

A concise result should state:

- files/features created
- validation result
- whether C# compiled
- whether RimWorld actually loaded it
- whether gameplay/visuals were tested
- unresolved warnings and asset requirements

That makes a weak model useful instead of merely confident.
