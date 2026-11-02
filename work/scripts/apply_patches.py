"""SMACX UI scaling patcher — applies patches.yaml to terranx.exe.

Workflow:
  1. Load patches.yaml: sites, groups, code_caves, symbols.
  2. Read terranx.exe; verify size and MD5 against expected values.
  3. Parse the PE section table to convert virtual addresses to file offsets.
  4. Verify each site (anchor + original bytes), each cave (padding-only),
     and decide group eligibility (all members + all referenced caves
     must verify, or the whole group is skipped).
  5. If --apply was passed: save a backup, resolve any `{rel32:NAME}`
     placeholders in cave-content bytes and site new_bytes, write all
     resolved bytes, atomic-rename into place.

Dry-run by default. Use --apply to commit.

  D:\\SmacxUi\\work\\run-apply-patches.bat            # dry-run
  D:\\SmacxUi\\work\\run-apply-patches.bat --apply    # write changes
  D:\\SmacxUi\\work\\run-apply-patches.bat --restore  # restore from backup
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

import pefile
import yaml

import config

DEFAULT_TARGET = str(config.terranx(required=False))

#: Resolved relative to THIS FILE, not absolute. It used to be a hardcoded
#: r"D:\SmacxUi\work\patches\patches.yaml", which meant the patch step failed on every end-user
#: machine -- a release blocker. `work\scripts\` sits beside `work\patches\` in the repo AND in an
#: extracted release archive (release.py stages a repo-shaped payload on purpose), so one
#: derivation serves both. Override with --patches, or PAYLOAD_ROOT for a relocated payload.
#: patches.yaml is 1.78 MB, and the pure-Python YAML loader takes ~2.0s to parse it against
#: ~0.22s for the C one -- a 9x difference, MEASURED on this file, with an identical result
#: (non-ASCII content included, which matters here: see the UTF-8 rule for this file).
#:
#: Every installer run parses it, so this is ~2s off the player's install, not merely off the test
#: suite. The fallback is not decoration: a trimmed runtime that omits _yaml.pyd still works, just
#: slower, and pyyaml's own `safe_load` never picks the C loader for you -- it has to be asked.
try:
    from yaml import CSafeLoader as _YAML_LOADER
except ImportError:                                  # pragma: no cover - depends on the build
    from yaml import SafeLoader as _YAML_LOADER


def _yaml_load(stream):
    """yaml.safe_load, but using the C loader when it is available."""
    return yaml.load(stream, Loader=_YAML_LOADER)


_WORK = Path(__file__).resolve().parent.parent
DEFAULT_PATCHES = str(_WORK / "patches" / "patches.yaml")

# Expected fingerprint of the PRACX-patched GOG terranx.exe (2024-08-19).
EXPECTED_MD5 = "2d0b1438eb73f98519134d7a4f6bc054"
EXPECTED_SIZE = 3_084_288

# Pristine (un-PRACX'd) GOG terranx.exe — the --pristine target. Same size; the
# only delta from the PRACX base is PRACX's own 45-byte loader (see patches.yaml
# target.pristine_md5). Used with --pristine to install the pristine group set.
PRISTINE_MD5 = "cc659f53cb6fa0eaaddccd0a54176647"
PRISTINE_EXE = "terranx.exe"
NATIVE_LOADER_GROUP = "uimod_bootstrap_native"
# Default group set for the pristine base: the native DLL loader (movie player
# lives in uimod.dll) + base-game bugfixes that are resolution/base-independent.
# win11_24h2_filelock_fix: the CRT file-lock sites + the 0x668200 cave region are
# byte-identical across the PRACX and pristine bases, so the same group applies.
PRISTINE_GROUPS = [NATIVE_LOADER_GROUP, "credits_menu_music_dedupe",
                   "win11_24h2_filelock_fix", "save_header_init"]

PLACEHOLDER_RE = re.compile(r"^\{(rel32|abs32):([A-Za-z_][A-Za-z0-9_]*)\}$")


# ---------------------------------------------------------------------------
# Multi-target resolution (patches.yaml schema 0.3).
#
# The constants above are the legacy two-way branch. `targets:` in patches.yaml is the
# open-ended table that replaces it: adding a supported base is a data change, not a code
# change. The constants stay as aliases so --pristine and the L1 tests keep working.
# ---------------------------------------------------------------------------


class UnsupportedBase(Exception):
    """Raised when a binary's hash matches no entry in the target table.

    Carries the supported labels so callers can tell the user what IS supported instead of
    failing with a bare hash. Never swallow this into a generic "skipped" status: a player on an
    unrecognised base needs to know their configuration isn't supported, not that nothing happened.
    """

    def __init__(self, md5: str, labels: list[str]):
        self.md5 = md5
        self.labels = labels
        super().__init__(
            f"unrecognised base binary (MD5 {md5}). Supported configurations: "
            + (", ".join(labels) if labels else "<none declared>")
        )


class TargetSpec:
    """One row of the `targets:` table."""

    __slots__ = ("id", "label", "exe", "launcher", "launch", "base_md5", "base_sha256", "base_size",
                 "groups", "patched_md5", "known_patched", "pending", "companion", "requires_files",
                 "exclude_sites")

    def __init__(self, tid: str, d: dict):
        self.id = tid
        self.label = d.get("label") or tid
        self.exe = d.get("exe")
        # The program the PLAYER starts when it is not the exe itself (Thinker's thinker.exe injects
        # thinker.dll into terranx.exe); the installer's shortcut and play note point at it.
        self.launcher = d.get("launcher") or None
        self.launch = bool(d.get("launch", False))
        self.base_md5 = (d.get("base_md5") or "").lower() or None
        self.base_sha256 = (d.get("base_sha256") or "").lower() or None
        self.base_size = d.get("base_size")
        pm = d.get("patched_md5")
        self.patched_md5 = pm.lower() if isinstance(pm, str) and pm else None
        # Every build an EARLIER RELEASE shipped for this target (append-only; release_all.py
        # refuses a release that drops one). patched_md5 changes with every release, so without
        # this the build on a player's disk is "a binary we did not make" to the next release's
        # installer and its in-game update is refused.
        self.known_patched = self._normalise_md5s(tid, "known_patched", d.get("known_patched"))
        self.pending = d.get("pending") or None
        self.companion = d.get("companion") or {}
        self.groups = self._normalise_groups(tid, d.get("groups", "all"))
        # A FOLDER-DETECTED OVERLAY: an entry that shares its base hash with another target and is
        # selected only when every named file sits beside the exe (Thinker patches terranx.exe in
        # memory, so "PRACX + Thinker" has PRACX's base hash and is told apart by thinker.dll).
        self.requires_files = self._normalise_names(tid, "requires_files", d.get("requires_files"))
        # Sites left UNPATCHED on disk for this target although their group applies. Every entry is
        # a recorded user decision (the yaml comment names it): under Thinker these bytes would fail
        # Thinker's own launch-time guard, so uimod.dll writes them at run time instead.
        self.exclude_sites = self._normalise_names(tid, "exclude_sites", d.get("exclude_sites"))

    @staticmethod
    def _normalise_names(tid: str, field: str, v) -> list:
        """A list of non-empty strings, or []. A bare string is refused for the same reason as in
        `_normalise_groups`: list() would split it into characters."""
        if v is None:
            return []
        if isinstance(v, str):
            raise ValueError(f"target {tid!r}: `{field}` must be a YAML list, not the bare string "
                             f"{v!r}. Write `{field}: [{v}]`.")
        try:
            out = list(v)
        except TypeError:
            raise ValueError(f"target {tid!r}: `{field}` must be a list, got {v!r}")
        if not all(isinstance(x, str) and x.strip() for x in out):
            raise ValueError(f"target {tid!r}: `{field}` entries must be non-empty strings, got {out!r}")
        return out

    @staticmethod
    def _normalise_md5s(tid: str, field: str, v) -> list:
        """A list of 32-hex-digit MD5s, lowercased. A malformed entry is an error, not a skip: a
        typo here would make a released build "not ours" again, silently."""
        out = [x.strip().lower() for x in TargetSpec._normalise_names(tid, field, v)]
        bad = [x for x in out if not re.fullmatch(r"[0-9a-f]{32}", x)]
        if bad:
            raise ValueError(f"target {tid!r}: `{field}` entries must be MD5 hex digests, got {bad!r}")
        return out

    @property
    def builds(self) -> set:
        """Every build this project has produced for this target: this release's lock and every
        earlier release's (known_patched)."""
        return set(self.known_patched) | ({self.patched_md5} if self.patched_md5 else set())

    @staticmethod
    def _normalise_groups(tid: str, g):
        """`all`/absent -> None (no restriction). Otherwise a LIST of group ids.

        Two traps this must refuse rather than silently accept:
          * A SCALAR (`groups: uimod_bootstrap_native`) -- list() on a str yields its characters,
            so the run would be restricted to ~22 one-letter group names, every group would be
            skipped, and the exe would be "patched" with zero changes. Writing a single group
            unbracketed is the natural mistake when adding a target.
          * An EMPTY LIST (`groups: []`) -- apply_patches() gates on `if only_groups:`, so []
            is falsy and means "apply EVERY group", the exact opposite of what someone writing
            "nothing is eligible yet" intends. On an unverified base that is the worst default
            available, so it is an error.
        """
        if g is None or (isinstance(g, str) and g.strip().lower() == "all"):
            return None
        if isinstance(g, str):
            raise ValueError(
                f"target {tid!r}: `groups` must be a YAML list or the word `all`, not the bare "
                f"string {g!r}. Write `groups: [{g}]`.")
        try:
            out = list(g)
        except TypeError:
            raise ValueError(f"target {tid!r}: `groups` must be a list or `all`, got {g!r}")
        if not out:
            raise ValueError(
                f"target {tid!r}: `groups: []` is ambiguous and would apply EVERY group. Use "
                f"`pending: measurement` while the eligible set is unknown.")
        if not all(isinstance(x, str) for x in out):
            raise ValueError(f"target {tid!r}: `groups` entries must be strings, got {out!r}")
        return out

    @property
    def measured(self) -> bool:
        """False for a declared-but-unmeasured entry, which must never match a real file."""
        return self.base_md5 is not None and not self.pending

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<TargetSpec {self.id} md5={self.base_md5} launch={self.launch}>"


