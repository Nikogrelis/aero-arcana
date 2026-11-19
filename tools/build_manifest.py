"""Build pack/index.json — the file list the Aero Arcana launcher syncs before every start.

Sources:
  * pack-src/lock.json        Modrinth mods (url + sha512), client-side ones only;
  * pack-src/mods.json local   CurseForge files (direct CDN links) and our own/patched jars (GitHub release);
  * pack/overrides/**          configs, quests, options (served raw from this repo).
Every jar is taken from the reference client archive and hashed, so the manifest is exactly what was tested.

Usage: python -I tools/build_manifest.py <reference client zip>
"""
import datetime, hashlib, json, pathlib, re, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "pack-src"
REPO = "Nikogrelis/aero-arcana"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/pack/overrides/"
REL = f"https://github.com/{REPO}/releases/download/files/"

# CurseForge files: file id -> direct CDN url (the launcher downloads from CurseForge itself)
CF = {
    "ftb-quests-neoforge-2101.1.39.jar": 9650792,
    "ftb-library-neoforge-2101.1.40.jar": 9650381,
    "ftb-teams-neoforge-2101.1.12.jar": 9434081,
    "ftb-filter-system-neoforge-21.1.4.jar": 7429011,
    "loconautics-0.1.3BETA.jar": 9627028,
}
SERVER_ONLY = {"aero_creeper_guard-1.0.0.jar"}
DROP = {"automodpack-mc1.21.1-neoforge-4.0.7.jar"}  # replaced by this launcher

# Configs the pack owns: always overwritten (gameplay must match the server / our fixes).
FORCE_PREFIX = ("config/ftbquests/", "config/coldsweat/world.toml", "config/coldsweat/main.toml",
                "config/coldsweat/entity.toml", "config/coldsweat/item.toml",
                "config/aeronauticswinds-common.toml", "config/unraveling_spells-common.toml",
                "config/inventoryprofilesnext/integrationHints/")
# Personal preferences: written once, never touched again.
ONCE = ("options.txt", "config/iris.properties", "config/coldsweat/client.toml", "config/jei/",
        "config/voicechat/", "config/sodium-options.json", "config/inventoryprofilesnext/inventoryprofiles.json")


def cf_url(fid, name):
    return f"https://mediafilez.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{name}"


def policy(rel):
    if rel.startswith(FORCE_PREFIX):
        return "force"
    if rel.startswith(ONCE):
        return "once"
    return "keep-modified"   # updated unless the player changed the file


def main(ref_zip):
    z = zipfile.ZipFile(ref_zip)
    jars = {n.rsplit("/", 1)[1]: n for n in z.namelist() if n.startswith("versions/Aero-Arcana/mods/") and n.endswith(".jar")}
    lock = {e["file"]: e for e in json.load(open(SRC / "lock.json", encoding="utf-8"))}
    files, own, problems = [], [], []
    LOCAL_OWN = SRC / "local"   # own/patched jars: the current build, not the copy in the reference zip
    for name, entry in sorted(jars.items()):
        if name in DROP or name in SERVER_ONLY:
            continue
        own_file = LOCAL_OWN / name
        data = own_file.read_bytes() if own_file.exists() and name not in lock and name not in CF else z.read(entry)
        sha1, size = hashlib.sha1(data).hexdigest(), len(data)
        if name in lock:
            e = lock[name]
            if hashlib.sha512(data).hexdigest() != e["sha512"]:
                problems.append(f"sha512 mismatch for {name}")
            url = e["url"]
        elif name in CF:
            url = cf_url(CF[name], name)
        else:
            url = REL + name
            own.append(name)
        files.append({"path": f"mods/{name}", "url": url, "sha1": sha1, "size": size, "kind": "mod", "policy": "force"})
    ov = ROOT / "pack" / "overrides"
    for f in sorted(p for p in ov.rglob("*") if p.is_file()):
        rel = f.relative_to(ov).as_posix()
        data = f.read_bytes()
        files.append({"path": rel, "url": RAW + rel.replace(" ", "%20"), "sha1": hashlib.sha1(data).hexdigest(),
                      "size": len(data), "kind": "config", "policy": policy(rel)})
    index = {
        "formatVersion": 1,
        "name": "Aero Arcana",
        "version": datetime.datetime.now().strftime("%Y.%m.%d-%H%M"),
        "minecraft": "1.21.1",
        "neoforge": "21.1.266",
        "server": {"name": "Aero Arcana", "host": "51.75.74.159", "port": 25501},
        "files": files,
        "fixes": json.loads((ROOT / "pack" / "fixes.json").read_text(encoding="utf-8")),
    }
    exe = ROOT / "launcher" / "dist" / "AeroArcana.exe"
    ver = re.search(r'LAUNCHER_VERSION = "([^"]+)"', (ROOT / "launcher" / "aero" / "core.py").read_text(encoding="utf-8")).group(1)
    if exe.exists():
        index["launcher"] = {"version": ver, "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                             "url": f"https://github.com/{REPO}/releases/download/v{ver}/AeroArcana.exe"}
    (ROOT / "pack" / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(files)} files ({sum(f['kind'] == 'mod' for f in files)} mods), version {index['version']}")
    print("release assets needed:", own)
    if problems:
        print("PROBLEMS:", *problems, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
