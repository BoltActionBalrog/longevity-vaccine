"""Assembler SOURCES reproduce the SHIPPED bytes (patches.yaml), so a regenerate can never revert them.

A thunk or site that a later bake took over keeps living in its first assembler, and nothing in that source says
"no longer mine": re-running it (or refreshing patches.yaml from its fragments) silently puts the old bytes back
(feedback-fragment-refresh-reverts-foreign-entries).  The parity tests cannot see this -- they emulate each
script's own layout.  This module pins, by RESOLVED bytes (placeholders resolved with the real symbol table):

  * assemble_devfill_stripes.py  thunk_fe_pair_remap v7 + thunk_box_thick_devfill (STEP3 -> thunk_s54_restripe)
  * assemble_popup_sb.py         thunk_btn_stripes v12
  * assemble_council.py          every SITES entry (vote chips -> t_si_chip, flag site -> thunk_art_core)
  * assemble_dw.py / assemble_dl.py   every site_list() entry (wheel head t_dw_wheel_*, t_cav_blit, t_dl_tile_ph)
  * assemble_diplo.py            every REDIRECTS entry (t_cr_tile_exit, the popup_art_reblit takeovers), and its
                                 WHOLE emit (fragment_texts): == the committed _fragment_diplo_*.yaml text, and every
                                 symbol / cave content / site / the group == the shipped patches.yaml entry (unresolved
                                 templates, exact tokens), the marker blocks hold nothing else, the splice-time
                                 repoints + thunk_btn_gate prefix are in place (test_diplo_emit_*)
  * the committed _fragment_{council,dw,diplo,dl,se}_*.yaml files, entry by entry
and that the two retired assemblers (assemble_fe_pair_remap.py, assemble_btn_stripes.py) refuse to run.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import subprocess
import sys
import textwrap

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PATCHES = ROOT / "patches"
sys.path.insert(0, str(SCRIPTS))

import apply_patches as ap  # noqa: E402

pytest.importorskip("keystone", reason="keystone absent")
pytest.importorskip("capstone", reason="capstone absent")


def _num(v):
    return int(v, 16) if isinstance(v, str) else v


@pytest.fixture(scope="module")
def live():
    doc = ap._yaml_load((PATCHES / "patches.yaml").read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    contents = {}
    for cave in doc["code_caves"]:
        base = _num(cave["virtual_addr"])
        for c in cave.get("contents", []) or []:
            contents[c["id"]] = (base + _num(c["offset"]), c)
    sites = {s["id"]: s for s in doc["sites"]}

    class Live:
        pass
    L = Live()
    L.doc, L.symtab, L.contents, L.sites = doc, symtab, contents, sites
    L.resolve = lambda tpl, va: ap.ByteTemplate(str(tpl)).resolve(va, symtab)

    def content(name):
        assert name in contents, f"{name} has no contents entry in patches.yaml"
        va, c = contents[name]
        return va, L.resolve(c["bytes"], va)

    def site(sid):
        assert sid in sites, f"site {sid} not in patches.yaml"
        s = sites[sid]
        return _num(s["virtual_addr"]), L.resolve(s["new_bytes"], _num(s["virtual_addr"]))
    L.content, L.site = content, site
    return L


def _quiet_import(name):
    with contextlib.redirect_stdout(io.StringIO()):
        return __import__(name)


# ---- thunks --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["thunk_fe_pair_remap", "thunk_box_thick_devfill"])
def test_devfill_stripes_reproduces_the_shipped_thunk(live, name):
    D = _quiet_import("assemble_devfill_stripes")
    off, tpl, _n = D.template(name)
    va, want = live.content(name)
    assert va == D.PCAVE2 + off, f"{name}: source offset {off:#x} != shipped {va - D.PCAVE2:#x}"
    assert live.resolve(tpl, va) == want, f"{name}: assemble_devfill_stripes.py no longer reproduces the shipped bytes"


def test_devfill_step3_calls_the_s54_restripe_wrapper():
    D = _quiet_import("assemble_devfill_stripes")
    _off, tpl, _n = D.template("thunk_box_thick_devfill")
    assert "{rel32:thunk_s54_restripe}" in tpl and "{rel32:thunk_fe_pair_remap}" not in tpl


def test_popup_sb_reproduces_the_shipped_btn_stripes(live):
    P = _quiet_import("assemble_popup_sb")
    va = P.PCAVE2 + P.STRIPES_OFF
    tpl = P.to_template(P.assemble(P.asm_btn_stripes(), va), va)
    lva, want = live.content("thunk_btn_stripes")
    assert lva == va and live.resolve(tpl, va) == want


@pytest.mark.parametrize("script, owner", [("assemble_fe_pair_remap.py", "assemble_devfill_stripes.py"),
                                           ("assemble_btn_stripes.py", "assemble_popup_sb.py")])
def test_retired_assemblers_refuse_to_run(script, owner):
    r = subprocess.run([sys.executable, str(SCRIPTS / script)], capture_output=True, text=True, timeout=60,
                       cwd=str(SCRIPTS))
    assert r.returncode != 0, f"{script} ran: it emits retired bytes"
    assert "SUPERSEDED" in r.stderr and owner in r.stderr


# ---- sites ---------------------------------------------------------------------------------------------------------

def test_council_sites_are_the_shipped_sites(live):
    AC = _quiet_import("assemble_council")
    for sid, _fn, va, _tgt, thunk, _note in AC.SITES:
        lva, want = live.site(sid)
        assert lva == va, sid
        assert live.resolve(f"E8 {{rel32:{thunk}}}", va) == want, f"{sid}: source sends it to {thunk}"


@pytest.mark.parametrize("module", ["assemble_dw", "assemble_dl"])
def test_site_list_is_the_shipped_sites(live, module):
    M = _quiet_import(module)
    if module == "assemble_dl":
        _layout, _end, names = M.assemble_all()
        sites = M.site_list(names)
    else:
        sites = M.site_list()
    for s in sites:
        lva, want = live.site(s["id"])
        assert lva == s["va"], s["id"]
        assert live.resolve(s["new"], s["va"]) == want, f"{module}: {s['id']} new bytes {s['new']!r} are not the shipped ones"


def test_diplo_redirects_are_the_shipped_sites(live):
    DP = _quiet_import("assemble_diplo")
    for sid, va, thunk in DP.REDIRECTS:
        thunk = DP.TAKEN_OVER.get(sid, (thunk, ""))[0]
        lva, want = live.site(sid)
        assert lva == va, sid
        assert live.resolve(f"E8 {{rel32:{thunk}}}", va) == want, f"{sid}: source sends it to {thunk}"


# ---- committed fragments -------------------------------------------------------------------------------------------

FRAGMENTS = sorted(p.name for fam in ("council", "dw", "diplo", "dl", "se")
                   for p in PATCHES.glob(f"_fragment_{fam}_*.yaml")
                   if p.stem.rsplit("_", 1)[-1] in ("sites", "cave", "symbols", "inplace"))


def test_fragment_families_present():
    for fam in ("council", "dw", "diplo", "dl", "se"):
        assert f"_fragment_{fam}_sites.yaml" in FRAGMENTS


@pytest.mark.parametrize("frag", FRAGMENTS)
def test_fragment_agrees_with_patches_yaml(live, frag):
    data = yaml.safe_load(textwrap.dedent((PATCHES / frag).read_text(encoding="utf-8")))
    bad = []
    if isinstance(data, dict):                       # symbols
        for k, v in data.items():
            if live.doc["symbols"].get(k) != v:
                bad.append(f"symbol {k}: {v} vs shipped {live.doc['symbols'].get(k)}")
    else:
        for e in data:
            i = e["id"]
            if "virtual_addr" in e:                  # site
                va = _num(e["virtual_addr"])
                lva, want = live.site(i)
                s = live.sites[i]
                if va != lva or live.resolve(e["new_bytes"], va) != want:
                    bad.append(f"site {i}: {e['new_bytes']} vs shipped {s['new_bytes']}")
                if str(e["original_bytes"]).split() != str(s["original_bytes"]).split():
                    bad.append(f"site {i}: original_bytes differ")
                for k in ("group", "length", "pattern"):
                    if e.get(k) != s.get(k):
                        bad.append(f"site {i}: {k} {e.get(k)} vs {s.get(k)}")
            else:                                    # cave content
                assert i in live.contents, f"{frag}: {i} not in patches.yaml"
                lva, c = live.contents[i]
                if _num(e["offset"]) != _num(c["offset"]):
                    bad.append(f"content {i}: offset {e['offset']} vs shipped {c['offset']}")
                elif live.resolve(e["bytes"], lva) != live.content(i)[1]:
                    bad.append(f"content {i}: bytes differ")
    assert not bad, f"{frag} would revert shipped entries on a refresh:\n  " + "\n  ".join(bad)


# ---- assemble_diplo.py: the whole emit == the committed fragments == the shipped patches.yaml ----------------------
# The patcher consumes patches.yaml only; the fragments are the assembler's intermediate output.  The emit is computed
# IN-PROCESS (build_fragments + fragment_texts): nothing here writes a fragment or patches.yaml.


@pytest.fixture(scope="module")
def diplo_emit():
    DP = _quiet_import("assemble_diplo")
    with contextlib.redirect_stdout(io.StringIO()):
        _layout, _end, sym, ce, sites, group = DP.build_fragments()
    return DP, DP.fragment_texts(sym, ce, sites, group)


def _diplo_blocks(DP, text: str) -> dict:
    import re
    out = {}
    for sect in ("symbols", "cave", "groups", "sites"):
        m = re.search(rf"^{re.escape(DP.MARK_B)} {sect}\n(.*?)\n{re.escape(DP.MARK_E)} {sect}\n", text, re.S | re.M)
        assert m, f"diplo_talk_scale {sect} block missing from patches.yaml"
        out[sect] = m.group(1)
    return out


def _block_ids(sect: str, body: str) -> set:
    import re
    return set(re.findall(r"^  ([A-Za-z_]\w*):" if sect == "symbols" else r"^ *- id: (\S+)", body, re.M))


def _diplo_emit_mismatches(DP, texts: dict, doc: dict, blocks: dict) -> list:
    """Every way the emit differs from the parsed patches.yaml `doc` (+ its raw diplo marker `blocks`)."""
    load = lambda fn: yaml.safe_load(textwrap.dedent(texts[fn]))  # noqa: E731
    sym, ce = load("_fragment_diplo_symbols.yaml"), load("_fragment_diplo_cave.yaml")
    sites, group = load("_fragment_diplo_sites.yaml"), load("_fragment_diplo_group.yaml")
    tok = lambda v: str(v).split()  # noqa: E731
    bad = []
    for k, v in sym.items():
        if doc["symbols"].get(k) != v:
            bad.append(f"symbol {k}: emit {v} vs shipped {doc['symbols'].get(k)}")
    shipped_ce = {c["id"]: c for cave in doc["code_caves"] if cave["id"] == "pcave2" for c in cave.get("contents") or []}
    for e in ce:
        c = shipped_ce.get(e["id"])
        if c is None:
            bad.append(f"content {e['id']}: not in pcave2")
        elif _num(e["offset"]) != _num(c["offset"]) or tok(e["bytes"]) != tok(c["bytes"]):
            bad.append(f"content {e['id']}: emit @{_num(e['offset']):#x} differs from shipped @{_num(c['offset']):#x}")
    shipped_sites = {s["id"]: s for s in doc["sites"]}
    for e in sites:
        s = shipped_sites.get(e["id"])
        if s is None:
            bad.append(f"site {e['id']}: not in patches.yaml")
            continue
        for k in ("status", "group", "function", "length", "pattern"):
            if e.get(k) != s.get(k):
                bad.append(f"site {e['id']}: {k} emit {e.get(k)} vs shipped {s.get(k)}")
        if _num(e["virtual_addr"]) != _num(s["virtual_addr"]):
            bad.append(f"site {e['id']}: virtual_addr")
        for k in ("original_bytes", "new_bytes"):
            if tok(e[k]) != tok(s[k]):
                bad.append(f"site {e['id']}: {k} emit {e[k]!r} vs shipped {s[k]!r}")
    (g,) = group
    sg = next((x for x in doc["groups"] if x["id"] == g["id"]), None)
    if sg != g:
        bad.append(f"group {g['id']}: emit differs from shipped")
    emitted = {"symbols": set(sym), "cave": {e["id"] for e in ce}, "groups": {g["id"]}, "sites": {e["id"] for e in sites}}
    for sect, body in blocks.items():
        extra = _block_ids(sect, body) - emitted[sect]      # a foreign entry inside the block: a --splice would delete it
        missing = emitted[sect] - _block_ids(sect, body)
        if extra or missing:
            bad.append(f"{sect} block: not emitted {sorted(extra)}, emitted but outside the block {sorted(missing)}")
    by_va = {_num(s["virtual_addr"]): s for s in doc["sites"]}
    content = {c["id"]: c for cave in doc["code_caves"] for c in cave.get("contents") or []}
    for va, (_old, new) in DP.EXISTING_REPOINTS.items():
        val = str(by_va[va]["new_bytes"]) if va in by_va else ""
        took = DP.REPOINT_TAKEN_OVER.get(va)
        if took and took in val:             # a later bake's wrapper owns the site: it must still reach our target
            wrapper = content.get(took.split(":", 1)[1].rstrip("}"))
            if wrapper is None or new not in str(wrapper["bytes"]):
                bad.append(f"repoint {va:#x}: taken over by {took}, which no longer reaches {new}")
        elif new not in val:
            bad.append(f"repoint {va:#x}: {new} not in the shipped new_bytes")
    gate = content.get("thunk_btn_gate")
    if gate is None or not tok(gate["bytes"])[:len(DP.btn_gate_prefix())] == tok(DP.to_tokens(DP.btn_gate_prefix())):
        bad.append("thunk_btn_gate: the diplo v8 prefix is not at its head")
    return bad


def test_diplo_emit_is_the_committed_fragments(diplo_emit):
    """assemble_diplo.py's four fragments, as text (each file keeps its own EOL), are exactly its emit."""
    DP, texts = diplo_emit
    for fn, body in texts.items():
        disk = (PATCHES / fn).read_bytes().decode("utf-8").replace("\r\n", "\n")
        assert disk == body, f"{fn} is not what assemble_diplo.py emits (rerun it; it rewrites only changed files)"


