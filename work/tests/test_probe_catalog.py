"""PROBES.md -- the catalogue of the tracked Frida scripts, and its safety classification.

A reader has to be able to tell a read-only observer from a script that WRITES to the game
process (the runtime prototypes: stale cave offsets crash the game). The classification is
mechanical and the catalogue is generated, so this pins that it is current and complete.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import gen_probe_catalog as gc   # noqa: E402


def test_the_catalogue_is_current():
    have = gc.CATALOG.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert have == gc.build(), "PROBES.md is out of date: run work\\scripts\\gen_probe_catalog.py"


def test_every_tracked_script_is_listed_exactly_once():
    text = gc.CATALOG.read_text(encoding="utf-8")
    names = gc.tracked_js()
    assert names, "no tracked .js found"
    for n in names:
        assert text.count(f"| `{n}` |") == 1, n


def test_classification_is_by_what_the_script_does():
    assert gc.classify("hook_x.js", "Interceptor.attach(p, { onEnter(a) { log(a[0].readU32()); } });") \
        == "observer"
    for src in ("ptr(0x5D4EF0).writeU8(0x90);", "p.writeByteArray([1, 2]);", "cell.writeS32(g);",
                "Interceptor.replace(fn, new NativeCallback(f, 'void', []));",
                "Memory.patchCode(p, 5, c => { new X86Writer(c); });", "q.writePointer(z);"):
        assert gc.classify("hook_x.js", src) == "writer", src
    assert gc.classify("scaling_laws.js", "x.writeU8(1)") == "shared"


def test_the_description_is_the_scripts_own_first_sentence():
    assert gc.describe('"use strict";\n// FIELD-RECT OBSERVER (2026-07-09). OBSERVE-ONLY: no '
                       'replace.\n//\n// PURPOSE. more\n') \
        == "FIELD-RECT OBSERVER (2026-07-09). OBSERVE-ONLY: no replace."
    assert gc.describe("// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to\n"
                       "// the game process.\n\n'use strict';\n// Council screen scaling "
                       "prototype.\n") == "Council screen scaling prototype."
    assert gc.describe("const x = 1;\n") == ""
    assert "|" not in gc.describe("// a | b.\n")


def test_every_writer_that_is_a_prototype_carries_the_warning():
    """A reader who opens the file, not the catalogue, must still be told."""
    missing = []
    for n in gc.tracked_js():
        text = (_SCRIPTS / n).read_text(encoding="utf-8", errors="replace")
        if gc.classify(n, text) == "writer" and "proto" in n.lower():
            # the exact banner: "runs on the BAKED build" in a header means the opposite
            if "historical prototype" not in text[:600].lower():
                missing.append(n)
    assert not missing, f"prototype writers without the HISTORICAL PROTOTYPE banner: {missing}"


def test_scratch_and_pre_scripts_are_not_offered_as_observers():
    text = gc.CATALOG.read_text(encoding="utf-8")
    assert "| `_" not in text, "`_`-prefixed scratch is never part of the source release"
    observers = text.split("## Observers")[1].split("## Writers")[0]
    assert "aivis_mode_filter.js" not in observers, "it arms the WRITING mode of a prototype"
    assert "aivis_mode_filter.js" in text.split("## Observers")[0]