def builds_on_base(table: dict, base_md5: str, exclude: str = None) -> set:
    """Every build this project produced, in any release, for every SHIPPING configuration of
    `base_md5` (PRACX and PRACX + Thinker share one base) -- optionally without target `exclude`.
    The one rule for "is this exe a build of ours"; never re-derive it from patched_md5 alone."""
    out = set()
    for t in table.values():
        if t.launch and t.base_md5 == base_md5 and t.id != exclude:
            out |= t.builds
    return out


def load_targets(path: Path | str = None) -> dict[str, TargetSpec]:
    """Read the `targets:` table from patches.yaml. Empty dict if the file has none.

    Raises ValueError for a malformed table or an unparseable file -- callers surface that as an
    explained error. It used to escape as a raw AttributeError/ParserError traceback, which for
    install.py meant a shipped-yaml problem was reported to the player as an installer bug.
    """
    p = Path(path or DEFAULT_PATCHES)
    try:
        with p.open("r", encoding="utf-8") as f:
            spec = _yaml_load(f)
    except OSError as e:
        raise ValueError(f"cannot read {p}: {e}")
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise ValueError(f"{p} is not valid YAML: {e}")
    raw = (spec or {}).get("targets") or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{p}: `targets:` must be a mapping of id -> spec, got "
                         f"{type(raw).__name__}")
    return {tid: TargetSpec(tid, d or {}) for tid, d in raw.items()}


def folder_files(game_dir) -> set:
    """The lower-cased file names beside the exe -- what `resolve_target` matches `requires_files`
    against. An unreadable folder contributes nothing (the plain target then wins)."""
    try:
        return {p.name.lower() for p in Path(game_dir).iterdir() if p.is_file()}
    except OSError:
        return set()


def resolve_target(md5: str, targets: dict[str, TargetSpec] = None,
                   launch_only: bool = False, present_files=None, exe_name: str = None) -> TargetSpec:
    """Map a clean base binary's MD5 (plus what sits beside it) to its TargetSpec.

    Raises UnsupportedBase if nothing matches. `launch_only=True` additionally refuses
    dev-only entries, which is what the shipping installer wants -- the vanilla base resolves
    for `--pristine` verification but must never be offered to a player.

    `present_files` is the set of file names in the game folder (see `folder_files`). An entry
    with `requires_files` is a folder-detected OVERLAY of a plain entry with the same base hash:
    it is chosen only when every required file is present, and then it wins over the plain
    entry. With `present_files=None` (callers that have no folder: a hash alone) overlays are
    never chosen -- the same hash resolves to the plain entry, as it always did.

    `exe_name` is the name of the file being resolved. An overlay that names its `exe` is for
    THAT file only: Thinker's launcher starts a file called terranx.exe and nothing else, so a
    PRACX exe under another name (terranx_PRACX.exe beside a stock terranx.exe, the common GOG
    layout) can never run through Thinker and must get the plain build and the plain instructions
    (audit 2026-10-28: it got the Thinker build, a receipt and a play note pointing at thinker.exe,
    which started the unpatched stock exe, and every later update refused the folder). With
    `exe_name=None` (a hash with no file) the name is not checked.
    """
    tbl = targets if targets is not None else load_targets()
    want = md5.lower() if isinstance(md5, str) else ""
    have = {str(n).lower() for n in present_files} if present_files is not None else None
    name = str(exe_name).lower() if exe_name else None
    plain = None
    for t in tbl.values():
        if not (t.measured and t.base_md5 == want):
            continue
        if launch_only and not t.launch:
            # CONTINUE, not break: a dev-only entry must not short-circuit the scan. With a
            # `break` a later shipping entry sharing that base would be reported unsupported,
            # making resolution depend on dict order.
            continue
        if t.requires_files:
            if name is not None and t.exe and str(t.exe).lower() != name:
                continue                       # the overlay is for another file name
            if have is not None and all(n.lower() in have for n in t.requires_files):
                return t                       # a satisfied overlay wins outright
            continue                           # an unsatisfied one never matches
        if plain is None:
            plain = t
    if plain is not None:
        return plain
    # Advertise only MEASURED launch targets: naming a declared-but-unmeasured one tells the user
    # their configuration is supported and then refuses it.
    labels = [t.label for t in tbl.values() if t.launch and t.measured]
    raise UnsupportedBase(want, labels)


def hex_to_bytes(s: str) -> bytes:
    """Parse a whitespace-separated hex byte string into bytes.
    Refuses tokens that aren't 2-char hex (placeholders aren't allowed here)."""
    out = bytearray()
    for tok in s.split():
        if len(tok) != 2:
            raise ValueError(f"unexpected token in raw bytes: {tok!r} "
                             f"(use parse_byte_template for placeholder support)")
        out.append(int(tok, 16))
    return bytes(out)


def fmt_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


# ---------------------------------------------------------------------------
# Placeholder-aware byte templates: "B8 2C 01 00 00 E8 {rel32:scale_uniform} C3"
#
# Each `{rel32:NAME}` token is a 4-byte slot the patcher computes at apply
# time:  bytes = (target_va - (rel32_va + 4)).to_bytes(4, "little", signed=True)
# The token must come immediately after an `E8` byte (CALL near). Any other
# placement is a programming error (no other instruction uses a bare rel32).
#
# Each `{abs32:NAME}` token is a 4-byte slot holding the symbol's absolute VA
# (little-endian, unsigned) — used for absolute memory operands like
# `lock cmpxchg [var], ecx`. No E8-precedence requirement.
# ---------------------------------------------------------------------------


