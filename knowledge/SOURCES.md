# Knowledge sources and evidence policy

RimWorldForge prefers installed game data over bundled prose. This file is a map of current public references, not a frozen copy of their content.

## Priority

1. Observed RimWorld runtime and Player.log
2. Installed Core/DLC Defs and assemblies
3. Current official Ludeon announcements / modder material
4. Current framework repositories and documentation
5. Community-maintained RimWorld Wiki
6. Model memory

## Sources checked for the 0.1.0 foundation

### RimWorld Wiki: Mod Folder Structure
https://rimworldwiki.com/wiki/Modding_Tutorials/Mod_Folder_Structure

Useful for recognized folders, About/Defs/Patches/Assemblies/Textures/Sounds/Languages, `LoadFolders.xml`, versioned folders, `IfModActive`/`IfModActiveAll`/`IfModNotActive`, and case-sensitive paths. It also explicitly recommends only declaring versions that were actually tested.

### RimWorld Wiki: About.xml
https://rimworldwiki.com/wiki/Modding_Tutorials/About.xml

Useful for required metadata tags, packageId behavior, dependencies and supportedVersions.

### RimWorld Wiki: XML Defs
https://rimworldwiki.com/wiki/Modding_Tutorials/XML_Defs
https://rimworldwiki.com/wiki/Modding_Tutorials/Defs

Useful for the Def/C# relationship and the recommendation to use installed vanilla Defs as examples. This is why RimWorldForge indexes the user's real `Data` tree instead of shipping a giant copied schema.

### RimWorld Wiki: XML file structure
https://rimworldwiki.com/wiki/Modding_Tutorials/XML_file_structure

Useful for `<Defs>` root structure and XML keyword conventions such as `ParentName`, `Abstract` and `Class`.

### Ludeon Studios: Update 1.6.4850
https://ludeon.com/blog/2026/06/update-1-6-4850-released/

Confirms the current 1.6 line in June 2026. The Forge should still inspect the installed game instead of assuming every user is on the latest build.

### Ludeon Studios: Odyssey and update 1.6
https://ludeon.com/blog/2025/06/announcing-odyssey-and-update-1-6/
https://ludeon.com/blog/2025/07/the-rimworld-odyssey-expansion-is-out-now/

Useful for 1.6/Odyssey context.

### Humanoid Alien Races
https://github.com/erdelf/AlienRaces

`About/About.xml` currently declares 1.6 support. Its project description states that it can define custom humanoid races largely through XML and supports graphics/body addons, gender distribution, backstories, thoughts and race restrictions. Forge treats HAR as an optional dependency, never a vendored component.

### RimWorld 1.7 and the Waylith engine (October 2026)

https://ludeon.com/blog/2026/10/announcing-the-waylith-engine-and-update-1-7/
https://rimworldwiki.com/wiki/Modding_Tutorials/RimWorld_1.7_Mod_Updates
https://docs.google.com/document/d/e/2PACX-1vSykw5_DYaaw42nEznI9zmBZVT_Vgg2bxYq_v2XWvAsHC3QSKFuDK2OyiQ5WC9jvVRUcrjpFt7xLLF5/pub
https://github.com/pardeike/HarmonyRimWorld

1.7 moves the game to the Waylith engine and .NET 10. Mods compile against
`Assembly-CSharp.dll`, `UnityStubs.dll` and `Waylith.dll`; Harmony 3 enforces
injection type checks. `Player.log` moves to a `Logs/` subfolder and Harmony
writes `harmony.log.txt` beside it. The update is on the unstable Steam branch
as of October 2026; the main branch remains 1.6.

### Harmony
https://github.com/pardeike/Harmony
https://harmony.pardeike.net/

Optional code-patching framework. RimWorldForge does not assume Harmony is present and does not vendor it.

## Freshness rule

An agent must not use this file to claim an exact current RimWorld build, framework version, or API shape. Inspect the installed game and fetch current upstream docs when the exact version matters.
