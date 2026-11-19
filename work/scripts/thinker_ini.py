"""Thinker Mod's settings files, read the way Thinker itself reads them, and changed only in the
two ways the user ruled (2026-11-14):

* thinker.ini is MERGED: the pinned release's stock file, with the player's values carried into
  every setting both know; settings the pinned Thinker knows but its stock file does not list are
  appended active; settings it does not know are appended commented out under one header line.
* thinker_user.ini is COMMENTED IN PLACE: only the lines Thinker would reject get a `;`.

Everything here is bytes in, bytes out: no file I/O, no console. The caller backs files up and
writes the result through a temp file and a rename.

The model of Thinker's reader is its own inih (src/lib/ini.c, ini.h, Thinker v5.5):
  * fopen "r" (TEXT mode): CRLF is read as LF, and byte 0x1A ends the file;
  * fgets(line, 256): at most 255 characters per read, so a long physical line is several lines;
  * a NUL byte ends the line's text (C string functions);
  * a line is stripped of ASCII whitespace at both ends; `;` or `#` first = a comment;
  * an INDENTED non-comment line after a key (prev_name set; blank and comment lines do not clear
    it, only a section header does) continues that key: the handler is called again with the
    key's name, truncated to MAX_NAME - 1 = 49 characters; this test runs BEFORE the section test,
    so an indented `[x]` is a continuation too;
  * `[name]` (up to the first `]`) sets the section (49 characters) and clears prev_name;
  * otherwise `name = value` or `name : value`; an inline comment needs whitespace before its `;`;
  * a line with neither `=` nor `:` reaches no handler (no warning) and leaves prev_name alone;
  * the first line may start with a UTF-8 BOM, which is skipped (and counts as indentation).
Thinker's option_handler (src/main.cpp) warns ("Unknown configuration option detected") for any
section other than exactly `thinker`, and for any name it does not know (names are compared with
strcmp: case-sensitive).
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_INI_BYTES = 1 << 20           # a larger thinker.ini is not parsed (design section 6)
READ = 255                        # fgets(line, 256): characters per read
COMMENT_CHUNK = 254               # ';' + 254 bytes = one read
MAX_NAME = 49                     # MAX_NAME 50, NUL-terminated
SECTION = b"thinker"
WS = b" \t\n\v\f\r"
HEADER_PREFIX = b"; Settings from your previous thinker.ini that Thinker Mod "
HEADER_SUFFIX = b" does not use. They are kept here for reference and have no effect."


class IniError(ValueError):
    """A file this module will not parse (too large, or binary)."""


def header_line(ts: str) -> bytes:
    """The approved header (user, 2026-11-14) for the commented block; `ts` is {TS}."""
    return HEADER_PREFIX + ts.encode("ascii") + HEADER_SUFFIX


# ---------------------------------------------------------------- reading like inih

@dataclass
class Read:
    """One inih read (one fgets) and what inih does with it."""
    kind: str                     # blank | comment | section | key | cont | error
    section: bytes = b""
    name: bytes = b""             # for key and cont: the name the handler receives
    value: bytes = b""


@dataclass
class PLine:
    """One physical line of the file, as bytes, with the reads inih makes of it."""
    raw: bytes                    # without its line ending
    eol: bytes                    # b"\r\n", b"\n" or b"" (last line)
    reads: list = field(default_factory=list)

    def warns(self, known) -> bool:
        return any(_warns(r, known) for r in self.reads)

    def handler_names(self) -> list:
        return [r.name for r in self.reads if r.kind in ("key", "cont")]


def _warns(r: Read, known) -> bool:
    return r.kind in ("key", "cont") and (r.section != SECTION or r.name not in known)


def _rstrip(b: bytes) -> bytes:
    return b.rstrip(WS)


def _find(s: bytes, chars: bytes) -> int:
    """ini_find_chars_or_comment: index of the first char in `chars`, or of a `;` that follows
    whitespace (an inline comment), or len(s)."""
    was_space = False
    for i, c in enumerate(s):
        if chars and c in chars:
            return i
        if was_space and c == 0x3B:           # ';' (INI_INLINE_COMMENT_PREFIXES)
            return i
        was_space = c in WS
    return len(s)


def _split_physical(data: bytes) -> list:
    """Physical lines, keeping each line's own ending. Text mode: only CRLF and LF end a line
    (a lone CR is an ordinary byte)."""
    out = []
    start = 0
    while start < len(data):
        nl = data.find(b"\n", start)
        if nl < 0:
            out.append((data[start:], b""))
            break
        if nl > start and data[nl - 1] == 0x0D:
            out.append((data[start:nl - 1], b"\r\n"))
        else:
            out.append((data[start:nl], b"\n"))
        start = nl + 1
    return out


def scan(data: bytes) -> list:
    """The file as Thinker reads it: a list of PLine. Text after a 0x1A byte is not read by
    Thinker; it is returned as one last PLine with no reads (so writers can keep it unchanged)."""
    cut = data.find(b"\x1a")
    tail = b""
    if cut >= 0:
        data, tail = data[:cut], data[cut:]
    section = b""
    prev_name = b""
    first = True
    lines = []
    for raw, eol in _split_physical(data):
        pl = PLine(raw, eol)
        text = raw + (b"\n" if eol else b"")   # what fgets sees in text mode
        pos = 0
        while pos < len(text) or (pos == 0 and not text):
            chunk = text[pos:pos + READ]
            pos += READ
            if not chunk:
                break
            line = chunk.split(b"\x00", 1)[0]
            off = 0
            if first and line.startswith(b"\xef\xbb\xbf"):
                off = 3
            first = False
            body = _rstrip(line[off:])
            lead = len(body) - len(body.lstrip(WS))
            start = off + lead                 # inih: start > line
            body = body.lstrip(WS)
            if not body:
                pl.reads.append(Read("blank"))
            elif body[:1] in (b";", b"#"):
                pl.reads.append(Read("comment"))
            elif prev_name and start > 0:
                end = _find(body, b"")
                pl.reads.append(Read("cont", section, prev_name, _rstrip(body[:end])))
            elif body[:1] == b"[":
                end = _find(body[1:], b"]") + 1
                if end < len(body) and body[end:end + 1] == b"]":
                    section = body[1:end][:MAX_NAME]
                    prev_name = b""
                    pl.reads.append(Read("section", section))
                else:
                    pl.reads.append(Read("error"))
            else:
                end = _find(body, b"=:")
                if end < len(body) and body[end:end + 1] in (b"=", b":"):
                    name = _rstrip(body[:end])
                    value = body[end + 1:]
                    value = value[:_find(value, b"")]
                    value = _rstrip(value.lstrip(WS))
                    prev_name = name[:MAX_NAME]
                    pl.reads.append(Read("key", section, name, value))
                else:
                    pl.reads.append(Read("error"))
        lines.append(pl)
    if tail:
        lines.append(PLine(tail, b""))
    return lines


def warnings(data: bytes, known) -> list:
    """(physical line number from 1, section, name) of every read that makes Thinker warn."""
    return [(i + 1, r.section, r.name)
            for i, pl in enumerate(scan(data)) for r in pl.reads if _warns(r, known)]


def check_parsable(data: bytes) -> None:
    if len(data) > MAX_INI_BYTES:
        raise IniError(f"larger than {MAX_INI_BYTES} bytes")
    if b"\x00" in data.split(b"\x1a", 1)[0]:
        raise IniError("contains NUL bytes")


# ---------------------------------------------------------------- writing

def _commented(raw: bytes, eol: bytes) -> list:
    """`raw` commented out so that every inih read of it starts with ';': split into physical
    lines of at most COMMENT_CHUNK bytes, each prefixed with ';'."""
    eol = eol or b"\r\n"
    if not raw:
        return [(b";", eol)]
    return [(b";" + raw[i:i + COMMENT_CHUNK], eol) for i in range(0, len(raw), COMMENT_CHUNK)]


def _join(pairs) -> bytes:
    return b"".join(r + e for r, e in pairs)


@dataclass
class Group:
    """One setting as written in a file: its key line and the continuation lines that follow."""
    name: bytes
    lines: list                   # [(raw, eol)]
    values: list                  # the values the handler receives, in order


def _groups(lines) -> tuple:
    """Split a scanned file into ([thinker] known-or-not key groups, other physical lines).
    Returns (groups, rest): groups in file order, each a Group whose key line is in a section;
    rest = [(index, PLine)] for lines that are not part of a key group."""
    groups = []
    rest = []
    cur = None
    for i, pl in enumerate(lines):
        kinds = [r.kind for r in pl.reads]
        # a known key line of exactly 255 bytes is read as the key and then an empty read: still a key line
        body = [k for k in kinds if k != "blank"] if kinds and kinds[-1] == "blank" else kinds
        if body and body[0] == "key" and all(k in ("key", "cont") for k in body) and \
                all(r.name == pl.reads[0].name for r in pl.reads[1:] if r.kind == "key") and \
                sum(1 for r in pl.reads if r.kind == "key") == 1:
            r = pl.reads[0]
            cur = Group(r.name, [(pl.raw, pl.eol)], [x.value for x in pl.reads])
            cur.section = r.section
            cur.start = i
            groups.append(cur)
        elif kinds and all(k in ("cont", "blank") for k in kinds) and "cont" in kinds and cur is not None:
            cur.lines.append((pl.raw, pl.eol))
            cur.values.extend(x.value for x in pl.reads)
        else:
            if any(k == "section" for k in kinds):
                cur = None
            rest.append((i, pl))
    return groups, rest


def _carried(g: "Group") -> list:
    """A player's setting as it goes into the merged file: CRLF, and its key line no longer indented (and no
    BOM), so it can never become a continuation of the stock line above it (round-7 review, D2)."""
    first = g.lines[0][0]
    if first.startswith(b"\xef\xbb\xbf"):
        first = first[3:]
    return [(first.lstrip(WS), b"\r\n")] + [(raw, b"\r\n") for raw, _ in g.lines[1:]]


@dataclass
class MergeResult:
    data: bytes
    carried: list                 # names whose player value was carried
    appended: list                # known names not in the stock file, appended active
    commented: list               # names (or b"" for a non-key line) kept as comments
    unparsed: bool = False        # the player's file was not parsed (too large / binary)


def _previous_block(lines) -> list:
    """The commented lines of an earlier merge's block (after the approved header), as raw bytes."""
    out = []
    inside = False
    for pl in lines:
        if pl.raw.startswith(HEADER_PREFIX) and pl.raw.endswith(HEADER_SUFFIX):
            inside = True
            continue
        if inside:
            if pl.raw.startswith(b";"):
                out.append(pl.raw)
            elif pl.raw.strip(WS):
                inside = False
    return out