class ByteTemplate:
    """Parses a placeholder-bearing hex string into a list of segments.

    Each segment is either ('lit', bytes_object) or ('rel32', symbol_name).
    Offsets of placeholders within the resolved byte stream are known
    statically (placeholders are 4 bytes wide).
    """

    def __init__(self, template: str) -> None:
        self.segments: list[tuple[str, object]] = []
        self.total_length = 0
        for tok in template.split():
            m = PLACEHOLDER_RE.match(tok)
            if m:
                self.segments.append((m.group(1), m.group(2)))  # (kind, name)
                self.total_length += 4
            elif len(tok) == 2:
                b = int(tok, 16)
                self.segments.append(("lit", bytes([b])))
                self.total_length += 1
            else:
                raise ValueError(f"bad template token: {tok!r}")

    def has_placeholders(self) -> bool:
        return any(kind in ("rel32", "abs32") for kind, _ in self.segments)

    def referenced_symbols(self) -> set[str]:
        return {payload for kind, payload in self.segments if kind in ("rel32", "abs32")}

    def resolve(self, base_va: int, symbol_to_va: dict[str, int]) -> bytes:
        """Resolve the template into concrete bytes.
        `base_va` is the VA of the first byte of the resolved sequence."""
        out = bytearray()
        for kind, payload in self.segments:
            if kind == "lit":
                out.extend(payload)
                continue
            target = symbol_to_va.get(payload)
            if target is None:
                raise KeyError(f"unknown symbol referenced by template: {payload!r}")
            if kind == "abs32":
                # Absolute VA, little-endian unsigned (e.g. a [disp32] operand).
                out.extend((target & 0xFFFFFFFF).to_bytes(4, "little", signed=False))
                continue
            # rel32: the previous byte must be E8 (CALL near) — sanity check.
            if not out or out[-1] != 0xE8:
                raise ValueError(
                    f"rel32 placeholder must follow E8 (CALL); previous "
                    f"byte is 0x{out[-1] if out else 0:02X}"
                )
            rel32_va = base_va + len(out)              # VA of first byte of the 4-byte slot
            displacement = target - (rel32_va + 4)
            try:
                disp_bytes = displacement.to_bytes(4, "little", signed=True)
            except OverflowError:
                raise ValueError(
                    f"rel32 displacement to {payload} out of int32 range: {displacement}"
                )
            out.extend(disp_bytes)
        if len(out) != self.total_length:
            raise AssertionError("template length drift")
        return bytes(out)


# ---------------------------------------------------------------------------


class VaResolver:
    """Convert virtual addresses to file offsets via the PE section table."""

    def __init__(self, pe: pefile.PE) -> None:
        self.image_base = pe.OPTIONAL_HEADER.ImageBase
        # (rva_start, rva_end, file_offset_start, name) tuples
        self.sections = []
        for s in pe.sections:
            rva = s.VirtualAddress
            # Bound by the raw extent too: bytes present in the file past VirtualSize
            # are still addressable once mapped (the OS maps the page-rounded extent),
            # and _SELFMOD in particular is file-only past VirtualSize 0x415d but holds
            # PRACX's loader stub (0x668160) + our caves out to SizeOfRawData 0x5000,
            # which the apply phase bumps VirtualSize to cover. Matches the cave
            # resolver's max(VirtualSize, SizeOfRawData) extent (see verify_cave).
            extent = max(s.Misc_VirtualSize, s.SizeOfRawData)
            self.sections.append((rva, rva + extent, s.PointerToRawData,
                                  s.Name.rstrip(b"\x00").decode("ascii", "replace")))

    def to_file_offset(self, va: int) -> int | None:
        rva = va - self.image_base
        for rstart, rend, foff, _name in self.sections:
            if rstart <= rva < rend:
                return rva - rstart + foff
        return None

    def section_for(self, va: int) -> str:
        rva = va - self.image_base
        for rstart, rend, _foff, name in self.sections:
            if rstart <= rva < rend:
                return name
        return "<none>"


# ---------------------------------------------------------------------------


def load_patches(path: Path) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Returns (sites, groups, caves, symbols)."""
    with path.open("r", encoding="utf-8") as f:
        spec = _yaml_load(f)
    if spec is None:
        return [], [], [], {}
    return (
        spec.get("sites", []) or [],
        spec.get("groups", []) or [],
        spec.get("code_caves", []) or [],
        spec.get("symbols", {}) or {},
    )


def build_symbol_table(symbols: dict, caves: list[dict]) -> dict[str, int]:
    """Flatten the symbol map to {name: virtual_address}. Cave-relative
    symbols are resolved against their cave's `virtual_addr`."""
    cave_by_id = {c["id"]: c for c in caves}
    out: dict[str, int] = {}
    for name, spec in symbols.items():
        if "va" in spec:
            out[name] = int(spec["va"])
        elif "cave" in spec and "offset" in spec:
            cave_id = spec["cave"]
            cave = cave_by_id.get(cave_id)
            if cave is None:
                raise KeyError(f"symbol {name} references unknown cave {cave_id!r}")
            out[name] = int(cave["virtual_addr"]) + int(spec["offset"])
        else:
            raise ValueError(f"symbol {name} must specify `va` or `cave`+`offset`")
    return out


def verify_site(site: dict, data: bytes, resolver: VaResolver,
                symbol_to_va: dict[str, int]) -> tuple[bool, str]:
    """Verify a single site against the binary. Returns (ok, message).
    Handles `{rel32:NAME}` placeholders in original_bytes and new_bytes."""
    sid = site["id"]
    va = site["virtual_addr"]
    length = site["length"]
    anchor_len = site.get("anchor_before_length", 0)
    expected_anchor = hex_to_bytes(site.get("anchor_before", "")) if anchor_len else b""

    orig_template = ByteTemplate(site["original_bytes"])
    new_template = ByteTemplate(site["new_bytes"])

    # Internal-consistency checks.
    if orig_template.total_length != length:
        return False, (f"{sid}: original_bytes resolves to {orig_template.total_length} "
                       f"bytes, but length is {length}")
    if new_template.total_length != length:
        return False, (f"{sid}: new_bytes resolves to {new_template.total_length} "
                       f"bytes, but length is {length}")
    if len(expected_anchor) != anchor_len:
        return False, f"{sid}: anchor_before len {len(expected_anchor)} != anchor_before_length {anchor_len}"

    foff = resolver.to_file_offset(va)
    if foff is None:
        return False, f"{sid}: VA 0x{va:08x} is not within any PE section"

    # Bounds check.
    if foff + length > len(data):
        return False, f"{sid}: site extends past end of file (foff=0x{foff:x}, len={length})"
    if anchor_len and foff - anchor_len < 0:
        return False, f"{sid}: anchor extends before start of file"

    # Verify original bytes against the (resolved) template.
    try:
        expected_orig = orig_template.resolve(va, symbol_to_va)
    except (KeyError, ValueError) as e:
        return False, f"{sid}: original_bytes template error: {e}"
    actual_orig = data[foff : foff + length]
    if actual_orig != expected_orig:
        return False, (
            f"{sid} @ VA 0x{va:08x} (file 0x{foff:x}): "
            f"expected {fmt_hex(expected_orig)}, got {fmt_hex(actual_orig)}"
        )

    if anchor_len:
        actual_anchor = data[foff - anchor_len : foff]
        if actual_anchor != expected_anchor:
            return False, (
                f"{sid} @ VA 0x{va:08x}: anchor mismatch — "
                f"expected {fmt_hex(expected_anchor)}, got {fmt_hex(actual_anchor)}"
            )

    # Resolve new_bytes too so any symbol typo is caught at verify-time.
    try:
        new_template.resolve(va, symbol_to_va)
    except (KeyError, ValueError) as e:
        return False, f"{sid}: new_bytes template error: {e}"

    return True, f"{sid} @ VA 0x{va:08x} (file 0x{foff:x}, section {resolver.section_for(va)})"