def test_diplo_emit_is_the_shipped_patches_yaml(live, diplo_emit):
    DP, texts = diplo_emit
    blocks = _diplo_blocks(DP, (PATCHES / "patches.yaml").read_text(encoding="utf-8"))
    bad = _diplo_emit_mismatches(DP, texts, live.doc, blocks)
    assert not bad, "assemble_diplo.py's emit != the shipped patches.yaml:\n  " + "\n  ".join(bad)


def test_diplo_emit_check_kills_a_flipped_byte(live, diplo_emit):
    """Mutants: one token flipped in the emit's cave bytes / site new_bytes, or in the shipped thunk -- each is caught."""
    import copy
    import re
    DP, texts = diplo_emit
    blocks = _diplo_blocks(DP, (PATCHES / "patches.yaml").read_text(encoding="utf-8"))

    def flip_first(text, field):
        m = re.search(rf'{field}: +"([0-9A-F]{{2}})', text)
        b = f"{int(m.group(1), 16) ^ 0x01:02X}"
        return text[:m.start(1)] + b + text[m.end(1):]
    for fn, field, who in (("_fragment_diplo_cave.yaml", "bytes", "content"),
                           ("_fragment_diplo_sites.yaml", "new_bytes", "site")):
        mut = dict(texts, **{fn: flip_first(texts[fn], field)})
        bad = _diplo_emit_mismatches(DP, mut, live.doc, blocks)
        assert len(bad) == 1 and bad[0].startswith(who), (fn, bad)
    doc = dict(live.doc)
    doc["code_caves"] = copy.deepcopy(live.doc["code_caves"])
    c = next(c for cave in doc["code_caves"] if cave["id"] == "pcave2" for c in cave["contents"] if c["id"] == "t_dp_itemrect")
    t = str(c["bytes"]).split()
    t[-1] = f"{int(t[-1], 16) ^ 0x80:02X}"
    c["bytes"] = " ".join(t)
    bad = _diplo_emit_mismatches(DP, texts, doc, blocks)
    assert bad == ["content t_dp_itemrect: emit @0x45b0 differs from shipped @0x45b0"], bad


