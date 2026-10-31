#!/usr/bin/env python
"""Load / Save file list: put the list's stripes on the dialog's row grid (2026-10-05).

The list is a child GraphicWin with its own canvas.  Its two stripe producers
  thunk_filedlg_rowbg_v6  (pcave2 0x2F00, redirect of FileDlg_draw_row's Buffer_tile @0x407327)
  thunk_copy4_stripes     (pcave2 0x2F50, redirect of the backdrop captures @0x60BBBA / 0x60C421)
must advance the stripe tile by the list's top row inside the PARENT canvas, or the list runs on its own grid and
a wrong-thickness band appears where it meets the frame.

Why the 2026-10-04 attempt read 0: it took the top from Win +0x140 (rRect1.top).  Win_init 0x5EBD80 does not
keep the position there for a window that has a client area ([+0x9C] bit 1, set when flags & 0x1D and not 0x80;
the list is created with the vertical-bar bit 8, flags 0x80028):
    0x5EC14C..0x5EC1C2   rRect1 = {x, y, x+w, y+h};  rRect2 = rRect1;  0x5EF050(rRect2)  (grow by the chrome);
                         rRect1.left/right -= rRect2.left;  rRect1.top/bottom -= rRect2.top
so rRect2 (+0x14C) holds the position in the parent and rRect1 (+0x13C) the client rect relative to it: with no
top chrome rRect1.top == 0 and rRect2.top == y.  A window without a client area keeps rRect1 = {x, y, ..} and
rRect2 = 0 (the Win ctor zeroes both, 0x5EB563..0x5EB58D).  The engine's own local -> parent mapping adds the two
(Win_flip_rect_2 0x5ECFE0: x += [+0x13C] + [+0x14C], y += [+0x140] + [+0x150]), and so does this fix:

    top = [Win +0x140] + [Win +0x150]        (canvas = Win +0x444  ->  [canvas - 0x304] + [canvas - 0x2F4])

For the list that is the y handed to GraphicWin_init @0x60A7AC, which is also Dialog +0x28, the srcY of the
vanilla backdrop capture (0x60BBA7 / 0x60C40E).

No explicit modulo: Buffer_tile 0x5DA860 reduces the source offset by the tile height itself
(0x5DA957: `mov eax,[srcOffY] / cdq / idiv tileH / sub destY, edx`), and thunk_ensure_stripes builds the tile
exactly g_stripe_period rows high -- so the offset is taken modulo the real period P, whatever P is.

Both replacements keep their slot, their gate and their native tail byte-identical.
  thunk_filedlg_rowbg_v6   72 -> 75 B  (slot 0x2F00..0x2F50)
  thunk_copy4_stripes      76 -> 79 B  (slot 0x2F50..0x2FA0)

`py assemble_stripes_fdphase.py`             prints the replacement templates and the diff against patches.yaml
`py assemble_stripes_fdphase.py --fragments` rewrites patches\\_fragment_stripes_fdphase_{symbols,cave,sites}.yaml
Parity: tests\\test_stripes_fdphase_asm_parity.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402

PCAVE2 = 0x00A0C000
assert PCAVE2 == SE.PCAVE2

SYM_NAMES = ("g_popup_scale_num", "g_stripe_period", "g_filedlg_active", "Buffer_tile", "Buffer_copy_4",
             "thunk_ensure_stripes", "g_stripe_navy", "g_stripe_sel", "g_filedlg_rowtile_sel",
             "thunk_filedlg_rowbg_v6", "thunk_copy4_stripes")

ROWBG_OFF, ROWBG_LIMIT = 0x2F00, 0x2F50          # cave_map.py --at 0x2F00: next entry starts 0x2F50
COPY4_OFF, COPY4_LIMIT = 0x2F50, 0x2FA0          # cave_map.py --at 0x2F50: next entry (g_fe_dst) starts 0x2FA0

CANVAS = 0x444                                    # GraphicWin canvas (struct Buffer) inside the Win
RRECT1_TOP = 0x140                                # Win rRect1.top
RRECT2_TOP = 0x150                                # Win rRect2.top
R1 = RRECT1_TOP - CANVAS                          # -0x304
R2 = RRECT2_TOP - CANVAS                          # -0x2F4

GATE_PREFIX = "83 3D {abs32:g_filedlg_active} 00 74 09 83 3D {abs32:g_popup_scale_num} 10 7F 06 68"


def load_syms(patches: Path | None = None) -> dict[str, int]:
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    s2v = ap.build_symbol_table(symbols, caves)
    out = {n: s2v[n] for n in SYM_NAMES}
    assert out["thunk_filedlg_rowbg_v6"] == PCAVE2 + ROWBG_OFF
    assert out["thunk_copy4_stripes"] == PCAVE2 + COPY4_OFF
    return out


def asm_rowbg(s: dict[str, int]) -> str:
    """thiscall(ecx = list canvas)(sprite, srcOffX, srcOffY, destX, destY, w, h), entered by `call` from 0x407327."""
    return f"""
    cmp     dword ptr [{s['g_filedlg_active']:#x}], 0
    je      native
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      scaled
native:
    push    {s['Buffer_tile']:#x}
    ret
scaled:
    push    ecx
    call    {s['thunk_ensure_stripes']:#x}
    pop     ecx
    mov     eax, dword ptr [ecx{R1:+#x}]
    add     eax, dword ptr [ecx{R2:+#x}]
    add     dword ptr [esp+0xC], eax
    mov     eax, dword ptr [{s['g_stripe_navy']:#x}]
    mov     edx, dword ptr [esp+4]
    cmp     edx, dword ptr [{s['g_filedlg_rowtile_sel']:#x}]
    jne     go
    mov     eax, dword ptr [{s['g_stripe_sel']:#x}]
go:
    mov     dword ptr [esp+4], eax
    jmp     native
"""


def asm_copy4(s: dict[str, int]) -> str:
    """Buffer_copy_4 drop-in: thiscall(ecx = parent canvas)(dst, srcX, srcY, dstX, dstY, w, h) RET 0x1C."""
    return f"""
    cmp     dword ptr [{s['g_filedlg_active']:#x}], 0
    je      native
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      scaled
native:
    push    {s['Buffer_copy_4']:#x}
    ret
scaled:
    call    {s['thunk_ensure_stripes']:#x}
    mov     ecx, dword ptr [esp+4]
    test    ecx, ecx
    je      done
    mov     eax, dword ptr [ecx{R1:+#x}]
    add     eax, dword ptr [ecx{R2:+#x}]
    mov     edx, dword ptr [esp+0x1C]
    push    edx
    push    dword ptr [esp+0x1C]
    push    0
    push    0
    push    eax
    push    0
    push    dword ptr [{s['g_stripe_navy']:#x}]
    call    {s['Buffer_tile']:#x}
done:
    ret     0x1C
"""


THUNKS = (("thunk_filedlg_rowbg_v6", ROWBG_OFF, ROWBG_LIMIT, asm_rowbg),
          ("thunk_copy4_stripes", COPY4_OFF, COPY4_LIMIT, asm_copy4))


def assemble_all(syms: dict[str, int] | None = None) -> dict[str, tuple[int, bytes, int]]:
    """{thunk id: (pcave2 offset, replacement bytes, slot limit)}."""
    s = syms or load_syms()
    out = {}
    for name, off, limit, fn in THUNKS:
        src = fn(s)
        assert ";" not in src
        b = SE.assemble(src, PCAVE2 + off)
        assert off + len(b) <= limit, (name, len(b), limit - off)
        out[name] = (off, b, limit)
    return out


def templates(syms: dict[str, int] | None = None) -> dict[str, tuple[int, str, int, int]]:
    """{id: (offset, patches.yaml byte template, length, slot limit)}; each template round-trips through the
    patcher's own ByteTemplate."""
    s = syms or load_syms()
    names = {v: n for n, v in s.items() if n not in ("thunk_filedlg_rowbg_v6", "thunk_copy4_stripes")}
    out = {}
    for name, (off, b, limit) in assemble_all(s).items():
        tpl = SE.templatize(b, PCAVE2 + off, names)
        assert bytes(ap.ByteTemplate(tpl).resolve(PCAVE2 + off, dict(s))) == b, name
        assert tpl.startswith(GATE_PREFIX), name
        out[name] = (off, tpl, len(b), limit)
    return out


def shipped_templates(patches: Path | None = None) -> dict[str, str]:
    """The `bytes:` template each thunk has in patches.yaml today (read as text: no YAML round-trip)."""
    text = Path(patches or ap.DEFAULT_PATCHES).read_text(encoding="utf-8").splitlines()
    out = {}
    for name, _off, _limit, _fn in THUNKS:
        for i, line in enumerate(text):
            if line.strip() == f"- id: {name}":
                for nxt in text[i + 1:i + 6]:
                    if nxt.strip().startswith("bytes:"):
                        out[name] = nxt.split('"')[1]
                        break
                break
    return out


def cave_yaml(syms: dict[str, int] | None = None) -> str:
    notes = {
        "thunk_filedlg_rowbg_v6": "srcOffY += [canvas-0x304] + [canvas-0x2F4] (Win rRect1.top + rRect2.top = the "
                                  "list's top in the parent canvas, Win_flip_rect_2's own sum); Buffer_tile takes it "
                                  "modulo the tile height = g_stripe_period",
        "thunk_copy4_stripes": "Buffer_tile(dst, g_stripe_navy, 0, top, 0, 0, srcW, srcH), top = [dst-0x304] + "
                               "[dst-0x2F4]; null dst returns",
    }
    out = ["# REPLACEMENTS for two existing pcave2 entries (same id, same offset): swap the bytes: line in patches.yaml.",
           "# Generated by scripts\\assemble_stripes_fdphase.py --fragments."]
    for name, (off, tpl, n, limit) in templates(syms).items():
        out.append(f"      # {name} ({n}B, slot ends {limit:#x}): {notes[name]}")
        out.append(f"      - id: {name}")
        out.append(f"        offset: {off:#x}")
        out.append(f'        bytes: "{tpl}"')
    return "\n".join(out) + "\n"


SYMBOLS_YAML = ("# stripes_fdphase: no new symbol. The two thunks keep their ids and offsets; only the trailing\n"
                "# comments change (sizes 63B/65B are stale in the symbols block: now 75B / 79B).\n")
SITES_YAML = ("# stripes_fdphase: no new site. FileDlg_draw_row 0x407327 and the two backdrop captures\n"
              "# 0x60BBBA / 0x60C421 are already redirected to the two thunks.\n")


def write_fragments() -> list[Path]:
    d = Path(ap.DEFAULT_PATCHES).parent
    files = {"_fragment_stripes_fdphase_symbols.yaml": SYMBOLS_YAML,
             "_fragment_stripes_fdphase_cave.yaml": cave_yaml(),
             "_fragment_stripes_fdphase_sites.yaml": SITES_YAML}
    out = []
    for name, text in files.items():
        p = d / name
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        out.append(p)
    return out


def main(argv: list[str]) -> int:
    if "--fragments" in argv:
        for p in write_fragments():
            print("wrote", p)
        return 0
    old = shipped_templates()
    for name, (off, tpl, n, limit) in templates().items():
        print(f"{name} @pcave2 {off:#x}: {n} B, slot ends {limit:#x}, slack {limit - off - n}")
        print(f"  old: {old.get(name, '?')}")
        print(f"  new: {tpl}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
