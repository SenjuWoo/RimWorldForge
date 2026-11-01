from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Hermetic tests: never probe the real Steam libraries on the dev machine.
os.environ.setdefault("RIMWORLD_FORGE_OFFLINE", "1")

from rwforge.assets import emit_prompts
from rwforge.blueprints import blueprint_from_def
from rwforge.builder import build_project, rollback_stage, stage_project
from rwforge.csharp import scaffold as csharp_scaffold
from rwforge.demo import run_demo
from rwforge.discovery import player_log_candidates
from rwforge.generator import apply_plan, validate_plan
from rwforge.indexer import build_index, inspect_def, search_index
from rwforge.logs import analyze_log, redact_text
from rwforge.mods import scan_mods
from rwforge.project import new_project
from rwforge.validator import validate_workspace
from rwforge.versions import active_package_ids, normalize_version

try:
    import PIL  # noqa: F401
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class ForgeTests(unittest.TestCase):
    def test_plan_validation_rejects_duplicate_defname(self):
        plan = {
            "schema": 1,
            "mod": {"name": "X", "packageId": "a.b"},
            "defs": [
                {"type": "ThingDef", "fields": {"defName": "A"}},
                {"type": "PawnKindDef", "fields": {"defName": "A"}},
            ],
        }
        result = validate_plan(plan)
        self.assertFalse(result["ok"])
        self.assertTrue(any("duplicate" in e for e in result["errors"]))

    def test_workspace_generate_validate_build(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "Demo"
            new_project("Demo Mod", "tester.demo", workspace=ws)
            plan = {
                "schema": 1,
                "mod": {"name": "Demo Mod", "packageId": "tester.demo", "author": "Tester", "supportedVersions": ["1.6"], "description": "Demo"},
                "defs": [{"type": "ThingDef", "attributes": {"ParentName": "BaseThing"}, "fields": {"defName": "Tester_DemoThing", "label": "demo thing", "statBases": {"MarketValue": 10}}}],
                "assets": [],
            }
            plan_path = ws / "plans" / "demo.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            generated = apply_plan(ws, plan_path)
            self.assertTrue(generated["ok"])
            validation = validate_workspace(ws)
            self.assertTrue(validation["ok"], validation)
            built = build_project(ws)
            self.assertTrue(built["ok"], built)
            archive = Path(built["archive"])
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as zf:
                names = zf.namelist()
                self.assertTrue(any(x.endswith("About/About.xml") for x in names))
                self.assertTrue(any(x.endswith("Defs/Generated/ThingDefs.xml") for x in names))

    def test_index_search_and_inspect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "RimWorld"
            defs = root / "Data" / "Core" / "Defs" / "ThingDefs"
            defs.mkdir(parents=True)
            (defs / "Test.xml").write_text("""<?xml version='1.0'?><Defs><ThingDef><defName>Test_Centipede</defName><label>test centipede</label></ThingDef></Defs>""", encoding="utf-8")
            index = Path(td) / "index.json"
            result = build_index(root, output=index)
            self.assertEqual(result["records"], 1)
            hits = search_index("centipede", index_path=index)
            self.assertEqual(hits[0]["def_name"], "Test_Centipede")
            record = inspect_def("Test_Centipede", index)
            self.assertIn("<defName>Test_Centipede</defName>", record["xml"])

    def test_log_analyzer_groups_errors(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "Player.log"
            log.write_text("hello\nCould not resolve cross-reference: No ThingDef named Nope\nNullReferenceException: x\n", encoding="utf-8")
            result = analyze_log(log)
            self.assertEqual(result["counts"]["cross_reference"], 1)
            self.assertEqual(result["counts"]["exception"], 1)

    def test_missing_texture_is_warning_not_fake_success_blocker(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "Demo"
            new_project("Demo Mod", "tester.demo", workspace=ws)
            defs = ws / "source" / "Defs" / "X.xml"
            defs.write_text("<Defs><ThingDef><defName>Tester_X</defName><graphicData><texPath>Tester/Missing</texPath></graphicData></ThingDef></Defs>", encoding="utf-8")
            result = validate_workspace(ws)
            self.assertTrue(result["ok"])
            self.assertTrue(any(w["code"] == "texture.missing" for w in result["warnings"]))

    def test_blueprint_from_indexed_def_and_art_prompts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "RimWorld"
            defs = root / "Data" / "Core" / "Defs"
            defs.mkdir(parents=True)
            (defs / "Weapon.xml").write_text("<Defs><ThingDef ParentName='BaseThing'><defName>Gun_Test</defName><label>test gun</label><statBases><MarketValue>100</MarketValue></statBases></ThingDef></Defs>", encoding="utf-8")
            index = Path(td) / "index.json"
            build_index(root, output=index)
            plan = Path(td) / "blueprint.json"
            result = blueprint_from_def("Gun_Test", "Tester_NewGun", plan, index, "tester.newgun", "New Gun")
            self.assertTrue(result["ok"])
            data = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual(data["defs"][0]["attributes"]["ParentName"], "BaseThing")
            self.assertEqual(data["defs"][0]["fields"]["defName"], "Tester_NewGun")

            ws = Path(td) / "Art"
            new_project("Art", "tester.art", workspace=ws)
            (ws / "plans" / "ASSETS-NEEDED.json").write_text(json.dumps({"schema": 1, "assets": [{"id": "icon", "kind": "ui_icon", "target": "Textures/Test/Icon.png", "transparent": True, "canvas": [128,128], "notes": "sharp silhouette"}]}), encoding="utf-8")
            prompts = emit_prompts(ws)
            self.assertEqual(prompts["count"], 1)
            self.assertIn("production asset brief", Path(prompts["prompts"][0]).read_text(encoding="utf-8"))

    def test_mod_scan_detects_framework(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "RimWorld"
            (root / "Data" / "Core" / "Defs").mkdir(parents=True)
            about = root / "Mods" / "HAR" / "About"
            about.mkdir(parents=True)
            about.joinpath("About.xml").write_text("<ModMetaData><name>Humanoid Alien Races</name><author>x</author><packageId>erdelf.HumanoidAlienRaces</packageId><supportedVersions><li>1.6</li></supportedVersions><description>x</description></ModMetaData>", encoding="utf-8")
            result = scan_mods(root)
            har = next(x for x in result["frameworks"] if x["packageId"] == "erdelf.humanoidalienraces")
            self.assertTrue(har["installed"])

    def test_index_reads_versioned_mod_layouts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "RimWorld"
            (root / "Data" / "Core" / "Defs").mkdir(parents=True)
            # Workshop-style mod: defs under 1.6/, Common/ and LoadFolders.xml
            mod = root / "Mods" / "SomeWorkshopMod"
            for sub in ("Defs", "1.6/Defs", "Common/Defs"):
                d = mod / sub
                d.mkdir(parents=True)
                d.joinpath("D.xml").write_text(
                    f"<Defs><ThingDef><defName>Test_{sub.replace('/', '_')}</defName><label>x</label></ThingDef></Defs>",
                    encoding="utf-8",
                )
            # a 1.5-only defs dir must NOT be indexed
            old = mod / "1.5" / "Defs"
            old.mkdir(parents=True)
            old.joinpath("Old.xml").write_text("<Defs><ThingDef><defName>Test_Legacy</defName></ThingDef></Defs>", encoding="utf-8")
            index = Path(td) / "index.json"
            result = build_index(root, include_mods=root / "Mods", output=index)
            names = {r["def_name"] for r in json.loads(index.read_text(encoding="utf-8"))["records"]}
            self.assertIn("Test_Defs", names)
            self.assertIn("Test_1.6_Defs", names)
            self.assertIn("Test_Common_Defs", names)
            self.assertNotIn("Test_Legacy", names)

    def test_index_default_auto_discovers_workshop_roots(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "RimWorld"
            (root / "Data" / "Core" / "Defs").mkdir(parents=True)
            # game on library A (inside td), workshop content "elsewhere" (second dir in td)
            ws = Path(td) / "OtherLibrary" / "steamapps" / "workshop" / "content" / "294100"
            mod = ws / "555555"
            (mod / "1.6" / "Defs").mkdir(parents=True)
            (mod / "1.6" / "Defs" / "W.xml").write_text("<Defs><ThingDef><defName>Test_WSMod</defName></ThingDef></Defs>", encoding="utf-8")
            # no libraryfolders.vdf inside td; point discovery at the second library via env
            os.environ["RIMWORLD_WORKSHOP_ROOT"] = str(ws)
            try:
                index = Path(td) / "i.json"
                build_index(root, output=index)  # no include_mods -> auto-discovery
                names = {r["def_name"] for r in json.loads(index.read_text(encoding="utf-8"))["records"]}
                self.assertIn("Test_WSMod", names)
            finally:
                os.environ.pop("RIMWORLD_WORKSHOP_ROOT", None)

    def test_scan_mods_detects_framework_by_assembly_marker(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "RimWorld"
            (root / "Data" / "Core" / "Defs").mkdir(parents=True)
            mod = root / "Mods" / "RenamedHarmonyRepack"
            (mod / "About").mkdir(parents=True)
            mod.joinpath("About", "About.xml").write_text("<ModMetaData><name>Some Repack</name><packageId>who.knows</packageId><supportedVersions><li>1.6</li></supportedVersions></ModMetaData>", encoding="utf-8")
            (mod / "1.6" / "Assemblies").mkdir(parents=True)
            (mod / "1.6" / "Assemblies" / "0Harmony.dll").write_bytes(b"MZ")
            result = scan_mods(root)
            harmony = next(f for f in result["frameworks"] if f["name"] == "Harmony")
            self.assertTrue(harmony["installed"])

    def test_log_analyzer_detects_duplicate_ref_storm(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "Player.log"
            storm_line = "InvalidCastException: Specified cast is not valid."
            dup = "[Ref 792923E] Duplicate stacktrace, see ref for original"
            log.write_text("start\n" + "\n".join([storm_line] + [dup] * 3000) + "\n", encoding="utf-8")
            result = analyze_log(log, max_hits=50)
            self.assertGreater(len(result["storms"]), 0)
            storm = max(result["storms"], key=lambda s: s["repeats"])
            self.assertGreaterEqual(storm["repeats"], 1000)
            self.assertEqual(storm["line"], 3)  # the [Ref X] dup line is the repeated one
            self.assertGreater(result["counts"]["duplicate_stack_ref"], 1000)
            self.assertTrue(any("FIRST block" in n for n in result["notes"]))


def _fake_game(root: Path, version: str = "1.6") -> Path:
    """Minimal installed-game tree: Core Defs, Version.txt, managed DLLs, Mods."""
    (root / "Data" / "Core" / "Defs").mkdir(parents=True, exist_ok=True)
    (root / "Version.txt").write_text(version, encoding="utf-8")
    managed = root / "RimWorldWin64_Data" / "Managed"
    managed.mkdir(parents=True, exist_ok=True)
    for name in ("Assembly-CSharp.dll", "UnityEngine.dll", "UnityEngine.CoreModule.dll", "UnityStubs.dll", "Waylith.dll"):
        (managed / name).write_bytes(b"MZ")
    (root / "Mods").mkdir(exist_ok=True)
    return root


class VersionAndLogTests(unittest.TestCase):
    def test_normalize_version(self):
        self.assertEqual(normalize_version("1.7.2600 rev123"), "1.7")
        self.assertEqual(normalize_version("1.6.4850"), "1.6")
        self.assertIsNone(normalize_version("unknown"))

    def test_player_log_candidates_prefer_17_logs_folder(self):
        paths = [str(p).replace("\\", "/") for p in player_log_candidates()]
        self.assertTrue(any(p.endswith("Logs/Player.log") for p in paths))
        self.assertGreaterEqual(len(paths), 2)

    def test_empty_modsconfig_is_resolved_not_missing(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "ModsConfig.xml"
            config.write_text("<ModsConfigData><activeMods/></ModsConfigData>", encoding="utf-8")
            os.environ["RWFORGE_MODS_CONFIG"] = str(config)
            try:
                self.assertEqual(active_package_ids(), set())
            finally:
                os.environ.pop("RWFORGE_MODS_CONFIG", None)

    def test_index_uses_active_version_folder_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = _fake_game(Path(td) / "RimWorld", "1.7.2600")
            mod = root / "Mods" / "Versioned"
            for sub, name in (("1.6/Defs", "Test_16"), ("1.7/Defs", "Test_17"), ("Common/Defs", "Test_Common"), ("Defs", "Test_Root")):
                d = mod / sub
                d.mkdir(parents=True)
                (d / "D.xml").write_text(f"<Defs><ThingDef><defName>{name}</defName></ThingDef></Defs>", encoding="utf-8")
            index = Path(td) / "i.json"
            build_index(root, include_mods=root / "Mods", output=index, active_version="1.7")
            names = {r["def_name"] for r in json.loads(index.read_text(encoding="utf-8"))["records"]}
            self.assertIn("Test_17", names)
            self.assertIn("Test_Common", names)
            self.assertIn("Test_Root", names)
            self.assertNotIn("Test_16", names)

    def test_loadfolders_conditions_follow_modsconfig(self):
        with tempfile.TemporaryDirectory() as td:
            root = _fake_game(Path(td) / "RimWorld", "1.7.2600")
            mod = root / "Mods" / "Conditional"
            (mod / "Defs").mkdir(parents=True)
            (mod / "Defs" / "Base.xml").write_text("<Defs><ThingDef><defName>Test_Base</defName></ThingDef></Defs>", encoding="utf-8")
            for sub, name in (("1.7/Defs", "Test_17"), ("Optional/Defs", "Test_Optional"), ("Both/Defs", "Test_Both")):
                d = mod / sub
                d.mkdir(parents=True)
                (d / "D.xml").write_text(f"<Defs><ThingDef><defName>{name}</defName></ThingDef></Defs>", encoding="utf-8")
            (mod / "LoadFolders.xml").write_text(
                "<loadFolders><v1.7><li>/</li><li>1.7</li>"
                '<li IfModActive="test.pack">Optional</li>'
                '<li IfModActiveAll="test.pack,other.mod">Both</li>'
                "</v1.7></loadFolders>",
                encoding="utf-8",
            )
            config = Path(td) / "ModsConfig.xml"
            config.write_text("<ModsConfigData><activeMods><li>test.pack</li></activeMods></ModsConfigData>", encoding="utf-8")
            os.environ["RWFORGE_MODS_CONFIG"] = str(config)
            try:
                index = Path(td) / "i.json"
                build_index(root, include_mods=root / "Mods", output=index, active_version="1.7")
                names = {r["def_name"] for r in json.loads(index.read_text(encoding="utf-8"))["records"]}
                self.assertIn("Test_Optional", names)
                self.assertNotIn("Test_Both", names)
            finally:
                os.environ.pop("RWFORGE_MODS_CONFIG", None)

    def test_loadfolders_unresolved_conditions_are_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = _fake_game(Path(td) / "RimWorld", "1.7.2600")
            mod = root / "Mods" / "Conditional"
            (mod / "1.7" / "Defs").mkdir(parents=True)
            (mod / "1.7" / "Defs" / "D.xml").write_text("<Defs><ThingDef><defName>Test_17</defName></ThingDef></Defs>", encoding="utf-8")
            (mod / "Optional" / "Defs").mkdir(parents=True)
            (mod / "Optional" / "Defs" / "O.xml").write_text("<Defs><ThingDef><defName>Test_Optional</defName></ThingDef></Defs>", encoding="utf-8")
            (mod / "LoadFolders.xml").write_text(
                '<loadFolders><v1.7><li>1.7</li><li IfModActive="test.pack">Optional</li></v1.7></loadFolders>',
                encoding="utf-8",
            )
            os.environ["RWFORGE_MODS_CONFIG"] = str(Path(td) / "missing.xml")
            try:
                index = Path(td) / "i.json"
                result = build_index(root, include_mods=root / "Mods", output=index, active_version="1.7")
                data = json.loads(index.read_text(encoding="utf-8"))
                names = {r["def_name"] for r in data["records"]}
                self.assertIn("Test_Optional", names)
                self.assertTrue(any(w["code"] == "loadfolders.conditions_unresolved" for w in data["warnings"]))
            finally:
                os.environ.pop("RWFORGE_MODS_CONFIG", None)

    def test_loadfolder_collision_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = _fake_game(Path(td) / "RimWorld", "1.7.2600")
            mod = root / "Mods" / "Collision"
            for sub in ("Defs", "1.7/Defs"):
                d = mod / sub
                d.mkdir(parents=True)
                (d / "Same.xml").write_text("<Defs><ThingDef><defName>Test_Same</defName></ThingDef></Defs>", encoding="utf-8")
            (mod / "LoadFolders.xml").write_text("<loadFolders><v1.7><li>/</li><li>1.7</li></v1.7></loadFolders>", encoding="utf-8")
            index = Path(td) / "i.json"
            build_index(root, include_mods=root / "Mods", output=index, active_version="1.7")
            data = json.loads(index.read_text(encoding="utf-8"))
            self.assertTrue(any(w["code"] == "loadfolder.collision" for w in data["warnings"]))

    def test_inspect_reports_parent_chain(self):
        with tempfile.TemporaryDirectory() as td:
            root = _fake_game(Path(td) / "RimWorld", "1.6.4850")
            defs = root / "Data" / "Core" / "Defs"
            (defs / "Base.xml").write_text(
                '<Defs><ThingDef Name="BaseThing" Abstract="True"><defName>BaseThing</defName><statBases><MarketValue>10</MarketValue></statBases></ThingDef>'
                '<ThingDef ParentName="BaseThing"><defName>ChildThing</defName></ThingDef></Defs>',
                encoding="utf-8",
            )
            index = Path(td) / "i.json"
            build_index(root, output=index)
            record = inspect_def("ChildThing", index)
            self.assertEqual(record["parent_chain"][0]["name"], "BaseThing")
            self.assertTrue(record["parent_chain"][0]["abstract"])

    def test_log_demangles_harmony_wrapper_and_phase(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "Player.log"
            log.write_text(
                "(wrapper dynamic-method) MonoMod.Utils.DynamicMethodDefinition:Verse.LoadedModManager.ParseAndProcessXML_Patch7\n"
                'Verse.PatchOperationReplace(xpath="Defs/ThingDef[defName=\\"Nope\\"]/statBases"): Failed to find a node with the given xpath\n',
                encoding="utf-8",
            )
            result = analyze_log(log)
            self.assertGreaterEqual(result["phases"].get("xpath_patching", 0), 1)
            self.assertTrue(any("Verse.LoadedModManager.ParseAndProcessXML" in (h.get("harmony_methods") or []) for h in result["hits"]))

    def test_log_reads_harmony_log_beside_player(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "Player.log"
            log.write_text("clean\n", encoding="utf-8")
            harmony = Path(td) / "harmony.log.txt"
            harmony.write_text("Harmony patch failed: Patching exception in Some.Mod.Prefix\n", encoding="utf-8")
            result = analyze_log(log)
            self.assertEqual(Path(result["harmony_log"]), harmony)
            self.assertTrue(any(h["source"] == "harmony.log.txt" for h in result["hits"]))

    def test_log_redaction(self):
        text = r"at C:\Users\alice\AppData\Local\RimWorld (steam 76561198000000000) 192.168.1.5 alice@example.com"
        redacted = redact_text(text)
        self.assertIn("%USERPROFILE%", redacted)
        self.assertIn("<steamid>", redacted)
        self.assertIn("<ip>", redacted)
        self.assertIn("<email>", redacted)
        self.assertNotIn("alice@example.com", redacted)

    def test_stage_backup_manifest_and_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            game = _fake_game(Path(td) / "RimWorld", "1.6.4850")
            ws = Path(td) / "Demo"
            new_project("Demo Mod", "tester.demo", workspace=ws)
            plan = {"schema": 1, "mod": {"name": "Demo Mod", "packageId": "tester.demo", "supportedVersions": ["1.6"]},
                    "defs": [{"type": "ThingDef", "fields": {"defName": "Tester_DemoThing"}}]}
            plan_path = ws / "plans" / "p.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            apply_plan(ws, plan_path)
            build_project(ws)
            target = game / "Mods" / "Demo-Mod"
            target.mkdir(parents=True)
            (target / "user-notes.txt").write_text("keep me", encoding="utf-8")
            staged = stage_project(ws, game, approve=True)
            self.assertTrue(staged["ok"])
            self.assertIsNotNone(staged["backup"])
            self.assertTrue((Path(staged["backup"]) / "user-notes.txt").is_file())
            self.assertTrue((target / ".rwforge-manifest.json").is_file())
            self.assertTrue(any(c["path"] == "user-notes.txt" for c in staged["unowned_conflicts"]))
            rollback_stage(ws, game)
            self.assertTrue((target / "user-notes.txt").is_file())

    def test_csharp_scaffold_targets_17(self):
        with tempfile.TemporaryDirectory() as td:
            game = _fake_game(Path(td) / "RimWorld", "1.7.2600")
            ws = Path(td) / "Code"
            new_project("Code Mod", "tester.code", workspace=ws, versions=["1.7"])
            result = csharp_scaffold(ws, game, target_version="1.7")
            csproj = Path(result["project"]) / f"{result['assembly']}.csproj"
            text = csproj.read_text(encoding="utf-8")
            self.assertIn("net10.0", text)
            self.assertIn("Waylith.dll", text)
            self.assertNotIn("UnityEngine.CoreModule", text)
            self.assertTrue(result["assemblies_dir"].replace("\\", "/").endswith("source/1.7/Assemblies"))
            self.assertEqual(json.loads((ws / "forge.json").read_text(encoding="utf-8"))["targetRimWorld"], "1.7")

    def test_csharp_scaffold_16_keeps_net472(self):
        with tempfile.TemporaryDirectory() as td:
            game = _fake_game(Path(td) / "RimWorld", "1.6.4850")
            ws = Path(td) / "Code"
            new_project("Code Mod", "tester.code", workspace=ws)
            result = csharp_scaffold(ws, game, target_version="1.6")
            text = (Path(result["project"]) / f"{result['assembly']}.csproj").read_text(encoding="utf-8")
            self.assertIn("net472", text)
            self.assertIn("UnityEngine.CoreModule", text)

    def test_about_accepts_17_only(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "Demo"
            new_project("Demo Mod", "tester.demo", workspace=ws, versions=["1.7"])
            result = validate_workspace(ws)
            self.assertTrue(result["ok"], result)
            self.assertFalse(any(w["code"] == "about.version" for w in result["warnings"]))

    def test_plan_accepts_17_only(self):
        plan = {"schema": 1, "mod": {"name": "X", "packageId": "a.b", "supportedVersions": ["1.7"]}, "defs": []}
        self.assertTrue(validate_plan(plan)["ok"])

    def test_loadfolders_validator_flags_missing_folder(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "Demo"
            new_project("Demo Mod", "tester.demo", workspace=ws, versions=["1.7"])
            (ws / "source" / "LoadFolders.xml").write_text(
                "<loadFolders><v1.7><li>MissingFolder</li></v1.7></loadFolders>", encoding="utf-8"
            )
            result = validate_workspace(ws)
            self.assertTrue(any(w["code"] == "loadfolders.missing" for w in result["warnings"]))




class ProceduralArtTests(unittest.TestCase):
    @unittest.skipUnless(HAS_PIL, "Pillow is not installed")
    def test_demo_generates_art_validates_and_builds(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "ForgeDemo"
            result = run_demo(out)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["validation"]["warnings"], [])
            self.assertEqual(result["assets"]["generated"], 7)
            preview = out / "source" / "About" / "Preview.png"
            self.assertTrue(preview.is_file())
            self.assertGreater(preview.stat().st_size, 5000)
            for name in ("Workbench.png", "Tool.png", "Pawn_south.png", "Pawn_north.png", "Pawn_east.png", "Pawn_west.png"):
                self.assertTrue((out / "source" / "Textures" / "ForgeDemo" / name).is_file(), name)
            with zipfile.ZipFile(result["archive"]) as zf:
                names = zf.namelist()
                self.assertTrue(any(name.endswith("About/Preview.png") for name in names))
                self.assertTrue(any(name.endswith("Textures/ForgeDemo/Workbench.png") for name in names))

    @unittest.skipUnless(HAS_PIL, "Pillow is not installed")
    def test_procedural_generation_is_deterministic(self):
        from rwforge.artgen import generate_assets
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "Art"
            new_project("Art Mod", "tester.art", workspace=ws)
            manifest = {"schema": 1, "assets": [{
                "id": "bench", "kind": "building", "target": "Textures/Test/Bench.png",
                "canvas": [64, 64], "transparent": True,
            }]}
            (ws / "plans" / "ASSETS-NEEDED.json").write_text(json.dumps(manifest), encoding="utf-8")
            generate_assets(ws, force=True, seed="fixed")
            first = hashlib.sha256((ws / "source" / "Textures/Test/Bench.png").read_bytes()).hexdigest()
            generate_assets(ws, force=True, seed="fixed")
            second = hashlib.sha256((ws / "source" / "Textures/Test/Bench.png").read_bytes()).hexdigest()
            self.assertEqual(first, second)

    @unittest.skipUnless(HAS_PIL, "Pillow is not installed")
    def test_pawn_directional_outputs_four_files_and_skips_existing(self):
        from rwforge.artgen import generate_assets
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "Art"
            new_project("Art Mod", "tester.art", workspace=ws)
            manifest = {"schema": 1, "assets": [{
                "id": "pawn", "kind": "pawn_directional", "target": "Textures/Test/Pawn.png",
                "canvas": [64, 64], "transparent": True,
                "directions": ["south", "north", "east", "west"],
            }]}
            (ws / "plans" / "ASSETS-NEEDED.json").write_text(json.dumps(manifest), encoding="utf-8")
            first = generate_assets(ws, seed="fixed")
            self.assertEqual(first["generated"], 4)
            for direction in ("south", "north", "east", "west"):
                self.assertTrue((ws / "source" / "Textures/Test" / f"Pawn_{direction}.png").is_file())
            second = generate_assets(ws, seed="fixed")
            self.assertEqual(second["generated"], 0)
            self.assertEqual(second["skipped"], 4)


if __name__ == "__main__":
    unittest.main()
