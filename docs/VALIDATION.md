# Validation and evidence

## RimWorld 1.6 and 1.7

The validator accepts either `1.6` or `1.7` in `supportedVersions`. It checks that
`LoadFolders.xml` version blocks point at folders that exist and that every
declared version has a block. It does not claim that a 1.7 load succeeds just
because the XML parses.

## Static validation is intentionally not a game emulator

RimWorld loads XML through reflection-heavy game code, resolves cross-references after Def loading, and many semantic problems only appear when content is instantiated. Static analysis can catch a large class of failures, but it cannot honestly prove runtime correctness.

## Evidence states

### syntax_valid
About/Defs/Patches parsed and structural static checks passed.

### references_valid
Forge had a real installed-game Def index and conservative reference checks found no blocking errors. This is still not exhaustive because XML field semantics vary by Def class and framework.

### compiled
A configured C# project compiled and produced a DLL. Compiler success does not prove Harmony targets exist or gameplay code is correct.

### load_tested
RimWorld actually loaded the mod in a controlled test run without relevant startup failures. Foundation 0.1 does not automate this tier.

### runtime_tested
Generated content was instantiated and exercised. Foundation 0.1 does not automate this tier.

### visual_tested
A human or vision system inspected actual in-game rendering at expected rotations, scales and UI contexts.

## Procedural art is not visual evidence

`rwforge assets-generate` proves that a PNG exists at the declared path, with the
requested canvas and a recorded hash. It does **not** prove the anchor, draw
size, rotation, layering or in-game readability. Those remain `visual_tested`
and require a screenshot or human inspection.

## Warning philosophy

Warnings are used where the validator has a useful suspicion but insufficient type information to safely reject the build, for example:

- a texture path has no obvious local PNG/DDS
- a reference-looking XML tag points to a string absent from the current compact Def index
- a non-abstract Def lacks a defName

A future reflection index can promote some warnings to errors when it can prove the field type from the installed assemblies.

Forge deliberately does not emulate `Verse.XmlInheritance` merging. `inspect`
returns the raw XML and the ParentName chain; an agent must read the parent
records for inherited fields instead of assuming a merged DOM.