# ---- cross-file constants that hardcode a patches.yaml address -----------------------------------------------------

def _cave_va(live, cave_id):
    return _num(next(c for c in live.doc["code_caves"] if c["id"] == cave_id)["virtual_addr"])


def test_g_stripe_period_is_the_hardcoded_cell(live):
    """Asm ports read the stripe period as the literal `[0x66879c]` (fe_pair_remap, t_msg_icon, t_dl_restripe, ...)."""
    spec = live.doc["symbols"]["g_stripe_period"]
    assert spec["cave"] == "menu_strip_thunks" and _num(spec["offset"]) == 0x59C
    assert _cave_va(live, "menu_strip_thunks") + 0x59C == 0x66879C
    assert live.symtab["g_stripe_period"] == 0x66879C


def test_uimod_portrait_offsets_are_the_yaml_cave_offsets(live):
    """src/uimod/src/portrait.cpp patches the two re-blit entries at pcave2 + a compiled-in offset."""
    import re
    cpp = (ROOT.parent / "src" / "uimod" / "src" / "portrait.cpp").read_text(encoding="utf-8")
    pcave2 = _cave_va(live, "pcave2")
    for const, sym in (("kOffParityReblit", "thunk_parity_reblit"), ("kOffArtReblit", "thunk_art_reblit")):
        m = re.search(rf"constexpr\s+uintptr_t\s+{const}\s*=\s*(0x[0-9A-Fa-f]+)\s*;", cpp)
        assert m, f"{const} not found in portrait.cpp"
        spec = live.doc["symbols"][sym]
        assert spec["cave"] == "pcave2", sym
        assert int(m.group(1), 16) == _num(spec["offset"]) == live.symtab[sym] - pcave2, \
            f"portrait.cpp {const} = {m.group(1)} but patches.yaml puts {sym} at pcave2+{_num(spec['offset']):#x}"
