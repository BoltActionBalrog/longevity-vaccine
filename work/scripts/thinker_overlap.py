"""Static Thinker-vs-patches.yaml overlap check (rebuilt 2026-10-28; the 2026-09-21 original was lost).

Thinker (refs/thinker, tag v5.5) never touches terranx.exe on disk: thinker.exe starts the PRACX exe
suspended, injects thinker.dll, and the DLL patches the image IN MEMORY.  Every one of its writes is
guarded by its own byte check and a failed check is `exit_fail` -- a MessageBox and no game.  So a
site of ours that changes a byte Thinker checks is FATAL for the player, and a Thinker write that
lands inside a site of ours silently replaces our bytes (CLOBBER).  This script measures both, from
the real sources and the real exe bytes; it decides nothing.  Exclusions and screen ownership are the
user's decisions (memory feedback-thinker-conflicts-user-decides).

What is parsed (all of Thinker's write surface at v5.5):
  * patchdata.h  AXPatchData[]   {addr, old, new} single-byte triples (Scient's patch), checked
                                 old||new except inside [AXSkipVerifyStart, AXSkipVerifyEnd]
  * patchveh.h   VehPatchData[]  {addr, field_off}: the int32 operand at addr must equal
                                 VehsDef + field_off (modify_unit_limit; default on)
  * patch.cpp    patch_setup(): write_call / write_jump / write_bytes / write_byte / write_word /
                                 write_offset / remove_call / short_jump / long_jump, direct
                                 `*(T*)0x... =`, memset / memcpy to literal addresses, and the
                                 `*(T*)0x... == ...` read-gates in if-conditions -- each with its
                                 enclosing if-conditions, so PRACX gating (`cf->reduced_mode`,
                                 set when the exe carries PRACX's "prax" marker) is known.

Usage:
  thinker_overlap.py [--base <clean PRACX exe>] [--patched <baked exe>] [--report out.md]
                     [--json out.json] [--dll] [--all-modes]
Defaults: base = config.terranx_bak(), patched = config.terranx(), Thinker source = refs/thinker/src.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pefile  # noqa: E402

import apply_patches as ap  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
THINKER_SRC = ROOT / "refs" / "thinker" / "src"
PATCHES = ROOT / "work" / "patches" / "patches.yaml"
UIMOD_SRC = ROOT / "src" / "uimod" / "src"

IMAGE_BASE = 0x401000          # Thinker's AC_IMAGE_BASE (patch.h)
IMAGE_LEN = 0x263000           # Thinker's AC_IMAGE_LEN
PRACX_MARKER = 0x668165        # strcmp((char*)0x668165, "prax") == 0  ->  cf->reduced_mode

SHORT_JCC = {0x74, 0x75, 0x7C, 0x7D, 0x7E}
LONG_JCC = {0x840F, 0x850F, 0x8C0F, 0x8D0F, 0x8E0F}


# ----------------------------------------------------------------------------------------------
# Thinker's write surface
# ----------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Write:
    kind: str                       # scient | veh_operand | write_call | ... | direct | memset | memcpy | read_check
    addr: int
    length: int                     # bytes WRITTEN (write_call: 5 for E8, 6 for FF15 -- see footprint())
    conds: tuple                    # enclosing if-conditions, outermost first; "!(c)" for an else branch
    line: int                       # source line (0 for the tables)
    text: str = ""                  # the source statement
    comment: str = ""               # trailing // comment, if any
    old: bytes | None = None        # bytes Thinker expects (write_bytes exact; scient/byte/word: old)
    new: bytes | None = None        # bytes Thinker writes when they are literal
    target: str = ""                # mod_* function / expression for calls, jumps, offsets
    field_off: int | None = None    # veh_operand
    width: int = 0                  # read_check / direct: operand width

    @property
    def end(self) -> int:
        return self.addr + self.length

    def gating(self, reduced_mode: bool = True, known: dict | None = None) -> tuple[str, tuple]:
        """('always' | 'never' | 'option', gating conditions) under the given cf->reduced_mode.
        `known` maps option names Thinker itself forces in this mode (see forced_options) to their truth value."""
        return classify_conds(self.conds, reduced_mode, known)


_COND_SPLIT = re.compile(r"(&&|\|\||!(?!=)|\(|\))")


def _formula_values(cond: str, reduced_mode: bool, known: dict | None = None) -> set:
    """Every truth value the condition can take: atoms are unknown except `reduced_mode` and `known` options."""
    known = known or {}
    tokens = [t.strip() for t in _COND_SPLIT.split(cond) if t.strip()]
    atoms: list[str] = []
    out = []
    for t in tokens:
        if t == "&&":
            out.append(" and ")
        elif t == "||":
            out.append(" or ")
        elif t == "!":
            out.append(" not ")
        elif t in "()":
            out.append(t)
        else:
            norm = t.replace(" ", "")
            if norm in ("cf->reduced_mode", "conf.reduced_mode"):
                out.append("True" if reduced_mode else "False")
            elif norm.startswith("cf->") and norm[4:] in known:
                out.append("True" if known[norm[4:]] else "False")
            else:
                if t not in atoms:
                    atoms.append(t)
                out.append(f"v[{atoms.index(t)}]")
    expr = "".join(out)
    vals = set()
    n = len(atoms)
    for bits in range(1 << n):
        v = [bool(bits >> i & 1) for i in range(n)]
        try:
            vals.add(bool(eval(expr, {"__builtins__": {}}, {"v": v})))  # noqa: S307 - our own tokens
        except SyntaxError:
            return {True, False}   # a condition shape the tokenizer did not understand: treat as an option gate
    return vals


def classify_conds(conds, reduced_mode: bool = True, known: dict | None = None) -> tuple[str, tuple]:
    gates = []
    for c in conds:
        if c is None:
            continue
        vals = _formula_values(c, reduced_mode, known)
        if vals == {False}:
            return "never", (c,)
        if vals == {True}:
            continue
        gates.append(c)
    return ("option", tuple(gates)) if gates else ("always", ())


def forced_options(assigns, reduced_mode: bool = True) -> dict:
    """Options patch_setup() itself overwrites with a literal in this mode (`cf->smooth_scrolling = 0` under PRACX):
    an assignment whose enclosing conditions hold whenever the option is on makes the option effectively that literal."""
    known: dict = {}
    for a in assigns:
        name, value = a.target, a.width
        if _formula_values(" && ".join(f"({c})" for c in a.conds) or "1", reduced_mode, {name: True}) == {True}:
            known[name] = bool(value)
    return known


def load_ini_defaults(src: Path = THINKER_SRC) -> dict:
    """`key=value` defaults from the source tree's docs/thinker.ini (what a player gets out of the box)."""
    p = Path(src).parent / "docs" / "thinker.ini"
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").split("\n"):
            m = re.match(r"^([A-Za-z_]\w*)\s*=\s*([^;]*?)\s*$", line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def parse_patchdata(path: Path) -> tuple[list[Write], tuple[int, int]]:
    """AXPatchData triples and the skip-verify range."""
    text = path.read_text(encoding="utf-8", errors="replace")
    m1 = re.search(r"AXSkipVerifyStart\s*=\s*\(void\*\)0x([0-9A-Fa-f]+)", text)
    m2 = re.search(r"AXSkipVerifyEnd\s*=\s*\(void\*\)0x([0-9A-Fa-f]+)", text)
    skip = (int(m1.group(1), 16), int(m2.group(1), 16)) if m1 and m2 else (0, -1)
    body = text.split("AXPatchData[] = {", 1)[1].split("};", 1)[0]
    writes = []
    for m in re.finditer(r"\{\s*0x([0-9A-Fa-f]+)\s*,\s*0x([0-9A-Fa-f]+)\s*,\s*0x([0-9A-Fa-f]+)\s*\}", body):
        a, old, new = (int(m.group(i), 16) for i in (1, 2, 3))
        writes.append(Write("scient", a, 1, (), 0, old=bytes([old]), new=bytes([new])))
    return writes, skip


def parse_patchveh(path: Path) -> list[Write]:
    text = path.read_text(encoding="utf-8", errors="replace")
    body = text.split("VehPatchData[][2] = {", 1)[1].split("};", 1)[0]
    writes = []
    for m in re.finditer(r"\{\s*0x([0-9A-Fa-f]+)\s*,\s*0x([0-9A-Fa-f]+)\s*\}\s*,?\s*(//[^\n]*)?", body):
        writes.append(Write("veh_operand", int(m.group(1), 16), 4, ("cf->modify_unit_limit",), 0,
                            comment=(m.group(3) or "").strip("/ "), field_off=int(m.group(2), 16)))
    return writes


def parse_vehs_def(engine_cpp: Path) -> int:
    m = re.search(r"VehsDef\s*=\s*\(VEH\*\s*\)\s*0x([0-9A-Fa-f]+)", engine_cpp.read_text(encoding="utf-8", errors="replace"))
    if not m:
        raise SystemExit("VehsDef not found in engine.cpp")
    return int(m.group(1), 16)


_WIDTH = {"byte": 1, "uint8_t": 1, "char": 1, "int8_t": 1, "uint16_t": 2, "int16_t": 2,
          "uint32_t": 4, "int32_t": 4, "int": 4}
_CAST_WRITE = re.compile(r"\*\(\s*(u?int(?:8|16|32)_t|int|byte|char)\s*\*\s*\)\s*\(?\s*0x([0-9A-Fa-f]{6,8})\s*\)?\s*=(?!=)")
_CAST_READ = re.compile(r"\*\(\s*(u?int(?:8|16|32)_t|int|byte|char)\s*\*\s*\)\s*\(?\s*0x([0-9A-Fa-f]{6,8})\s*\)?\s*(==|!=)\s*(0x[0-9A-Fa-f]+|\d+)")
_MEMSET = re.compile(r"memset\(\s*\(void\*\)\s*0x([0-9A-Fa-f]{6,8})\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*(\d+|sizeof\(\w+\))\s*\)")
_MEMCPY = re.compile(r"memcpy\(\s*\(void\*\)\s*0x([0-9A-Fa-f]{6,8})\s*,\s*(\w+)\s*,\s*(\d+|sizeof\(\w+\))\s*\)")
_HELPER = re.compile(r"^\s*(write_call|write_jump|write_bytes|write_byte|write_word|write_offset|remove_call|short_jump|long_jump)\(\s*0x([0-9A-Fa-f]{6,8})\s*(?:,\s*(.*))?\)\s*;")
_ASSIGN = re.compile(r"^\s*cf->(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*;")
_ARRAY = re.compile(r"(?:const\s+)?(?:byte|uint8_t)\s+(\w+)\[\]\s*=\s*\{")


def _int_literal(s: str) -> int | None:
    s = s.strip()
    m = re.fullmatch(r"\(?\s*(?:\(int\))?\s*(0x[0-9A-Fa-f]+|\d+)\s*\)?", s)
    return int(m.group(1), 0) if m else None


def _split_args(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
            continue
        depth += ch in "([{"
        depth -= ch in ")]}"
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_patch_cpp(path: Path) -> list[Write]:
    """Every write and read-gate in patch_setup(), with its enclosing if-conditions."""
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("bool patch_setup("))
    writes: list[Write] = []
    arrays: dict[str, bytes] = {}
    # frames: (depth_after_open, cond or None, is_cond_frame)
    frames: list[tuple[int, str | None]] = []
    depth = 0
    last_closed_cond: str | None = None
    pending_cond: str | None = None       # an `if (...)` whose body (brace or single statement) comes next
    i = start
    n = len(lines)

    def conds_now():
        return tuple(c for _, c in frames if c is not None)

    def add(kind, addr, length, line_no, text, comment, **kw):
        writes.append(Write(kind, addr, length, conds_now(), line_no, text.strip(), comment, **kw))

    def add_read_checks(cond: str, line_no: int, comment: str):
        """`*(T*)0x... == v` inside an if-condition: Thinker reads those bytes to decide a feature."""
        for m in _CAST_READ.finditer(cond):
            w = _WIDTH[m.group(1)]
            v = int(m.group(4), 0)
            writes.append(Write("read_check", int(m.group(2), 16), 0, conds_now(), line_no, cond, comment,
                                old=(v & ((1 << (8 * w)) - 1)).to_bytes(w, "little"), target=m.group(3), width=w))

    while i < n:
        raw = lines[i]
        line_no = i + 1
        code, _, comment = raw.partition("//")
        comment = comment.strip()
        s = code.strip()
        i += 1
        if not s:
            continue
        # -- byte-array definitions (brace initialisers must not count as blocks)
        am = _ARRAY.search(code)
        if am:
            buf = code[am.end():]
            while "}" not in buf and i < n:
                buf += " " + lines[i].partition("//")[0]
                i += 1
            body = buf.split("}", 1)[0]
            arrays[am.group(1)] = bytes(int(x, 0) for x in re.findall(r"0x[0-9A-Fa-f]+|\b\d+\b", body))
            continue
        # -- control flow
        im = re.match(r"^(?:\}\s*)?(else\s+if|if|else)\b\s*(.*)$", s)
        if im:
            closing = s.startswith("}")
            if closing:
                # the frame this brace closes
                depth -= 1
                while frames and frames[-1][0] > depth:
                    last_closed_cond = frames.pop()[1]
            kw, rest = im.group(1), im.group(2)
            cond = None
            if kw in ("if", "else if"):
                # collect the parenthesised condition, possibly over several lines
                buf = rest
                while buf.count("(") > buf.count(")") and i < n:
                    buf += " " + lines[i].partition("//")[0].strip()
                    i += 1
                open_idx = buf.index("(")
                d = 0
                for j in range(open_idx, len(buf)):
                    d += buf[j] == "("
                    d -= buf[j] == ")"
                    if d == 0:
                        break
                cond = buf[open_idx + 1:j].strip()
                rest = buf[j + 1:].strip()
                if kw == "else if":
                    cond = f"!({last_closed_cond}) && ({cond})"
            else:
                cond = f"!({last_closed_cond})"
            if kw != "else":
                add_read_checks(cond, line_no, comment)
            if rest.startswith("{"):
                depth += 1
                frames.append((depth, cond))
                rest = rest[1:].strip()
                if rest:
                    # statement on the same line as the brace: fall through to parse it
                    s = rest
                else:
                    continue
            else:
                pending_cond = cond
                if rest:
                    s = rest
                else:
                    continue
        gated_single = False
        if pending_cond is not None:
            # braceless if-body: this single statement (same line or the next) is gated
            frames.append((depth + 1, pending_cond))
            gated_single = True
            pending_cond = None
        # -- block braces on plain lines (for/while/switch/scope)
        if s == "{" or s.endswith("{"):
            depth += 1
            frames.append((depth, None))
            s = s[:-1].strip() if s != "{" else ""
        if s.startswith("}"):
            depth -= 1
            while frames and frames[-1][0] > depth:
                last_closed_cond = frames.pop()[1] or last_closed_cond
            s = s[1:].strip()
        if not s:
            if gated_single:
                frames.pop()
            continue
        # -- option assignments (Thinker forcing one of its own options, e.g. smooth_scrolling under PRACX)
        asg = _ASSIGN.match(s)
        if asg:
            add("assign", 0, 0, line_no, s, comment, target=asg.group(1), width=int(asg.group(2), 0))
        # -- helpers
        hm = _HELPER.match(s)
        if hm:
            kind, addr, args = hm.group(1), int(hm.group(2), 16), _split_args(hm.group(3) or "")
            if kind == "write_call" or kind == "write_jump":
                add(kind, addr, 5, line_no, s, comment, target=args[0] if args else "")
            elif kind == "write_offset":
                add(kind, addr, 5, line_no, s, comment, target=args[0] if args else "")
            elif kind == "remove_call":
                add(kind, addr, 5, line_no, s, comment, new=b"\x90" * 5)
            elif kind == "short_jump":
                add(kind, addr, 1, line_no, s, comment, new=b"\xEB")
            elif kind == "long_jump":
                add(kind, addr, 2, line_no, s, comment, new=b"\x90\xE9")
            elif kind == "write_byte":
                old, new = _int_literal(args[0]), _int_literal(args[1])
                add(kind, addr, 1, line_no, s, comment, old=bytes([old]) if old is not None else None,
                    new=bytes([new]) if new is not None else None, target=args[1])
            elif kind == "write_word":
                old, new = _int_literal(args[0]), _int_literal(args[1])
                add(kind, addr, 4, line_no, s, comment,
                    old=old.to_bytes(4, "little", signed=True) if old is not None else None,
                    new=new.to_bytes(4, "little", signed=True) if new is not None else None, target=args[1])
            elif kind == "write_bytes":
                oldn, newn, lenx = args[0], args[1], args[2]
                old = arrays.get(oldn)
                new = None if newn == "NULL" else arrays.get(newn)
                lm = re.fullmatch(r"sizeof\((\w+)\)", lenx)
                length = len(arrays[lm.group(1)]) if lm and lm.group(1) in arrays else _int_literal(lenx)
                if length is None:
                    raise SystemExit(f"patch.cpp:{line_no}: write_bytes length not resolved: {s}")
                if new is None and newn == "NULL":
                    new = b"\x90" * length
                add(kind, addr, length, line_no, s, comment, old=old[:length] if old else None,
                    new=new[:length] if new else None)
        else:
            for m in _CAST_WRITE.finditer(s):
                w = _WIDTH[m.group(1)]
                rhs = s[m.end():].strip().rstrip(";")
                v = _int_literal(rhs)
                add("direct", int(m.group(2), 16), w, line_no, s, comment,
                    new=v.to_bytes(w, "little", signed=v < 0) if v is not None else None, target=rhs, width=w)
            for m in _MEMSET.finditer(s):
                lm = re.fullmatch(r"sizeof\((\w+)\)", m.group(3))
                length = len(arrays[lm.group(1)]) if lm else int(m.group(3))
                add("memset", int(m.group(1), 16), length, line_no, s, comment, new=bytes([int(m.group(2), 0) & 0xFF]) * length)
            for m in _MEMCPY.finditer(s):
                lm = re.fullmatch(r"sizeof\((\w+)\)", m.group(3))
                src = arrays.get(m.group(2))
                length = len(arrays[lm.group(1)]) if lm and lm.group(1) in arrays else (int(m.group(3)) if m.group(3).isdigit() else (len(src) if src else None))
                if length is None:
                    raise SystemExit(f"patch.cpp:{line_no}: memcpy length not resolved: {s}")
                add("memcpy", int(m.group(1), 16), length, line_no, s, comment, new=src[:length] if src else None, target=m.group(2))
        if gated_single:
            frames.pop()
    return writes


def load_thinker(src: Path = THINKER_SRC) -> dict:
    """Thinker's writes in the order patch_setup() performs them: the Scient triples at their loop, the unit-array
    operands at theirs, everything else by source line.  Order matters -- a later guard reads what an earlier write
    left (VehPatchData was generated against the Scient-patched image, so its guards fail on the raw exe)."""
    scient, skip = parse_patchdata(src / "patchdata.h")
    veh = parse_patchveh(src / "patchveh.h")
    cpp = parse_patch_cpp(src / "patch.cpp")
    lines = (src / "patch.cpp").read_text(encoding="utf-8", errors="replace").split("\n")
    scient_line = next(i + 1 for i, l in enumerate(lines) if "AXPatchData" in l and "for (" in l)
    veh_line = next(i + 1 for i, l in enumerate(lines) if "VehPatchData" in l and "for (" in l)
    for w in scient:
        w.line = scient_line
    for w in veh:
        w.line = veh_line
    order = {"scient": 0, "veh_operand": 1}
    assigns = [w for w in cpp if w.kind == "assign"]
    cpp = [w for w in cpp if w.kind != "assign"]
    writes = sorted(scient + veh + cpp, key=lambda w: (w.line, order.get(w.kind, 2)))
    return {"writes": writes, "assigns": assigns, "skip_verify": skip, "vehs_def": parse_vehs_def(src / "engine.cpp"),
            "counts": _counts(writes), "table_lines": {"scient": scient_line, "veh_operand": veh_line},
            "ini_defaults": load_ini_defaults(src)}


def _counts(writes) -> dict:
    c: dict[str, int] = {}
    for w in writes:
        c[w.kind] = c.get(w.kind, 0) + 1
    return dict(sorted(c.items()))


# ----------------------------------------------------------------------------------------------
# Thinker's checks, emulated on real exe bytes
# ----------------------------------------------------------------------------------------------

class Image:
    def __init__(self, path: Path, data: bytes | None = None):
        self.path = Path(path)
        self.data = bytearray(data if data is not None else self.path.read_bytes())
        self.pe = pefile.PE(data=bytes(self.data), fast_load=True)
        self.res = ap.VaResolver(self.pe)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase

    def copy(self) -> "Image":
        return Image(self.path, bytes(self.data))

    def rd(self, va: int, n: int) -> bytes | None:
        off = self.res.to_file_offset(va)
        if off is None or off + n > len(self.data):
            return None
        return bytes(self.data[off:off + n])

    def wr(self, va: int, b: bytes) -> None:
        off = self.res.to_file_offset(va)
        if off is not None and off + len(b) <= len(self.data):
            self.data[off:off + len(b)] = b

    def i32(self, va: int) -> int | None:
        b = self.rd(va, 4)
        return int.from_bytes(b, "little", signed=True) if b else None

    def u16(self, va: int) -> int | None:
        b = self.rd(va, 2)
        return int.from_bytes(b, "little") if b else None


def footprint(w: Write, img: Image) -> int:
    """Bytes Thinker writes at w.addr on this image (write_call is 6 for an FF15 site)."""
    if w.kind == "write_call":
        return 6 if img.u16(w.addr) == 0x15FF else 5
    if w.kind == "read_check":
        return w.width
    return w.length


def check(w: Write, img: Image, skip: tuple[int, int], vehs_def: int) -> tuple[str, str]:
    """('ok'|'fail'|'none', detail): would Thinker's own guard pass on this image?"""
    b1 = img.rd(w.addr, 1)
    if b1 is None:
        return "fail", "address not in the file image"
    b = b1[0]
    k = w.kind
    if k == "scient":
        if skip[0] <= w.addr <= skip[1]:
            return "none", "inside AXSkipVerify range (written without a check)"
        return ("ok" if b in (w.old[0], w.new[0]) else "fail"), f"byte {b:02X} vs old {w.old[0]:02X}/new {w.new[0]:02X}"
    if k == "veh_operand":
        v = img.i32(w.addr)
        want = vehs_def + w.field_off
        return ("ok" if v == want else "fail"), f"int32 {v & 0xFFFFFFFF:08X} vs VehsDef+{w.field_off:#x} = {want:08X}"
    if k == "write_call":
        if img.u16(w.addr) == 0x15FF and (img.i32(w.addr + 2) or 0) + w.addr >= IMAGE_BASE:
            return "ok", "FF15 indirect call"
        if b == 0xE8 and (img.i32(w.addr + 1) or 0) + w.addr >= IMAGE_BASE:
            return "ok", "E8 call"
        return "fail", f"opcode {img.rd(w.addr, 2).hex().upper()} is neither FF15 nor E8 into the image"
    if k == "write_jump":
        if (w.addr & 0xF) == 0:
            return "none", "16-aligned (function entry): written without a check"
        return ("ok" if b == 0xE9 else "fail"), f"opcode {b:02X} (needs E9 unless 16-aligned)"
    if k == "write_bytes":
        have = img.rd(w.addr, w.length)
        return ("ok" if have == w.old else "fail"), f"{have.hex().upper()} vs {w.old.hex().upper()}"
    if k in ("write_byte", "write_word"):
        have = img.rd(w.addr, w.length)
        if w.old is None:
            return "none", "non-literal old value"
        ok = have == w.old or (w.new is not None and have == w.new)
        return ("ok" if ok else "fail"), f"{have.hex().upper()} vs old {w.old.hex().upper()}" + (f"/new {w.new.hex().upper()}" if w.new else "")
    if k == "write_offset":
        return ("ok" if b == 0x68 and (img.i32(w.addr + 1) or 0) >= IMAGE_BASE else "fail"), f"opcode {b:02X} (needs 68 push imm32)"
    if k == "remove_call":
        return ("ok" if b == 0xE8 and (img.i32(w.addr + 1) or 0) + w.addr >= IMAGE_BASE else "fail"), f"opcode {b:02X} (needs E8)"
    if k == "short_jump":
        return ("ok" if b in SHORT_JCC or b == 0xEB else "fail"), f"opcode {b:02X}"
    if k == "long_jump":
        v = img.u16(w.addr)
        return ("ok" if v in LONG_JCC or v == 0xE990 else "fail"), f"opcode {img.rd(w.addr, 2).hex().upper()}"
    if k == "read_check":
        have = img.rd(w.addr, w.width)
        eq = have == w.old
        taken = eq if w.target == "==" else not eq
        return ("ok" if taken else "fail"), f"{have.hex().upper()} {w.target} {w.old.hex().upper()} -> {'taken' if taken else 'not taken'}"
    return "none", "no guard (direct write)"


def result_bytes(w: Write, img: Image) -> bytes | None:
    """What the bytes at the footprint look like after Thinker's write, when that is literal."""
    if w.kind in ("write_call", "write_jump", "write_offset", "veh_operand", "read_check"):
        return None   # depend on thinker.dll's load address / relocated array
    return w.new


def apply_write(w: Write, img: Image, vehs_def: int) -> None:
    """Perform Thinker's write on the in-memory copy so later guards see what Thinker's would.  Targets that
    depend on thinker.dll's load address get a placeholder operand; the opcode bytes are exact."""
    k = w.kind
    if k == "read_check":
        return
    if k == "write_call":
        if img.u16(w.addr) == 0x15FF:
            img.wr(w.addr, b"\x90\xE8" + b"\x00" * 4)
        else:
            img.wr(w.addr, b"\xE8" + b"\x00" * 4)
    elif k == "write_jump":
        img.wr(w.addr, b"\xE9" + b"\x00" * 4)
    elif k == "write_offset":
        img.wr(w.addr, b"\x68" + (IMAGE_BASE + IMAGE_LEN).to_bytes(4, "little"))
    elif k == "veh_operand":
        img.wr(w.addr, (vehs_def + w.field_off + 0x100000).to_bytes(4, "little"))
    elif w.new is not None:
        img.wr(w.addr, w.new)


# ----------------------------------------------------------------------------------------------
# Our side
# ----------------------------------------------------------------------------------------------

def load_sites(yaml_path: Path = PATCHES):
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        sites, groups, caves, symbols = ap.load_patches(Path(yaml_path))
    live = []
    for s in sites:
        if s.get("status") == "skip" or not s.get("length"):
            continue
        live.append({"id": s["id"], "group": s.get("group"), "function": s.get("function", ""),
                     "va": int(s["virtual_addr"]), "length": int(s["length"]),
                     "original_bytes": str(s.get("original_bytes", "")), "new_bytes": str(s.get("new_bytes", ""))})
    cave_ranges = [(c["id"], int(c["virtual_addr"]), int(c["length"])) for c in caves]
    group_sizes: dict[str, int] = {}
    for s in live:
        group_sizes[s["group"]] = group_sizes.get(s["group"], 0) + 1
    return live, cave_ranges, group_sizes


def _byte_index(sites):
    idx: dict[int, list] = {}
    for s in sites:
        for a in range(s["va"], s["va"] + s["length"]):
            idx.setdefault(a, []).append(s)
    return idx


# ----------------------------------------------------------------------------------------------
# The measurement
# ----------------------------------------------------------------------------------------------

def measure(thinker: dict, sites, caves, base: Image, patched: Image | None, reduced_mode: bool = True) -> dict:
    skip, vehs_def = thinker["skip_verify"], thinker["vehs_def"]
    known = forced_options(thinker.get("assigns", []), reduced_mode)
    idx = _byte_index(sites)
    hits = []            # one record per (write, site) overlap
    base_fails = []      # Thinker's guard already fails on the clean base (not caused by us)
    cave_hits = []
    skipped_mode = []    # writes that do not apply in this mode (reduced_mode gating)
    # Thinker's guards are evaluated in ITS order on a copy that carries its earlier writes (engine call order).
    mb = base.copy()
    mp = patched.copy() if patched else None
    for w in thinker["writes"]:
        gate, gates = w.gating(reduced_mode, known)
        fp = footprint(w, mb)
        lo, hi = w.addr, w.addr + fp
        if gate == "never":
            over = sorted({s["id"] for a in range(lo, hi) for s in idx.get(a, [])})
            if over:
                skipped_mode.append({"write": _wdict(w, fp), "sites": over, "why": gates[0]})
            continue
        cb = check(w, mb, skip, vehs_def)
        cp = check(w, mp, skip, vehs_def) if mp else ("none", "no patched image given")
        ours = mp.rd(lo, fp) if mp else None
        apply_write(w, mb, vehs_def)
        if mp:
            apply_write(w, mp, vehs_def)
        if cb[0] == "fail":
            base_fails.append({"write": _wdict(w, fp), "gate": gate, "gates": gates, "detail": cb[1]})
        for cid, cva, clen in caves:
            if lo < cva + clen and cva < hi:
                cave_hits.append({"write": _wdict(w, fp), "cave": cid})
        over: dict[str, dict] = {}
        for a in range(lo, hi):
            for s in idx.get(a, []):
                over[s["id"]] = s
        if not over:
            continue
        for s in over.values():
            if cp[0] == "fail" and cb[0] != "fail":
                cls = "FATAL"            # our bytes break Thinker's guard -> exit_fail, game never starts
            elif cp[0] == "fail":
                cls = "PRE-EXISTING"     # Thinker's guard fails on the clean base already
            else:
                rb = result_bytes(w, patched or base)
                if w.kind == "read_check":
                    cls = "READ-GATE"    # Thinker reads our bytes to decide whether to apply a feature
                elif rb is not None and ours is not None and rb == ours:
                    cls = "BENIGN"       # Thinker writes exactly the bytes we already put there
                else:
                    cls = "CLOBBER"      # Thinker's write replaces our bytes in memory
            hits.append({"class": cls, "gate": gate, "gates": gates, "write": _wdict(w, fp),
                         "site": {k: s[k] for k in ("id", "group", "function", "va", "length")},
                         "check_base": cb, "check_patched": cp})
    return {"hits": hits, "base_fails": base_fails, "cave_hits": cave_hits, "skipped_mode": skipped_mode,
            "counts": thinker["counts"], "reduced_mode": reduced_mode, "forced": known,
            "ini_defaults": thinker.get("ini_defaults", {})}


def _wdict(w: Write, fp: int) -> dict:
    return {"kind": w.kind, "addr": w.addr, "length": fp, "line": w.line, "text": w.text, "comment": w.comment,
            "target": w.target, "conds": list(w.conds)}


def summarize(m: dict, group_sizes: dict) -> dict:
    groups: dict[str, dict] = {}
    for h in m["hits"]:
        g = h["site"]["group"]
        d = groups.setdefault(g, {"sites_total": group_sizes.get(g, 0), "sites_hit": set(), "classes": {}, "gates": set()})
        d["sites_hit"].add(h["site"]["id"])
        d["classes"][h["class"]] = d["classes"].get(h["class"], 0) + 1
        for x in h["gates"]:
            d["gates"].add(x)
    for g, d in groups.items():
        d["sites_hit"] = sorted(d["sites_hit"])
        d["gates"] = sorted(d["gates"])
    return dict(sorted(groups.items()))


# ----------------------------------------------------------------------------------------------
# Pass 2 (heuristic): uimod.dll's runtime sites
# ----------------------------------------------------------------------------------------------

def dll_proximity(thinker: dict, base: Image, src_dir: Path = UIMOD_SRC, window: int = 16, reduced_mode: bool = True) -> list:
    """Engine-address literals in the DLL sources that a Thinker write touches or sits within `window` bytes of, on
    either side (Thinker's movie hook at 0x403BD4 is 12 bytes BEFORE our amovie_project_2 entry hook at 0x403BE0).
    The DLL byte-checks its sites at Init and self-disables, so a hit here is a feature of ours going INERT (or a
    Thinker feature ours re-patches over), never a crash at launch -- but it is still a conflict for the user."""
    known = forced_options(thinker.get("assigns", []), reduced_mode)
    writes = [(w, footprint(w, base)) for w in thinker["writes"] if w.gating(reduced_mode, known)[0] != "never" and w.kind != "read_check"]
    writes.sort(key=lambda t: t[0].addr)
    starts = [w.addr for w, _ in writes]
    import bisect
    out = []
    for f in sorted(Path(src_dir).glob("*.cpp")):
        for ln, line in enumerate(f.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
            code = line.partition("//")[0]
            if not code.strip() or "UimodLog(" in code or code.lstrip().startswith(("*", "/*", "\"")):
                continue   # comments and log strings mention addresses that are not sites
            for m in re.finditer(r"0x0*([4-6][0-9A-Fa-f]{5})\b", code):
                va = int(m.group(1), 16)
                if not (IMAGE_BASE <= va < IMAGE_BASE + IMAGE_LEN):
                    continue
                lo, hi = va - window, va + window
                j = bisect.bisect_left(starts, lo - 8)
                while j < len(writes) and writes[j][0].addr < hi:
                    w, fp = writes[j]
                    if w.addr < hi and lo < w.addr + fp:
                        out.append({"file": f.name, "line": ln, "literal": va, "code": line.strip()[:140], "write": _wdict(w, fp),
                                    "gate": w.gating(reduced_mode, known)})
                    j += 1
    return out


# ----------------------------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------------------------

_INI_DEFAULTS: dict = {}


def _gate_str(gate, gates) -> str:
    if gate == "always":
        return "unconditional"
    names = sorted({m.group(1) for g in gates for m in re.finditer(r"cf->(\w+)", g)})
    defaults = ", ".join(f"{n}={_INI_DEFAULTS[n]}" for n in names if n in _INI_DEFAULTS)
    return "option-gated: " + " ; ".join(gates) + (f" (thinker.ini default: {defaults})" if defaults else "")


def render(m: dict, summary: dict, base: Image, patched: Image | None, dll_hits: list | None, thinker_src: Path) -> str:
    global _INI_DEFAULTS
    _INI_DEFAULTS = m.get("ini_defaults", {})
    L = []
    L.append("# Thinker overlap report (static, measured)\n")
    L.append(f"- Thinker source: `{thinker_src}`  |  clean base: `{base.path}`  |  patched: `{patched.path if patched else '(none)'}`")
    L.append(f"- Mode: {'PRACX (cf->reduced_mode = 1)' if m['reduced_mode'] else 'Thinker alone (reduced_mode = 0; NOT a shipping target)'}")
    L.append("- Thinker write surface parsed: " + ", ".join(f"{k} {v}" for k, v in m["counts"].items()))
    L.append("- Classes: **FATAL** = our bytes fail Thinker's guard -> exit_fail at launch; **CLOBBER** = Thinker's write replaces our bytes in memory;"
             " **READ-GATE** = Thinker reads our bytes to decide a feature; **BENIGN** = identical bytes; **PRE-EXISTING** = Thinker's guard fails on the clean base already.")
    if m.get("forced"):
        L.append("- Options Thinker forces in this mode: " + ", ".join(f"{k}={int(v)}" for k, v in sorted(m["forced"].items())))
    L.append("- This report decides nothing. Every FATAL / CLOBBER / READ-GATE is a user decision (feedback-thinker-conflicts-user-decides).\n")

    L.append("## Groups touched\n")
    if not summary:
        L.append("(none)\n")
    else:
        L.append("| group | sites hit / total | classes | gating |\n|---|---|---|---|")
        for g, d in summary.items():
            cls = ", ".join(f"{k} {v}" for k, v in sorted(d["classes"].items()))
            gates = "; ".join(d["gates"]) if d["gates"] else "unconditional"
            L.append(f"| `{g}` | {len(d['sites_hit'])} / {d['sites_total']} | {cls} | {gates} |")
        L.append("")

    L.append("## Every overlap\n")
    for h in sorted(m["hits"], key=lambda h: (h["site"]["group"], h["site"]["va"], h["write"]["addr"])):
        w, s = h["write"], h["site"]
        L.append(f"- **{h['class']}** `{s['group']}` / `{s['id']}` ({s['function']}) @ {s['va']:#x}+{s['length']}  <->  "
                 f"Thinker {w['kind']} @ {w['addr']:#x}+{w['length']}" + (f" -> {w['target']}" if w['target'] else "")
                 + (f" (patch.cpp:{w['line']})" if w['line'] else "") + (f" // {w['comment']}" if w['comment'] else ""))
        L.append(f"  - {_gate_str(h['gate'], h['gates'])}; guard on base: {h['check_base'][0]} ({h['check_base'][1]}); on patched: {h['check_patched'][0]} ({h['check_patched'][1]})")
    if not m["hits"]:
        L.append("(none)")
    L.append("")

    L.append("## Caves\n")
    L.append("(no Thinker write inside our caves)\n" if not m["cave_hits"] else "\n".join(f"- `{c['cave']}` <- {c['write']}" for c in m["cave_hits"]) + "\n")

    L.append("## Thinker guards that fail on the clean base (not caused by us: Thinker's own option combinations / PRACX)\n")
    if not m["base_fails"]:
        L.append("(none)\n")
    else:
        for b in m["base_fails"]:
            w = b["write"]
            L.append(f"- {w['kind']} @ {w['addr']:#x}+{w['length']} ({_gate_str(b['gate'], b['gates'])}): {b['detail']}" + (f" // {w['comment']}" if w['comment'] else ""))
        L.append("")

    L.append("## Writes that do not apply in this mode but overlap our sites\n")
    if not m["skipped_mode"]:
        L.append("(none)\n")
    else:
        for s in m["skipped_mode"]:
            w = s["write"]
            L.append(f"- {w['kind']} @ {w['addr']:#x}+{w['length']} skipped by `{s['why']}`; sites: {', '.join(s['sites'])}")
        L.append("")

    if dll_hits is not None:
        L.append("## uimod.dll runtime sites (heuristic: address literals in src/uimod/src within 16 bytes of a Thinker write)\n")
        if not dll_hits:
            L.append("(none)\n")
        else:
            for d in dll_hits:
                w = d["write"]
                L.append(f"- `{d['file']}:{d['line']}` literal {d['literal']:#x}  <->  Thinker {w['kind']} @ {w['addr']:#x}+{w['length']}"
                         + (f" -> {w['target']}" if w['target'] else "") + f" ({_gate_str(*d['gate'])})" + (f" // {w['comment']}" if w['comment'] else ""))
                L.append(f"  - `{d['code']}`")
            L.append("")
    return "\n".join(L)


def run(thinker_src: Path = THINKER_SRC, yaml_path: Path = PATCHES, base_path: Path | None = None,
        patched_path: Path | None = None, reduced_mode: bool = True, dll: bool = False) -> dict:
    import config
    base = Image(base_path or config.terranx_bak())
    patched = Image(patched_path) if patched_path else (Image(config.terranx()) if config.terranx(required=False).exists() else None)
    thinker = load_thinker(Path(thinker_src))
    sites, caves, group_sizes = load_sites(yaml_path)
    m = measure(thinker, sites, caves, base, patched, reduced_mode)
    summary = summarize(m, group_sizes)
    dll_hits = dll_proximity(thinker, base, reduced_mode=reduced_mode) if dll else None
    return {"measure": m, "summary": summary, "dll": dll_hits, "base": base, "patched": patched, "thinker": thinker,
            "report": render(m, summary, base, patched, dll_hits, Path(thinker_src))}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--thinker-src", type=Path, default=THINKER_SRC)
    p.add_argument("--yaml", type=Path, default=PATCHES)
    p.add_argument("--base", type=Path, help="clean PRACX exe (default: config.terranx_bak())")
    p.add_argument("--patched", type=Path, help="our baked exe (default: config.terranx())")
    p.add_argument("--all-modes", action="store_true", help="also report Thinker-alone gating (not a target)")
    p.add_argument("--dll", action="store_true", help="add the heuristic uimod.dll runtime-site pass")
    p.add_argument("--report", type=Path, help="write the markdown report here")
    p.add_argument("--json", type=Path, help="write the structured result here")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)
    r = run(a.thinker_src, a.yaml, a.base, a.patched, True, a.dll)
    text = r["report"]
    if a.all_modes:
        r2 = run(a.thinker_src, a.yaml, a.base, a.patched, False, False)
        text += "\n\n---\n\n" + r2["report"]
    if a.report:
        a.report.write_text(text, encoding="utf-8")
    if a.json:
        a.json.write_text(json.dumps({"measure": r["measure"], "summary": r["summary"], "dll": r["dll"]}, indent=1), encoding="utf-8")
    if not a.quiet:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