def plan_new_section(cave: dict, data: bytes, pe: pefile.PE) -> tuple[bool, object]:
    """Validate that a brand-new PE section can be appended for this cave and
    compute every field the apply phase needs. Returns (True, info_dict) or
    (False, error_message).

    Used for caves with `creates_section: true` when the existing caves are
    full. Appends a 40-byte section header (PE has ample SizeOfHeaders slack),
    bumps NumberOfSections + SizeOfImage, and appends zero-filled RWX raw data
    at EOF. No existing bytes are touched except the small header fields."""
    cid = cave["id"]
    va = int(cave["virtual_addr"])
    length = int(cave["length"])
    name = str(cave.get("new_section_name", ".pcave"))
    name_b = name.encode("ascii", "replace")
    if len(name_b) > 8:
        return False, f"cave {cid}: new_section_name {name!r} exceeds 8 bytes"

    ib = pe.OPTIONAL_HEADER.ImageBase
    e_lfanew = pe.DOS_HEADER.e_lfanew
    file_align = pe.OPTIONAL_HEADER.FileAlignment
    sect_align = pe.OPTIONAL_HEADER.SectionAlignment
    size_of_headers = pe.OPTIONAL_HEADER.SizeOfHeaders
    numsec = pe.FILE_HEADER.NumberOfSections
    size_opt = pe.FILE_HEADER.SizeOfOptionalHeader

    def align_up(x, a):
        return (x + a - 1) // a * a

    sec_table_off = e_lfanew + 24 + size_opt
    new_hdr_off = sec_table_off + numsec * 40
    if new_hdr_off + 40 > size_of_headers:
        return False, (f"cave {cid}: no room for another section header "
                       f"(0x{new_hdr_off + 40:x} > SizeOfHeaders 0x{size_of_headers:x})")

    rva = va - ib
    if rva % sect_align != 0:
        return False, (f"cave {cid}: VA 0x{va:08x} (RVA 0x{rva:x}) is not aligned "
                       f"to SectionAlignment 0x{sect_align:x}")
    end_rva = 0
    for s in pe.sections:
        end_rva = max(end_rva, s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData))
    end_rva = align_up(end_rva, sect_align)
    if rva < end_rva:
        return False, (f"cave {cid}: RVA 0x{rva:x} overlaps the existing image "
                       f"(first free RVA is 0x{end_rva:x})")

    rawptr = align_up(len(data), file_align)
    rawsize = align_up(length, file_align)
    new_sizeofimage = align_up(rva + length, sect_align)

    return True, {
        "cid": cid,
        "name_b": name_b,
        "header_offset": new_hdr_off,
        "numsec_off": e_lfanew + 6,
        "old_numsec": numsec,
        "sizeofimage_off": e_lfanew + 24 + 56,  # PE32 optional-header SizeOfImage
        "new_sizeofimage": new_sizeofimage,
        "rva": rva,
        "rawptr": rawptr,
        "rawsize": rawsize,
        "vsize": length,
        "cave_va": va,
        "characteristics": 0xE0000020,  # CODE | EXECUTE | READ | WRITE
    }


def verify_cave(cave: dict, data: bytes, resolver: VaResolver, pe: pefile.PE,
                symbol_to_va: dict[str, int]) -> tuple[bool, str]:
    """Verify a single code cave: all bytes in the reserved region must be
    in `expected_padding`, and the planned contents must fit without overlap.
    Also pre-resolves cave-content templates so symbol typos surface here.

    If the cave sets `extends_section_virtual_size: true`, the cave is
    allowed to extend past the host section's current VirtualSize — the
    apply phase will bump VirtualSize to cover it. Cave bytes must still
    be readable from file (within SizeOfRawData)."""
    cid = cave["id"]
    va = int(cave["virtual_addr"])
    length = int(cave["length"])
    expected_padding = set(int(b) for b in cave.get("expected_padding", [0x00]))
    extends = bool(cave.get("extends_section_virtual_size", False))
    section_name = cave.get("section", None)

    # A `creates_section` cave doesn't exist in `data` yet — we'll append a
    # brand-new PE section for it. Validate the append is possible, then only
    # resolve/fit-check the contents (no padding scan).
    if bool(cave.get("creates_section", False)):
        ok, info = plan_new_section(cave, data, pe)
        if not ok:
            return False, info  # info is the error string
        cave["_pending_section_creation"] = info
        contents = sorted(cave.get("contents", []) or [], key=lambda c: int(c["offset"]))
        prev_end = 0
        for c in contents:
            off = int(c["offset"])
            if off < prev_end:
                return False, (f"cave {cid}: content {c['id']!r} at +0x{off:02X} "
                               f"overlaps previous content (ends at +0x{prev_end:02X})")
            try:
                resolved = ByteTemplate(c["bytes"]).resolve(va + off, symbol_to_va)
            except (KeyError, ValueError) as e:
                return False, f"cave {cid}: content {c['id']!r} template error: {e}"
            if off + len(resolved) > length:
                return False, (f"cave {cid}: content {c['id']!r} extends past cave "
                               f"({off + len(resolved)} > {length})")
            prev_end = off + len(resolved)
        return True, (f"cave {cid} @ VA 0x{va:08x}: NEW section "
                      f"{info['name_b'].decode('ascii', 'replace')!r} "
                      f"(RVA 0x{info['rva']:x}, raw 0x{info['rawptr']:x}+0x{info['rawsize']:x}, "
                      f"{len(contents)} content(s)); NumberOfSections "
                      f"{info['old_numsec']}->{info['old_numsec'] + 1}, "
                      f"SizeOfImage -> 0x{info['new_sizeofimage']:x}")

    foff = resolver.to_file_offset(va)
    if foff is None and extends and section_name is not None:
        # Cave is past current VirtualSize; we'll bump it. Compute file
        # offset directly from the section header, bounded by SizeOfRawData.
        sect = next((s for s in pe.sections
                     if s.Name.rstrip(b"\x00").decode("ascii", "replace") == section_name), None)
        if sect is None:
            return False, f"cave {cid}: section {section_name!r} not found"
        sect_va_start = sect.VirtualAddress + pe.OPTIONAL_HEADER.ImageBase
        if va < sect_va_start:
            return False, f"cave {cid}: VA 0x{va:08x} is before section start 0x{sect_va_start:08x}"
        within = (va - sect_va_start) + length
        if within > sect.SizeOfRawData:
            return False, (f"cave {cid}: cave extends past SizeOfRawData "
                           f"({within} > {sect.SizeOfRawData})")
        foff = sect.PointerToRawData + (va - sect_va_start)
    if foff is None:
        return False, f"cave {cid}: VA 0x{va:08x} is not within any PE section"
    if foff + length > len(data):
        return False, f"cave {cid}: extends past end of file"

    region = data[foff : foff + length]
    for i, b in enumerate(region):
        if b not in expected_padding:
            return False, (f"cave {cid} collision at +0x{i:03X} (VA 0x{va + i:08x}): "
                           f"got 0x{b:02X}, expected one of "
                           f"{{{', '.join(f'0x{x:02X}' for x in sorted(expected_padding))}}}")

    # If extends_section_virtual_size, validate the bump is safe.
    section_ext_info: dict | None = None
    if extends:
        if section_name is None:
            return False, f"cave {cid}: extends_section_virtual_size=true requires `section` field"
        sect = next((s for s in pe.sections
                     if s.Name.rstrip(b"\x00").decode("ascii", "replace") == section_name), None)
        if sect is None:
            return False, f"cave {cid}: section {section_name!r} not found"
        sect_va_start = sect.VirtualAddress + pe.OPTIONAL_HEADER.ImageBase
        cur_vsize = sect.Misc_VirtualSize
        raw_size = sect.SizeOfRawData
        required_vsize = (va + length) - sect_va_start
        if required_vsize > raw_size:
            return False, (f"cave {cid}: required VirtualSize 0x{required_vsize:x} exceeds "
                           f"SizeOfRawData 0x{raw_size:x} for section {section_name!r}")
        # Check no overlap with next section.
        next_sect_starts = [s.VirtualAddress for s in pe.sections
                            if s.VirtualAddress > sect.VirtualAddress]
        if next_sect_starts:
            next_start = min(next_sect_starts)
            available = next_start - sect.VirtualAddress
            if required_vsize > available:
                return False, (f"cave {cid}: required VirtualSize 0x{required_vsize:x} "
                               f"would overlap next section (max 0x{available:x})")
        if required_vsize > cur_vsize:
            # Section header VirtualSize field is at section_header_file_offset + 8 (4 bytes LE).
            shdr_off = sect.get_file_offset()
            section_ext_info = {
                "section_name": section_name,
                "header_offset": shdr_off,
                "old_vsize": cur_vsize,
                "new_vsize": required_vsize,
            }
            # Stash on the cave dict for the apply phase. Cave dicts are
            # mutable per-run state from yaml.safe_load, so this is fine.
            cave["_pending_section_extension"] = section_ext_info

    # Verify contents fit and don't overlap, and resolve templates.
    contents = cave.get("contents", []) or []
    contents = sorted(contents, key=lambda c: int(c["offset"]))
    prev_end = 0
    for c in contents:
        off = int(c["offset"])
        if off < prev_end:
            return False, (f"cave {cid}: content {c['id']!r} at +0x{off:02X} "
                           f"overlaps previous content (ends at +0x{prev_end:02X})")
        tmpl = ByteTemplate(c["bytes"])
        try:
            resolved = tmpl.resolve(va + off, symbol_to_va)
        except (KeyError, ValueError) as e:
            return False, f"cave {cid}: content {c['id']!r} template error: {e}"
        if off + len(resolved) > length:
            return False, (f"cave {cid}: content {c['id']!r} extends past cave "
                           f"({off + len(resolved)} > {length})")
        prev_end = off + len(resolved)

    msg = f"cave {cid} @ VA 0x{va:08x} (file 0x{foff:x}, {len(contents)} content(s))"
    if section_ext_info is not None:
        msg += (f"; will bump {section_ext_info['section_name']}.VirtualSize "
                f"0x{section_ext_info['old_vsize']:x} -> 0x{section_ext_info['new_vsize']:x}")
    return True, msg