def merge(player: bytes, stock: bytes, known, ts: str, old_stock=None) -> MergeResult:
    """thinker.ini for the pinned release.

    player     the player's current thinker.ini (bytes)
    stock      the pinned release's stock thinker.ini (bytes, CRLF)
    known      the names the pinned Thinker accepts (set of bytes)
    ts         {TS}, for the header line
    old_stock  {name: [values]} of the stock file of the player's OWN release when it is a tagged
               release (decision MD): only values the player changed from it are carried. None
               (a development or unrecognised build, or a release newer than the data): every
               value is carried.
    """
    known = set(known)
    try:
        check_parsable(player)
    except IniError:
        return MergeResult(stock, [], [], [], unparsed=True)
    p_lines = scan(player)
    s_lines = scan(stock)
    p_groups, p_rest = _groups(p_lines)

    by_name = {}
    unknown = []                  # (line index, name, [(raw, eol)]) to comment out
    for g in p_groups:
        if g.section == SECTION and g.name in known:
            by_name.setdefault(g.name, []).append(g)
        else:
            unknown.append((g.start, g.name, g.lines))
    in_header_block = set(_previous_block(p_lines))
    for i, pl in p_rest:
        kinds = [r.kind for r in pl.reads]
        if not kinds or all(k in ("blank", "comment") for k in kinds):
            continue                                  # formatting and the player's own comments
        if kinds == ["section"] and pl.reads[0].section == SECTION:
            continue                                  # the stock file has its own header
        if pl.raw in in_header_block:
            continue
        names = pl.handler_names()
        unknown.append((i, names[0] if names else b"", [(pl.raw, pl.eol)]))
    unknown.sort(key=lambda u: u[0])                  # the player's own order

    def carry(name) -> bool:
        if old_stock is None:
            return True
        mine = [v for g in by_name[name] for v in g.values]
        return mine != [v.encode() if isinstance(v, str) else v for v in old_stock.get(name.decode(), [])]

    s_groups, _ = _groups(s_lines)
    stock_names = {g.name for g in s_groups if g.section == SECTION}
    at = {g.start: g for g in s_groups}
    out = []
    emitted = set()
    carried = []
    # Walk the stock file; a carried setting replaces the stock lines at its FIRST stock
    # occurrence (a repeated key such as script_label is carried as the player's whole set).
    i = 0
    while i < len(s_lines):
        g = at.get(i)
        if g is None:
            out.append((s_lines[i].raw, s_lines[i].eol))
            i += 1
            continue
        name = g.name
        if g.section == SECTION and name in by_name and carry(name):
            if name not in emitted:
                for pg in by_name[name]:
                    out.extend(_carried(pg))
                emitted.add(name)
                carried.append(name)
        else:
            out.extend(g.lines)
        i += len(g.lines)

    eol = b"\r\n"
    if out and out[-1][1] == b"":
        out[-1] = (out[-1][0], eol)
    appended = []
    last_section = None
    for pl in s_lines:
        for r in pl.reads:
            if r.kind == "section":
                last_section = r.section
    extra = [n for n in by_name if n not in stock_names and carry(n)]
    if extra:
        if last_section not in (None, SECTION):
            out.append((b"[thinker]", eol))
        for n in extra:
            for pg in by_name[n]:
                out.extend(_carried(pg))
            appended.append(n)

    previous = _previous_block(p_lines)
    block = []
    commented = []
    seen = set()
    for raw in previous:
        if raw not in seen:
            block.append((raw, eol))
            seen.add(raw)
    for _, name, lines in unknown:
        for raw, _ in lines:
            for c in _commented(raw, eol):
                if c[0] not in seen:
                    block.append(c)
                    seen.add(c[0])
        commented.append(name)
    if block:
        out.append((b"", eol))
        out.append((header_line(ts), eol))
        out.extend(block)

    data = _join(out)
    left = warnings(data, known)
    if left:
        raise AssertionError(f"merged thinker.ini would still warn: {left[:3]}")
    return MergeResult(data, carried, appended, commented)


