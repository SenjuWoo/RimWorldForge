"""Generate and build C# mod projects for RimWorld 1.6 and 1.7.

1.6 targets .NET Framework 4.7.2 and references the Unity assemblies. 1.7 runs on
.NET 10 and references Assembly-CSharp.dll, UnityStubs.dll and Waylith.dll
instead. A machine normally has one game version installed, so Forge scaffolds
for that version (or an explicit override) rather than pretending to
cross-compile both from one reference set.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .discovery import game_version_short, managed_dir
from .util import ensure_dir, read_json, safe_slug, sha256_file, write_json
from .versions import SUPPORTED_VERSIONS

CSPROJ_16 = r'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net472</TargetFramework>
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
    <AssemblyName>{assembly}</AssemblyName>
    <RootNamespace>{namespace}</RootNamespace>
    <GenerateAssemblyInfo>false</GenerateAssemblyInfo>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
    <Deterministic>true</Deterministic>
    <ContinuousIntegrationBuild>true</ContinuousIntegrationBuild>
    <DebugType>portable</DebugType>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="Assembly-CSharp"><HintPath>{managed}/Assembly-CSharp.dll</HintPath><Private>false</Private></Reference>
    <Reference Include="UnityEngine"><HintPath>{managed}/UnityEngine.dll</HintPath><Private>false</Private></Reference>
    <Reference Include="UnityEngine.CoreModule"><HintPath>{managed}/UnityEngine.CoreModule.dll</HintPath><Private>false</Private></Reference>
{harmony_ref}  </ItemGroup>
</Project>
'''

CSPROJ_17 = r'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
    <AssemblyName>{assembly}</AssemblyName>
    <RootNamespace>{namespace}</RootNamespace>
    <GenerateAssemblyInfo>false</GenerateAssemblyInfo>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
    <GenerateDependencyFile>false</GenerateDependencyFile>
    <Deterministic>true</Deterministic>
    <ContinuousIntegrationBuild>true</ContinuousIntegrationBuild>
    <DebugType>portable</DebugType>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="Assembly-CSharp"><HintPath>{managed}/Assembly-CSharp.dll</HintPath><Private>false</Private></Reference>
    <Reference Include="UnityStubs"><HintPath>{managed}/UnityStubs.dll</HintPath><Private>false</Private></Reference>
    <Reference Include="Waylith"><HintPath>{managed}/Waylith.dll</HintPath><Private>false</Private></Reference>
{harmony_ref}  </ItemGroup>
</Project>
'''

SOURCE = r'''using Verse;

namespace {namespace};

public sealed class {class_name}Mod : Mod
{{
    public {class_name}Mod(ModContentPack content) : base(content)
    {{
        Log.Message("[{assembly}] loaded");
    }}
}}
'''


def _target_version(workspace: Path, requested: str | None, game_root: Path) -> str:
    if requested:
        version = requested.strip()
    else:
        config = read_json(workspace / "forge.json") if (workspace / "forge.json").is_file() else {}
        version = str(config.get("targetRimWorld") or game_version_short(game_root) or "1.6")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported RimWorld version '{version}'. Use one of: {', '.join(SUPPORTED_VERSIONS)}")
    return version


def _assemblies_dir(workspace: Path, version: str) -> Path:
    # 1.7 keeps its assembly in a version folder so a mod can ship both builds.
    return workspace / "source" / (version if version == "1.7" else "") / "Assemblies"


def scaffold(
    workspace: Path,
    game_root: Path,
    namespace: str | None = None,
    harmony_dll: Path | None = None,
    target_version: str | None = None,
) -> dict[str, Any]:
    config = read_json(workspace / "forge.json")
    managed = managed_dir(game_root)
    if not managed:
        raise FileNotFoundError("RimWorld Managed directory was not found (Assembly-CSharp.dll missing)")
    version = _target_version(workspace, target_version, game_root)
    # Persist the override so a later `csharp-build` without --version writes the
    # DLL to the same version folder the csproj targets.
    if str(config.get("targetRimWorld") or "") != version:
        config["targetRimWorld"] = version
        write_json(workspace / "forge.json", config)
    required = ["Assembly-CSharp.dll", "UnityEngine.dll", "UnityEngine.CoreModule.dll"] if version == "1.6" else [
        "Assembly-CSharp.dll", "UnityStubs.dll", "Waylith.dll"
    ]
    missing = [name for name in required if not (managed / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"RimWorld {version} references are incomplete in {managed}: missing {', '.join(missing)}"
        )
    assembly = safe_slug(config.get("name", "RimWorldForgeMod")).replace("-", "")
    ns = namespace or f"RimWorldForge.{assembly}"
    class_name = "".join(ch for ch in assembly if ch.isalnum()) or "Generated"
    project = ensure_dir(workspace / "csharp" / assembly)
    href = ""
    if harmony_dll:
        href = f'    <Reference Include="0Harmony"><HintPath>{harmony_dll}</HintPath><Private>false</Private></Reference>\n'
    template = CSPROJ_16 if version == "1.6" else CSPROJ_17
    (project / f"{assembly}.csproj").write_text(
        template.format(assembly=assembly, namespace=ns, managed=str(managed), harmony_ref=href),
        encoding="utf-8",
    )
    (project / "Mod.cs").write_text(SOURCE.format(namespace=ns, class_name=class_name, assembly=assembly), encoding="utf-8")
    return {
        "ok": True,
        "project": str(project),
        "assembly": assembly,
        "namespace": ns,
        "target_version": version,
        "target_framework": "net472" if version == "1.6" else "net10.0",
        "assemblies_dir": str(_assemblies_dir(workspace, version)),
    }


def build(workspace: Path, approve: bool = False, target_version: str | None = None) -> dict[str, Any]:
    if not approve:
        return {"ok": False, "refused": True, "reason": "C# build executes an external compiler and requires --approve."}
    projects = sorted((workspace / "csharp").glob("*/*.csproj"))
    if not projects:
        raise FileNotFoundError("No C# project. Run `rwforge csharp-scaffold` first.")
    dotnet = shutil.which("dotnet")
    if not dotnet:
        return {"ok": False, "dependency": "dotnet", "reason": "dotnet was not found on PATH"}
    config = read_json(workspace / "forge.json") if (workspace / "forge.json").is_file() else {}
    version = target_version or str(config.get("targetRimWorld") or "1.6")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported RimWorld version '{version}'")
    results: list[dict[str, Any]] = []
    assemblies = ensure_dir(_assemblies_dir(workspace, version))
    all_ok = True
    for project in projects:
        command = [
            dotnet, "build", str(project), "-c", "Release", "--nologo",
            "-p:ContinuousIntegrationBuild=true",
            "-p:Deterministic=true",
            "-p:DebugType=portable",
            "-p:AppendTargetFrameworkToOutputPath=false",
        ]
        proc = subprocess.run(command, capture_output=True, text=True, shell=False)
        item: dict[str, Any] = {
            "project": str(project),
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-12000:],
        }
        if proc.returncode == 0:
            dlls = list((project.parent / "bin" / "Release").glob("*.dll"))
            if not dlls:
                # Some SDK/target combinations still add the TFM folder.
                dlls = list((project.parent / "bin" / "Release").rglob("*.dll"))
            copied = []
            for dll in dlls:
                if dll.name.lower().endswith(".resources.dll"):
                    continue
                target = assemblies / dll.name
                shutil.copy2(dll, target)
                copied.append({"path": str(target), "sha256": sha256_file(target)})
            item["copied"] = copied
            if not copied:
                all_ok = False
                item["error"] = "compiler returned success but produced no DLL"
        else:
            all_ok = False
        results.append(item)
    report = {"ok": all_ok, "target_version": version, "assemblies_dir": str(assemblies), "results": results}
    write_json(workspace / "reports" / "csharp-build.json", report)
    return report