def apply_patches(target: Path, patches_path: Path, do_apply: bool,
                  only_groups: list | None = None,
                  expected_md5: str = EXPECTED_MD5,
                  expected_size: int = EXPECTED_SIZE,
                  spec: "TargetSpec" = None, summary=None) -> int:
    """Verify and (optionally) apply the patch set to one binary.

    `spec` is the preferred way in: it carries the baseline hash/size and the group selection for
    ONE supported base, so the same code path serves every target instead of a hardcoded pair.
    The loose `expected_*` arguments remain for the legacy single-baseline callers.

    THE BASELINE ABORT BELOW IS DELIBERATE and stays: every site's `original_bytes` and every
    cave's `expected_padding` are written against one specific binary, so operating on different
    bytes is how an install gets corrupted. What `spec` changes is that the baseline is now
    DECLARED per target rather than assumed, which is what makes a new base a data change.

    `summary`: when given, the per-site narration (thousands of lines) is suppressed and each
    phase reports ONE line through `summary(status, text)` -- status "ok" / "error" / "skip" /
    "info" -- plus the sites that failed (with their bytes) or were skipped (names only). This
    is what the end-user installer prints; the developer CLI keeps the full transcript.
    """
    def v(*parts, **kw):
        """Verbose narration: the developer transcript only."""
        if summary is None:
            print(*parts, **kw)

    def err(text):
        """An error: red through `summary`, plain in the transcript."""
        if summary is not None:
            summary("error", text)
        else:
            print(text)

    if spec is not None:
        # A target with no recorded patched_md5 has never produced a verified output, so it is
        # DRY-RUN ONLY. This is what makes discovery safe: to measure which groups survive on a
        # new base you register its hash and dry-run it, and the entry cannot be written to
        # until someone records the hash the run actually produced -- a deliberate, reviewed act,
        # exactly like updating the build lock. Registering a base with `groups: all` to find out
        # what applies therefore cannot turn into an --apply against an unverified binary.
        # A spec MUST declare its own baseline. Falling back to the PRACX constants when a target
        # omits base_md5/base_size was a trap: `--target-id thinker` against a PRACX binary
        # verified it against PRACX's hash while calling it "thinker", then told the operator to
        # record the PRACX build lock as Thinker's lock -- at which point the per-target baseline
        # is gone entirely.
        if not spec.base_md5 or not spec.base_size:
            err(f"ERROR: target {spec.id!r} ({spec.label}) declares no base_md5/base_size, so "
                  f"there is nothing to verify against.")
            err("       Hash the real binary and record base_md5 + base_size for it first;")
            err("       until then this target cannot be used, in either mode.")
            return 2
        if spec.pending:
            err(f"ERROR: target {spec.id!r} ({spec.label}) is marked `pending: {spec.pending}` "
                  f"-- it has not been measured on real bytes.")
            err("       Remove the `pending` marker once base_md5/base_size are recorded.")
            return 2
        # A target with no recorded patched_md5 has never produced a verified output, so it is
        # DRY-RUN ONLY -- see the docstring. `launch: false` targets are exempt: they are dev
        # verification tools that never reach a player, so the rule protects nobody there and
        # would only break the workflow they exist for (e.g. --pristine --apply).
        if do_apply and not spec.patched_md5 and spec.launch:
            err(f"ERROR: target {spec.id!r} ({spec.label}) has no recorded patched_md5 -- it "
                  f"has never produced a verified output.")
            err("       Dry-run is allowed (that is how you measure group eligibility);")
            err("       --apply is refused until a patched_md5 is recorded for it.")
            return 2
        expected_md5 = spec.base_md5
        expected_size = spec.base_size
        if only_groups is None:
            only_groups = spec.groups

    v(f"Target  : {target}")
    v(f"Patches : {patches_path}")
    if spec is not None:
        v(f"Base    : {spec.id}  ({spec.label})")
    v()

    if not target.exists():
        err(f"ERROR: target file not found")
        return 1
    if not patches_path.exists():
        err(f"ERROR: patches file not found")
        return 1

    data = target.read_bytes()
    actual_size = len(data)
    actual_md5 = hashlib.md5(data).hexdigest()
    v(f"Size    : {actual_size:,} bytes  (expected {expected_size:,})")
    v(f"MD5     : {actual_md5}  (expected {expected_md5})")

    if actual_size != expected_size:
        err(f"ERROR: size mismatch. Refusing to operate on an unrecognized binary.")
        return 2
    if actual_md5 != expected_md5:
        err(f"ERROR: MD5 mismatch. Refusing to operate on an unrecognized binary.")
        return 2

    pe = pefile.PE(data=data, fast_load=True)
    resolver = VaResolver(pe)
    v(f"ImageBase: 0x{resolver.image_base:08x}")

    sites, groups, caves, symbols_spec = load_patches(patches_path)
    try:
        symbol_to_va = build_symbol_table(symbols_spec, caves)
    except (KeyError, ValueError) as e:
        err(f"ERROR building symbol table: {e}")
        return 4

    confirmed_sites = [s for s in sites if s.get("status") == "confirmed"]
    candidate_sites = [s for s in sites if s.get("status") == "candidate"]
    skipped_sites = [s for s in sites if s.get("status") == "skip"]
    partial_sites = [s for s in sites if s.get("status") == "partial"]

    site_by_id = {s["id"]: s for s in sites}
    group_by_id = {g["id"]: g for g in groups}

    # Optional restriction: apply ONLY the named groups (and the caves they use).
    # Standalone confirmed sites and every other group are skipped. Lets us put,
    # say, just the Win11 file-lock crash fix onto a clean/pristine binary:
    #   --groups win11_24h2_filelock_fix
    only_set: set | None = None
    if only_groups:
        only_set = set(only_groups)
        unknown = sorted(only_set - set(group_by_id))
        if unknown:
            err(f"ERROR: unknown group(s) in --groups: {', '.join(unknown)}")
            err(f"       known groups: {', '.join(sorted(group_by_id))}")
            return 4
        v(f"Restricting to group(s): {', '.join(sorted(only_set))}")
        v("  (standalone sites and all other groups will be left unpatched)")
        v()

    # Sites this target leaves UNPATCHED on disk although their group applies (each a recorded user
    # decision in the yaml). They still verify -- the bytes are the clean base's -- and their group
    # stays eligible; they are simply not written. uimod.dll applies them at run time, after the
    # other patcher (Thinker) has run its own launch-time guards over the clean bytes.
    excluded: set = set(spec.exclude_sites) if spec is not None else set()
    if excluded:
        unknown_x = sorted(excluded - set(site_by_id))
        if unknown_x:
            err(f"ERROR: target {spec.id!r} excludes unknown site(s): {', '.join(unknown_x)}")
            return 4
        v(f"Excluded on disk for target {spec.id!r} (applied at run time by uimod.dll): "
          f"{', '.join(sorted(excluded))}")
        v()

    def in_scope(site: dict) -> bool:
        """Whether a site is eligible to be written under the current selection.
        With no --groups restriction, every site is in scope (default behavior)."""
        if site["id"] in excluded:
            return False
        if only_set is None:
            return True
        return site.get("group") in only_set

    def is_skippable(site: dict) -> bool:
        """A site is skippable (non-critical) if it or its group says so.
        Skippable patches that fail verification — e.g. because another mod
        already modified that code — are calmly skipped rather than treated as
        a hard failure that blocks the rest of the patch set."""
        if site.get("skippable"):
            return True
        gid = site.get("group")
        return bool(gid and group_by_id.get(gid, {}).get("skippable"))

    v(f"Sites    : {len(sites)} total ({len(confirmed_sites)} confirmed, "
          f"{len(candidate_sites)} candidate, {len(skipped_sites)} skip, "
          f"{len(partial_sites)} partial)")
    v(f"Groups   : {len(groups)}")
    v(f"Caves    : {len(caves)}")
    v(f"Symbols  : {len(symbol_to_va)}")
    v()

    if not confirmed_sites and not groups:
        v("Nothing to apply -- no confirmed sites and no groups.")
        return 0

    # -------- Verify caves --------
    cave_ok: dict[str, tuple[bool, str]] = {}
    if caves:
        v("=== Cave verification ===")
        for cave in caves:
            ok, msg = verify_cave(cave, data, resolver, pe, symbol_to_va)
            marker = "[ok]  " if ok else "[FAIL]"
            v(f"  {marker} {msg}")
            cave_ok[cave["id"]] = (ok, msg)
        v()
        if summary is not None:
            fails = [m for ok_, m in cave_ok.values() if not ok_]
            if fails:
                summary("error", f"Code caves: ERROR ({len(fails)}/{len(cave_ok)} failed)")
                for m in fails:
                    summary("error", "  " + m)
            else:
                summary("ok", f"Code caves: SUCCESS ({len(cave_ok)}/{len(cave_ok)} ready)")

    # -------- Verify sites --------
    v("=== Site verification ===")
    site_ok: dict[str, tuple[bool, str]] = {}
    for site in confirmed_sites:
        ok, msg = verify_site(site, data, resolver, symbol_to_va)
        if ok:
            marker = "[ok]  "
        elif is_skippable(site):
            marker = "[skip]"
            msg = f"{msg}  — skippable; not applied (already modified by another mod?)"
        else:
            marker = "[FAIL]"
        v(f"  {marker} {msg}")
        site_ok[site["id"]] = (ok, msg)
    if summary is not None:
        s_ok = sum(1 for ok_, _ in site_ok.values() if ok_)
        s_skip = [sid for sid, (ok_, _) in site_ok.items()
                  if not ok_ and is_skippable(site_by_id[sid])]
        s_fail = [sid for sid, (ok_, _) in site_ok.items()
                  if not ok_ and not is_skippable(site_by_id[sid])]
        if s_fail:
            summary("error", f"Patch sites: ERROR ({len(s_fail)}/{len(site_ok)} failed, "
                             f"{len(s_skip)} skipped)")
            for sid in s_fail:
                summary("error", "  " + site_ok[sid][1])
        else:
            summary("ok", f"Patch sites: SUCCESS ({s_ok}/{len(site_ok)} verified, "
                          f"{len(s_skip)} skipped)")
        if s_skip:
            summary("skip", "  skipped: " + ", ".join(s_skip))
            summary("info", "  Skipped sites are expected: another program or an earlier "
                            "install already changed those bytes, and they are left alone.")

    # -------- Decide group eligibility --------
    v()
    v("=== Group eligibility ===")
    group_ok: dict[str, bool] = {}
    group_reasons: dict[str, list] = {}
    for grp in groups:
        gid = grp["id"]
        members = grp.get("members", []) or []
        cave_refs = grp.get("code_caves", []) or []
        reasons: list[str] = []

        for m in members:
            if m not in site_by_id:
                reasons.append(f"unknown member site {m!r}")
                continue
            if site_by_id[m].get("status") != "confirmed":
                reasons.append(f"member {m!r} not confirmed "
                               f"(status={site_by_id[m].get('status')!r})")
                continue
            ok, msg = site_ok.get(m, (False, "(not verified)"))
            if not ok:
                reasons.append(f"member {m!r} verification failed")

        for cr in cave_refs:
            cok, _cmsg = cave_ok.get(cr, (False, f"unknown cave {cr!r}"))
            if not cok:
                reasons.append(f"cave {cr!r} not ready")

        if reasons:
            group_ok[gid] = False
            group_reasons[gid] = reasons
            if grp.get("skippable"):
                v(f"  [skip] group {gid}: not applied -- {'; '.join(reasons)} "
                      f"(skippable; left to existing mod)")
            else:
                v(f"  [FAIL] group {gid}: {'; '.join(reasons)}")
        else:
            group_ok[gid] = True
            v(f"  [ok]   group {gid}: {len(members)} site(s), "
                  f"{len(cave_refs)} cave(s)")

    v()
    if summary is not None:
        g_skip = [g["id"] for g in groups if not group_ok.get(g["id"]) and g.get("skippable")]
        g_fail = [g["id"] for g in groups if not group_ok.get(g["id"]) and not g.get("skippable")]
        g_ok = sum(1 for g in groups if group_ok.get(g["id"]))
        if g_fail:
            summary("error", f"Patch groups: ERROR ({len(g_fail)}/{len(groups)} failed, "
                             f"{len(g_skip)} skipped)")
            for gid in g_fail:
                summary("error", f"  {gid}: " + "; ".join(group_reasons.get(gid, [])))
        else:
            summary("ok", f"Patch groups: SUCCESS ({g_ok}/{len(groups)} eligible, "
                          f"{len(g_skip)} skipped)")
        # Skipped GROUP ids are not listed: a player cannot act on them, and the sites that
        # caused the skip were already named above.

    # -------- Decide which sites apply --------
    apply_set: list[dict] = []
    deferred_sites: list[str] = []
    for site in confirmed_sites:
        sid = site["id"]
        if not in_scope(site):
            continue
        if not site_ok.get(sid, (False, ""))[0]:
            continue
        gid = site.get("group")
        if gid is None:
            apply_set.append(site)
            continue
        if not group_ok.get(gid, False):
            v(f"  [skip] {sid}: deferred -- group {gid} not eligible")
            deferred_sites.append(sid)
            continue
        apply_set.append(site)

    # Caves to write: any cave referenced by an eligible group.
    caves_to_write: list[dict] = []
    for grp in groups:
        if only_set is not None and grp["id"] not in only_set:
            continue
        if not group_ok.get(grp["id"], False):
            continue
        for cr in grp.get("code_caves", []) or []:
            cave = next((c for c in caves if c["id"] == cr), None)
            if cave is not None and cave not in caves_to_write:
                caves_to_write.append(cave)

    v(f"Will write: {len(apply_set)} site(s), {len(caves_to_write)} cave(s)")

    # Classify verification failures. Skippable failures (e.g. a site another
    # mod already modified) are NOT hard errors — they're calmly left as-is.
    # Only critical (non-skippable) failures block the whole apply.
    critical_site_failures = [sid for sid, (ok, _) in site_ok.items()
                              if not ok and not is_skippable(site_by_id[sid])
                              and in_scope(site_by_id[sid])]
    skipped_site_failures = [sid for sid, (ok, _) in site_ok.items()
                             if not ok and is_skippable(site_by_id[sid])
                             and in_scope(site_by_id[sid])]
    if only_set is None:
        cave_failures = [cid for cid, (ok, _) in cave_ok.items() if not ok]
    else:
        inscope_caves = set()
        for grp in groups:
            if grp["id"] in only_set:
                inscope_caves.update(grp.get("code_caves", []) or [])
        cave_failures = [cid for cid, (ok, _) in cave_ok.items()
                         if not ok and cid in inscope_caves]

    if skipped_site_failures:
        v(f"Note      : {len(skipped_site_failures)} skippable site(s) not applied "
              f"(already modified by another mod, or handled elsewhere) — this is fine.")

    if critical_site_failures or cave_failures:
        v()
        err(f"ERROR: {len(critical_site_failures)} critical site failure(s), "
              f"{len(cave_failures)} cave failure(s). No changes written.")
        return 3

    # -------- Build the patched image --------
    # Built for BOTH paths. A dry run that can report the hash it WOULD produce is what breaks
    # the deadlock created by the dry-run-only rule above: you cannot record a target's
    # patched_md5 without applying, and you cannot apply without the patched_md5. Now the loop is
    # dry-run -> read the prospective hash -> record it -> apply (which re-verifies the output).
    # That is strictly safer than applying blind to find out, and it is exactly what the Thinker
    # sweep needs. Nothing is written to disk until after the do_apply check further down.
    v()
    v("=== Apply ===" if do_apply else "=== Plan (dry run -- nothing will be written) ===")
    buf = bytearray(data)

    # Caves first (so any sites that reference cave-resident symbols see
    # finished bytes if we ever read back from buf).
    for cave in caves_to_write:
        cva = int(cave["virtual_addr"])
        section_name = cave.get("section")
        # Apply any pending section-VirtualSize bump first so file offsets
        # inside the (newly-extended) loaded region resolve cleanly.
        ext = cave.get("_pending_section_extension")
        if ext is not None:
            shdr_off = ext["header_offset"]
            new_vsize = ext["new_vsize"]
            buf[shdr_off + 8 : shdr_off + 12] = new_vsize.to_bytes(4, "little")
            v(f"  ext   {ext['section_name']}.VirtualSize bumped to 0x{new_vsize:x} "
                  f"(was 0x{ext['old_vsize']:x}; section header at file 0x{shdr_off:x})")
        # Append a brand-new section if requested, BEFORE writing its contents.
        newsec = cave.get("_pending_section_creation")
        if newsec is not None:
            rawptr, rawsize = newsec["rawptr"], newsec["rawsize"]
            if len(buf) < rawptr:                      # pad to file-aligned EOF
                buf.extend(b"\x00" * (rawptr - len(buf)))
            buf.extend(b"\x00" * rawsize)              # the new section body (zero-filled)
            hdr = bytearray(40)
            hdr[0:8]   = newsec["name_b"].ljust(8, b"\x00")
            hdr[8:12]  = newsec["vsize"].to_bytes(4, "little")    # VirtualSize
            hdr[12:16] = newsec["rva"].to_bytes(4, "little")      # VirtualAddress
            hdr[16:20] = rawsize.to_bytes(4, "little")            # SizeOfRawData
            hdr[20:24] = rawptr.to_bytes(4, "little")             # PointerToRawData
            hdr[36:40] = newsec["characteristics"].to_bytes(4, "little")
            ho = newsec["header_offset"]
            buf[ho:ho + 40] = hdr
            buf[newsec["numsec_off"]:newsec["numsec_off"] + 2] = \
                (newsec["old_numsec"] + 1).to_bytes(2, "little")
            buf[newsec["sizeofimage_off"]:newsec["sizeofimage_off"] + 4] = \
                newsec["new_sizeofimage"].to_bytes(4, "little")
            v(f"  newsec {cave['id']}: +section "
                  f"{newsec['name_b'].decode('ascii', 'replace')!r} RVA 0x{newsec['rva']:x} "
                  f"raw 0x{rawptr:x}+0x{rawsize:x}; NumberOfSections "
                  f"{newsec['old_numsec']}->{newsec['old_numsec'] + 1}, "
                  f"SizeOfImage->0x{newsec['new_sizeofimage']:x} (hdr@0x{ho:x})")
        # Compute file-offset base for this cave. Use section info directly
        # if the cave's start VA is past the (original) VirtualSize.
        sect = None
        if section_name:
            sect = next((s for s in pe.sections
                         if s.Name.rstrip(b"\x00").decode("ascii", "replace") == section_name), None)
        for content in sorted(cave.get("contents", []) or [], key=lambda c: int(c["offset"])):
            off = int(content["offset"])
            content_va = cva + off
            tmpl = ByteTemplate(content["bytes"])
            resolved = tmpl.resolve(content_va, symbol_to_va)
            foff = resolver.to_file_offset(content_va)
            if foff is None and newsec is not None:
                foff = newsec["rawptr"] + (content_va - cva)
            elif foff is None and sect is not None:
                sect_va_start = sect.VirtualAddress + pe.OPTIONAL_HEADER.ImageBase
                foff = sect.PointerToRawData + (content_va - sect_va_start)
            buf[foff : foff + len(resolved)] = resolved
            v(f"  cave  {cave['id']}/{content['id']} @ VA 0x{content_va:08x} "
                  f"(file 0x{foff:x}, {len(resolved)} bytes): {fmt_hex(resolved)}")

    # Then sites.
    for site in apply_set:
        va = int(site["virtual_addr"])
        new_template = ByteTemplate(site["new_bytes"])
        resolved = new_template.resolve(va, symbol_to_va)
        foff = resolver.to_file_offset(va)
        buf[foff : foff + len(resolved)] = resolved
        gtag = f"  [group {site['group']}]" if site.get("group") else ""
        v(f"  site  {site['id']} @ VA 0x{va:08x} (file 0x{foff:x}): "
              f"{fmt_hex(resolved)}{gtag}")

    new_md5 = hashlib.md5(bytes(buf)).hexdigest()

    # Does the recorded lock apply to THIS run? Only when the full group selection the target
    # declares was used -- an explicit --groups produces a legitimately different binary, so
    # comparing it to the lock would be meaningless.
    groups_as_declared = (spec is not None
                          and (only_groups == spec.groups
                               or (only_groups is None and spec.groups is None)))
    lock_applies = spec is not None and bool(spec.patched_md5) and groups_as_declared

    if not do_apply:
        v()
        v("DRY RUN -- all verifications passed. Nothing was written.")
        v(f"Would produce MD5 : {new_md5}")
        if spec is not None and not spec.patched_md5:
            v(f"  Record this as targets.{spec.id}.patched_md5 in {patches_path.name} to "
                  f"allow --apply for this base.")
        elif lock_applies and new_md5 != spec.patched_md5:
            v(f"  WARNING: differs from the recorded lock {spec.patched_md5} -- the patch set "
                  f"has changed since that hash was taken.")
        elif spec is not None and not groups_as_declared:
            v(f"  (an explicit --groups was used, so target {spec.id!r}'s recorded lock "
                  f"{spec.patched_md5} does not apply to this output)")
        return 0

    # The apply path must check the lock too, not just dry-run. Writing a binary whose hash
    # disagrees with the recorded lock -- silently, returning 0 -- is how an unmeasured patch set
    # ships. Checked BEFORE the write, so a mismatch changes nothing on disk.
    if lock_applies and new_md5 != spec.patched_md5:
        v()
        err(f"ERROR: this run would produce {new_md5}, but target {spec.id!r} is locked to "
              f"{spec.patched_md5}.")
        err("       Nothing was written. Either the patch set changed (update the lock "
              "deliberately, after review) or the wrong base was selected.")
        return 4

    if spec is not None and not groups_as_declared:
        v()
        v(f"NOTE: an explicit --groups was used, so this output is NOT target {spec.id!r}'s "
              f"locked build.")
        v(f"      Expect {new_md5}, not the recorded {spec.patched_md5}.")

    backup = target.with_suffix(target.suffix + ".bak")
    if backup.exists():
        v(f"\nNOTE: backup already exists at {backup} -- preserving the existing one (not overwriting).")
        if summary is not None:
            summary("info", f"Backup: {backup.name} (kept from an earlier install)")
    else:
        shutil.copy2(target, backup)
        v(f"\nBackup written: {backup}")
        if summary is not None:
            summary("info", f"Backup: {backup.name}")

    tmp = target.with_suffix(target.suffix + ".patching")
    tmp.write_bytes(bytes(buf))
    tmp.replace(target)
    v(f"Patched binary written: {target}")
    v()
    v(f"New MD5 : {new_md5}")
    if summary is not None:
        skipped_n = len(skipped_site_failures) + len(deferred_sites)
        summary("ok", f"Patching: SUCCESS ({len(apply_set)}/{len(apply_set) + skipped_n} sites "
                      f"patched, {skipped_n} skipped, {len(caves_to_write)} code cave(s) written)")
    return 0