@dataclass
class CommentResult:
    data: bytes
    commented: list               # names (b"" for a non-key line) commented out
    changed: bool
    unparsed: bool = False


def comment_unknown(data: bytes, known) -> CommentResult:
    """thinker_user.ini: comment out, in place, every line Thinker would warn about, and the
    continuation lines of a commented key (otherwise they would continue the key before it).
    Every other byte is kept, including line endings and anything after 0x1A."""
    known = set(known)
    try:
        check_parsable(data)
    except IniError:
        return CommentResult(data, [], False, unparsed=True)
    lines = scan(data)
    commented = []
    for _ in range(8):                                # commenting can re-attach continuations
        hit = False
        new = []
        drop_cont = False
        for pl in lines:
            kinds = [r.kind for r in pl.reads]
            is_cont = bool(kinds) and all(k == "cont" for k in kinds)
            if pl.warns(known) or (drop_cont and is_cont):
                names = pl.handler_names()
                commented.append(names[0] if names else b"")
                new.extend(_commented(pl.raw, pl.eol))
                drop_cont = True
                hit = True
                continue
            if kinds and not all(k in ("blank", "comment", "cont") for k in kinds):
                drop_cont = False
            new.append((pl.raw, pl.eol))
        if not hit:
            break
        lines = scan(_join(new))
    out = _join((pl.raw, pl.eol) for pl in lines)
    if warnings(out, known):
        raise AssertionError("thinker_user.ini would still warn after commenting")
    return CommentResult(out, commented, out != data)


def console_names(names, limit: int = 10) -> str:
    """`a, b, c` for the console: names filtered to [A-Za-z0-9_], at most `limit`, then 'and N more'."""
    clean = []
    for n in names:
        s = "".join(ch for ch in n.decode("latin-1") if ch.isascii() and (ch.isalnum() or ch == "_"))
        if s and s not in clean:
            clean.append(s)
    if len(clean) <= limit:
        return ", ".join(clean)
    return ", ".join(clean[:limit]) + f" and {len(clean) - limit} more"
