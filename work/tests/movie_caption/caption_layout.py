"""Vanilla secret-project caption layout law (port of terranx.exe 0x4BEF00 /
Buffer_write_strings_height 0x5DAD70 / Buffer_write_strings 0x5DB040 and helpers).

Pure Python, no GDI.  Everything is in NATIVE 640x480 movie-surface pixels.

Font metrics dict per font (index 0,1,2 = the three fonts of the movlist section):
    tmHeight, tmAscent, tmDescent, tmInternalLeading, tmExternalLeading
extent(font_index, text) -> GetTextExtentPoint32A cx for that font.

Engine Font fields (Font_init 0x618F40):
    +0x0C line_height = tmHeight + tmExternalLeading
    +0x10 "height"    = tmAscent - tmInternalLeading
    +0x14 tmInternalLeading, +0x18 tmAscent, +0x1C tmDescent

Slots (Buffer_set_font(f0,f1,f2,f0)): 0 normal=f0, 1 {..}=f1, 2 [..]=f2, 3 $LINK=f0.
"""

SLOT_FONT = (0, 1, 2, 0)          # slot -> section font index
PARA_CONT, PARA_LEFT, PARA_CENTRE, PARA_BLANK = 0, 1, 2, 3


def line_height(fm):               # Font+0x0C
    return fm["tmHeight"] + fm["tmExternalLeading"]


def font_h(fm):                    # Font+0x10
    return fm["tmAscent"] - fm["tmInternalLeading"]


def parse_node(line):
    """TextList add_line 0x608BA0 -> (type, text)."""
    if not line.startswith("^"):
        return PARA_CONT, line
    if len(line) == 1:
        return PARA_BLANK, ""
    if line[1] != "^":
        return PARA_LEFT, line[1:]
    if len(line) > 2 and line[2] == "^":
        return PARA_CENTRE, line[3:]
    return PARA_CENTRE, line[2:]


def tokenize(text, slot=0):
    """Markup state machine shared by 0x5DC410 (wrap) / 0x5DC7C0 (width) / 0x5DCAE0 (draw).
    Returns ([(char, slot), ...] visible chars, end_slot)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        special = c in "{}[]$" or (slot == 3 and c == "=")
        if not special:
            out.append((c, slot)); i += 1; continue
        if c == "$":
            if text.startswith("$LINK<", i):
                slot = 3; i += 6
            else:
                i += 1                       # lone '$' is dropped
        elif c == "=":                       # only inside a link: skip "=id>"
            j = text.find(">", i + 1)
            i = (j + 1) if j >= 0 else i + 1
            slot = 0
        else:
            if i + 1 < n and text[i + 1] == c:   # "[[" "{{" "]]" "}}" -> literal
                out.append((c, slot)); i += 2
            else:
                slot = {"{": 1, "}": 0, "[": 2, "]": 0}[c]; i += 1
    return out, slot


def _runs(chars):
    runs = []
    for ch, s in chars:
        if runs and runs[-1][1] == s:
            runs[-1][0] += ch
        else:
            runs.append([ch, s])
    return [(t, s) for t, s in runs]


def _width(chars, extent):
    return sum(extent(SLOT_FONT[s], t) for t, s in _runs(chars))


def _wrap(chars, avail_first, avail, extent):
    """Greedy word wrap (Font fit 0x619370): a chunk is [space]word; the break goes AFTER the
    space, so a wrapped line keeps its trailing space (it counts in the centring width).
    A first word that does not fit on an EMPTY line is forced onto it."""
    lines, cur, i, n = [], [], 0, len(chars)
    room = avail_first
    while i < n:
        j = i + 1
        while j < n and chars[j][0] != " ":
            j += 1
        chunk = chars[i:j]
        if _width(cur + chunk, extent) > room and cur:
            # break after the space that starts this chunk
            if chunk and chunk[0][0] == " ":
                cur.append(chunk[0]); chunk = chunk[1:]
            lines.append(cur); cur = []; room = avail
        cur += chunk
        i = j
    lines.append(cur)
    return lines


def layout(section_lines, rect, fonts, extent):
    """section_lines: caption text lines (after the blank line).  rect = (x, y, w, h).
    Returns dict(H, y0, y_shift, lines=[{y, kind, runs:[{text,slot,font,x,y_textout,baseline}]}])."""
    x0, ry, w, h = rect
    LH = line_height(fonts[0])                       # EVERY line advances by font0's line height
    y_shift = max(font_h(f) for f in fonts[:3])      # Buffer_write_raw_l: y += max(Font+0x10 of slots 0,1,2)

    # paragraphs: a type-0 node continues the previous left paragraph, joined with ' '
    paras = []
    for ln in section_lines:
        t, s = parse_node(ln)
        if t == PARA_CONT and paras and paras[-1][0] in (PARA_LEFT, PARA_CONT):
            paras[-1][1] += " " + s
        else:
            paras.append([t, s])

    vis = []                                         # (kind, [chars]) per visual line
    for t, s in paras:
        if t == PARA_BLANK:
            vis.append((t, []))
            continue
        chars, _ = tokenize(s, 0)                    # slot state resets per paragraph (0x5E3660)
        for l in _wrap(chars, w, w, extent):
            vis.append((t, l))

    H = LH * len(vis)                                # Buffer_write_strings_height
    d = h - H
    y0 = ry + (abs(d) // 2) * (1 if d >= 0 else -1)  # cdq/sub/sar = trunc toward zero

    out = []
    for k, (t, l) in enumerate(vis):
        y = y0 + k * LH
        x = x0
        if t == PARA_CENTRE:
            dd = w - _width(l, extent)
            x = x0 + (abs(dd) // 2) * (1 if dd >= 0 else -1)
        runs = []
        for text, s in _runs(l):
            f = SLOT_FONT[s]
            runs.append(dict(text=text, slot=s, font=f, x=x, y_textout=y + y_shift,
                             baseline=y + y_shift + fonts[f]["tmAscent"]))   # TextOutA is TA_TOP on the DDraw DC
            x += extent(f, text)
        out.append(dict(y=y, kind=t, runs=runs))
    return dict(H=H, y0=y0, y_shift=y_shift, line_height=LH, lines=out)