def restore(target: Path) -> int:
    backup = target.with_suffix(target.suffix + ".bak")
    if not backup.exists():
        print(f"ERROR: no backup at {backup}")
        return 1
    shutil.copy2(backup, target)
    print(f"Restored {target} from {backup}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SMACX UI scaling patcher")
    ap.add_argument("--target", default=DEFAULT_TARGET, help="Path to terranx.exe")
    ap.add_argument("--patches", default=DEFAULT_PATCHES, help="Path to patches.yaml")
    ap.add_argument("--apply", action="store_true", help="Commit changes (default: dry-run)")
    ap.add_argument("--restore", action="store_true", help="Restore from backup and exit")
    ap.add_argument("--groups", default=None,
                    help="Comma/space-separated group name(s) to apply EXCLUSIVELY; all "
                         "standalone sites and other groups are skipped. E.g. "
                         "--groups win11_24h2_filelock_fix  (put only the crash fix on a "
                         "clean binary). Combine with --target to patch a separate copy.")
    ap.add_argument("--target-id", default=None, metavar="ID",
                    help="Which base from the patches file's `targets:` table to verify against "
                         "(e.g. pracx, vanilla, thinker). Omit to auto-detect by hashing "
                         "--target. Use --list-targets to see them.")
    ap.add_argument("--list-targets", action="store_true",
                    help="Print the target table from --patches and exit.")
    ap.add_argument("--pristine", action="store_true",
                    help="Deprecated alias for --target-id vanilla (the un-PRACX'd terranx.exe). "
                         f"Defaults --target to <game dir>\\{PRISTINE_EXE}.")
    args = ap.parse_args()

    only_groups = None
    if args.groups:
        only_groups = [g for g in re.split(r"[,\s]+", args.groups.strip()) if g]

    if args.target_id and args.pristine:
        print("ERROR: --target-id and --pristine both select a base; pass only one. "
              "(--pristine is the deprecated alias for --target-id vanilla.)")
        return 2

    patches = Path(args.patches)
    if not patches.is_file():
        print(f"ERROR: patches file not found: {patches}")
        return 1

    # Parse the patches file ONCE: it is 1.77 MB, and we need both the legacy `target:` block and
    # the `targets:` table out of it.
    try:
        with patches.open("r", encoding="utf-8") as f:
            doc = _yaml_load(f) or {}
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        print(f"ERROR: {patches} is not valid YAML: {e}")
        return 1
    except OSError as e:
        print(f"ERROR: cannot read {patches}: {e}")
        return 1
    if not isinstance(doc, dict):
        print(f"ERROR: {patches} must contain a mapping at the top level")
        return 1
    tgt_spec = doc.get("target", {}) or {}
    raw_targets = doc.get("targets") or {}
    if not isinstance(raw_targets, dict):
        print(f"ERROR: {patches}: `targets:` must be a mapping of id -> spec, got "
              f"{type(raw_targets).__name__}")
        return 2
    try:
        table = {tid: TargetSpec(tid, d or {}) for tid, d in raw_targets.items()}
    except ValueError as e:
        print(f"ERROR: bad `targets:` table in {patches}: {e}")
        return 2

    if args.list_targets:
        if not table:
            print(f"{patches} has no `targets:` table (legacy single-baseline spec).")
            return 0
        print(f"{'id':<16} {'ship':<5} {'writable':<9} base_md5                          label")
        for tid, t in table.items():
            base = t.base_md5 or "<unmeasured>"
            print(f"{tid:<16} {'yes' if t.launch else 'no':<5} "
                  f"{'yes' if t.patched_md5 else 'DRY-RUN':<9} {base:<33} {t.label}")
        return 0

    if args.pristine and args.target == DEFAULT_TARGET:
        args.target = str(config.game_dir(required=False) / PRISTINE_EXE)
    target = Path(args.target)

    if args.restore:
        return restore(target)

    # Resolve the base: explicit id > --pristine alias > auto-detect by hash.
    spec = None
    if args.target_id:
        spec = table.get(args.target_id)
        if spec is None:
            print(f"ERROR: unknown --target-id {args.target_id!r}. "
                  f"Known: {', '.join(table) or '<none>'}")
            return 2
    elif args.pristine:
        spec = table.get("vanilla")
    elif table and target.is_file():
        try:
            # The folder decides between a plain base and its overlay (PRACX vs PRACX + Thinker share
            # one hash; thinker.dll beside the exe tells them apart).
            spec = resolve_target(hashlib.md5(target.read_bytes()).hexdigest(), table,
                                  present_files=folder_files(target.parent), exe_name=target.name)
        except (UnsupportedBase, OSError):
            spec = None   # fall through to the legacy block; the baseline check will explain

    if spec is not None:
        return apply_patches(target, patches, args.apply, only_groups=only_groups, spec=spec)

    # Legacy single-baseline path: the patches file's own `target:` block (patches_prax.yaml
    # targets prax.dll and has no `targets:` table), with the module constants as a last resort.
    expected_md5 = PRISTINE_MD5 if args.pristine else EXPECTED_MD5
    if args.pristine:
        expected_md5 = tgt_spec.get("pristine_md5", expected_md5)
        if only_groups is None:
            only_groups = list(PRISTINE_GROUPS)
    else:
        expected_md5 = tgt_spec.get("md5", expected_md5)
    expected_size = int(tgt_spec.get("size", EXPECTED_SIZE))

    return apply_patches(target, patches, args.apply, only_groups=only_groups,
                         expected_md5=expected_md5, expected_size=expected_size)


if __name__ == "__main__":
    sys.exit(main())
