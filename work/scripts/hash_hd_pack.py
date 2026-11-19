"""Emit a provenance sidecar for a built HD Cinematics pack.

`build_hd_pack.py` produces 61 .mp4 files and nothing else -- no hashes, no sizes, and no record
of which upscale model or CRF produced which clip. That provenance lived only in `pipeline.ini`
plus the transient console log, so a shipped pack could not be reproduced or verified after the
fact, and every release had to re-hash 1.3 GB.

This runs AFTER the pack exists, so it needs no GPU and no rebuild:

    py work\\scripts\\hash_hd_pack.py                    # -> dist\\movies-hd\\pack-manifest.json
    py work\\scripts\\hash_hd_pack.py --verify           # re-check an existing sidecar

It is incremental: a clip whose size and mtime are unchanged keeps its recorded hash, so a
re-run after adding one clip costs one hash, not sixty-one.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent.parent
_DEFAULT_PACK = _REPO / "dist" / "movies-hd"
_PIPELINE = _REPO / "work" / "video-upscale" / "pipeline.ini"

SIDECAR_NAME = "pack-manifest.json"

#: The game's 61 cinematics, by the exact name of their movies\<name>.wve. A shipped pack carries exactly one
#: movies\hd\<name>.mp4 per name: the game looks clips up by these names, so a missing or misspelt one silently plays
#: the original instead (release.py's pack check refuses both).
MOVIE_CLIPS = (
    'angels', 'asceticVirtues', 'believe', 'bulkMatter', 'caretake', 'citizensDefense', 'clinical_Immortality',
    'cloningVats', 'close_ct', 'close_us', 'commandNexus', 'cyborg', 'cyborgFactory', 'dreamTwister', 'drone',
    'empathGuild', 'fungboy', 'gaians', 'hive', 'humanGenome', 'hunterSeeker', 'livingRefinery', 'logo',
    'longevityVaccine', 'losealien', 'loseman', 'losewoman', 'maritimeControl', 'merchantExchange', 'morgan',
    'nanofactory', 'networkBackbone', 'neuralAmplifier', 'open', 'opening', 'openingx', 'peace',
    'pholusMutagen', 'pirates', 'planetaryDatalinks', 'planetaryTransit', 'selfAwareColony',
    'singularityInductor', 'smacxcloudbase', 'smacxgrid', 'smacxmanifold', 'smacxnethack', 'spaceElevator',
    'spartans', 'supercollider', 'telepathicMatrix', 'theoryOfEverything', 'theyTranscend', 'transcend', 'univ',
    'universalTranslator', 'usurper', 'virtualWorld', 'voiceOfPlanet', 'weatherParadigm', 'xenoempathyDome',
)
_SETTINGS = ("model", "scale", "crf")


def sha256_file(p: Path, _buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(_buf), b""):
            h.update(chunk)
    return h.hexdigest()


def read_pipeline(path: Path = _PIPELINE) -> tuple[dict, dict]:
    """Return (defaults, per-clip overrides) from pipeline.ini.

    Resolution order matches build_hd_pack.py: [clip:<name>] then [pipeline].
    """
    if not path.is_file():
        return {}, {}
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    defaults = {k.lower(): v for k, v in cp["pipeline"].items()} if cp.has_section("pipeline") else {}
    overrides = {}
    for sec in cp.sections():
        if sec.startswith("clip:"):
            overrides[sec.split(":", 1)[1]] = {k.lower(): v for k, v in cp[sec].items()}
    return defaults, overrides


def settings_for(stem: str, defaults: dict, overrides: dict) -> dict:
    o = overrides.get(stem, {})
    return {
        "model": o.get("model", defaults.get("model")),
        "scale": o.get("scale", defaults.get("scale")),
        "crf": o.get("crf", defaults.get("crf")),
    }


def build(pack: Path, verify: bool = False) -> int:
    if not pack.is_dir():
        print(f"ERROR: pack directory not found: {pack}")
        return 2
    clips = sorted(p for p in pack.glob("*.mp4") if p.is_file())
    if not clips:
        print(f"ERROR: no .mp4 files in {pack}")
        return 2

    defaults, overrides = read_pipeline()
    if not defaults:
        print(f"WARNING: {_PIPELINE} not readable -- model/CRF provenance will be null.")

    sidecar = pack / SIDECAR_NAME
    previous, prev_defaults = {}, None
    if sidecar.is_file():
        try:
            prev_doc = json.loads(sidecar.read_text(encoding="utf-8"))
            previous = {c["name"]: c for c in prev_doc.get("clips", [])}
            prev_defaults = prev_doc.get("defaults")
        except (ValueError, KeyError, TypeError, AttributeError):
            print("  (existing sidecar unreadable -- rebuilding from scratch)")
            previous, prev_defaults = {}, None

    entries, hashed, reused, failures = [], 0, 0, []
    kept = 0       # clips whose recorded provenance was kept (same bytes as when it was recorded)
    for p in clips:
        st = p.stat()
        prev = previous.get(p.name)
        # Incremental: trust a recorded hash only when size AND mtime both match.
        if prev and not verify and prev.get("size") == st.st_size \
                and prev.get("mtime_ns") == st.st_mtime_ns and prev.get("sha256"):
            digest = prev["sha256"]
            reused += 1
        else:
            digest = sha256_file(p)
            hashed += 1
            if verify and prev and prev.get("sha256") and prev["sha256"] != digest:
                failures.append(p.name)
        # Provenance belongs to the BYTES: a clip unchanged since it was recorded keeps what was recorded for it.
        # pipeline.ini describes only clips our own Real-ESRGAN pipeline builds, so re-deriving every clip from it
        # (as release_all re-runs this) rewrote a third-party pack's provenance as Real-ESRGAN.
        if prev and prev.get("sha256") == digest and all(k in prev for k in _SETTINGS):
            settings = {k: prev[k] for k in _SETTINGS}
            kept += 1
        else:
            settings = settings_for(p.stem, defaults, overrides)
        entries.append({
            "name": p.name,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha256": digest,
            **settings,
        })

    if verify:
        missing = sorted(set(previous) - {e["name"] for e in entries})
        print(f"--- verify {pack} ---")
        print(f"  clips checked : {len(entries)}")
        print(f"  hash mismatch : {len(failures)}")
        for n in failures:
            print(f"      !! {n}")
        if missing:
            print(f"  recorded but now absent: {', '.join(missing)}")
        if failures or missing:
            return 1
        print("  OK -- every clip matches the sidecar.")
        return 0

    total = sum(e["size"] for e in entries)
    doc = {
        "schema": 1,
        "pack": "movies-hd",
        "clip_count": len(entries),
        "total_size": total,
        # Every clip kept its recorded provenance: so do the pack's defaults. Otherwise pipeline.ini's.
        "defaults": (prev_defaults if kept == len(entries) and isinstance(prev_defaults, dict)
                     else {"model": defaults.get("model"), "scale": defaults.get("scale"),
                           "crf": defaults.get("crf")}),
        "clips": entries,
    }
    sidecar.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    models = {}
    for e in entries:
        models[e["model"]] = models.get(e["model"], 0) + 1
    print(f"--- {sidecar} ---")
    print(f"  clips      : {len(entries)}  ({hashed} hashed, {reused} reused)")
    print(f"  total size : {total:,} bytes")
    for m, n in sorted(models.items(), key=lambda kv: -kv[1]):
        print(f"  model      : {m}  x{n}")
    return 0


def main() -> int:
    apr = argparse.ArgumentParser(description="Hash + record provenance for an HD pack.")
    apr.add_argument("--pack", default=str(_DEFAULT_PACK))
    apr.add_argument("--verify", action="store_true",
                     help="re-hash every clip and compare against the existing sidecar")
    args = apr.parse_args()
    return build(Path(args.pack), verify=args.verify)


if __name__ == "__main__":
    sys.exit(main())
