"""Assemble the PRACX left/right edge-scroll console-exemption cave (prax.dll).

Problem: PRACXCheckScroll (pracx.cpp:991) LEFT (line 1047) and RIGHT (line 1053)
edge-scroll zones have NO console carve-out (unlike the already-fixed bottom edge).
On 4:3 / 5:4 screens the scaled HUD strip is full-width, so the MENU (top-left) and
COMMLINK (top-right) buttons reach the screen edges and sit inside the left/right
scroll zones -> PRACXCheckScroll's message-starving spin -> deferred/eaten clicks.

Fix: detour each zone's body-entry (the `mov [ebp-0x1c],1` that sets fScrolled) into
a small cave that suppresses the scroll when the cursor is over the console strip's
screen rectangle at that edge. If exempt -> fScrolled stays 0 -> the do{}while loop
exits its first iteration -> the message pump is never starved -> the click lands.

Console strip rect (derived purely from screen w,h in PRACXCheckScroll's frame):
  strip is 1024*g/16 wide x 257*g/16 tall, bottom-flush, centered; g = clamp(16h/768,16,40).
  For every realistic 4:3/5:4/16:9/16:10 monitor (h <= 1920) the clamp is inactive, so:
    stripW = 1024*h/768 = 4h/3      strip_left = (w - stripW)/2 = (3w - 4h)/6
    stripH = 257*h/768              strip_top  = h - stripH
  strip_left classifies aspect exactly: <= iScrollArea  <=>  strip reaches the edge
  (0 at 4:3, negative at 5:4, ~0.22h at 16:9 -> far outside the ~0.07h scroll zone, so
  16:9/16:10 are never exempted = zero regression on those). Above h=1920 the unclamped
  formulas overestimate the strip but STILL never mis-exempt 16:9/16:10 (verified in the
  memo); a 4:3 monitor taller than 1920 would fall back to vanilla PRACX (original bug),
  which is the safe direction. p.x/p.y = [ebp-0xc]/[ebp-8]; w/h = [ebp-0x40]/[ebp-0x2c].

Exemption predicate:
  LEFT  :  p.y >= strip_top  &&  p.x       >= strip_left
  RIGHT :  p.y >= strip_top  && (w - p.x)  >= strip_left

Everything has a static VA (cave fixed at CAVE_VA), so we compute all rel8/rel32 here
and emit raw bytes for both the cave contents and the two detour site new_bytes.

Run:  py -3 work/scripts/assemble_prax_scroll_lr.py
"""

CAVE_VA = 0x10033830          # zero-fill slack in .text (VA end 0x10033821..raw end 0x10033a00)

# Detour sites (both are the identical 7-byte `mov dword [ebp-0x1c],1`).
SITE_LEFT  = 0x100052EE
SITE_RIGHT = 0x10005367
DISPLACED  = bytes.fromhex("C7 45 E4 01 00 00 00".replace(" ", ""))  # mov [ebp-0x1c],1

RET_LEFT   = 0x100052F5       # instruction after the left  displaced mov
RET_RIGHT  = 0x1000536E       # instruction after the right displaced mov
SKIP_TOP   = 0x100053D0       # past both L/R zones -> top-edge check (exempt target)


def rel32(frm_end, to):
    d = to - frm_end
    assert -0x80000000 <= d < 0x80000000
    return d.to_bytes(4, "little", signed=True)


def rel8(frm_end, to):
    d = to - frm_end
    assert -128 <= d < 128, f"rel8 out of range: {d}"
    return d.to_bytes(1, "little", signed=True)


def build():
    # ---- strip_metrics: eax=strip_left, edx=strip_top; clobbers eax,ecx,edx ----
    strip_metrics = bytes.fromhex("".join([
        "8B45C0",        # mov eax,[ebp-0x40]      ; w
        "8D0440",        # lea eax,[eax+eax*2]     ; 3w
        "8B4DD4",        # mov ecx,[ebp-0x2c]      ; h
        "C1E102",        # shl ecx,2               ; 4h
        "2BC1",          # sub eax,ecx             ; 3w-4h
        "99",            # cdq
        "B906000000",    # mov ecx,6
        "F7F9",          # idiv ecx                ; eax=(3w-4h)/6 = strip_left
        "50",            # push eax
        "8B45D4",        # mov eax,[ebp-0x2c]      ; h
        "69C001010000",  # imul eax,eax,257        ; 257h
        "99",            # cdq
        "B900030000",    # mov ecx,768
        "F7F9",          # idiv ecx                ; eax=257h/768 = stripH
        "8B55D4",        # mov edx,[ebp-0x2c]      ; h
        "2BD0",          # sub edx,eax             ; strip_top = h - stripH
        "58",            # pop eax                 ; strip_left
        "C3",            # ret
    ]))
    sm_va = CAVE_VA
    sm_len = len(strip_metrics)

    # ---- cave_left ----
    cl_va = sm_va + sm_len
    # layout offsets within cave_left:
    #   call(5) ecx=py(3) cmp(2) jl(2) ecx=px(3) cmp(2) jl(2) jmp_exempt(5) do_scroll:mov(7) jmp_ret(5)
    cl_jl1_end = cl_va + 5 + 3 + 2 + 2          # after first jl
    cl_jl2_end = cl_jl1_end + 3 + 2 + 2         # after second jl
    cl_jmp_exempt_end = cl_jl2_end + 5
    cl_do_scroll = cl_jmp_exempt_end            # do_scroll label
    cl_end = cl_do_scroll + 7 + 5
    cave_left = b"".join([
        b"\xE8" + rel32(cl_va + 5, sm_va),                       # call strip_metrics
        bytes.fromhex("8B4DF8"),                                  # mov ecx,[ebp-8]  (p.y)
        bytes.fromhex("3BCA"),                                    # cmp ecx,edx
        b"\x7C" + rel8(cl_jl1_end, cl_do_scroll),                 # jl do_scroll
        bytes.fromhex("8B4DF4"),                                  # mov ecx,[ebp-0xc] (p.x)
        bytes.fromhex("3BC8"),                                    # cmp ecx,eax
        b"\x7C" + rel8(cl_jl2_end, cl_do_scroll),                 # jl do_scroll
        b"\xE9" + rel32(cl_jmp_exempt_end, SKIP_TOP),             # jmp exempt (skip L/R)
        DISPLACED,                                                # do_scroll: mov [ebp-0x1c],1
        b"\xE9" + rel32(cl_end, RET_LEFT),                        # jmp back
    ])
    assert len(cave_left) == cl_end - cl_va

    # ---- cave_right ----
    cr_va = cl_end
    cr_jl1_end = cr_va + 5 + 3 + 2 + 2
    cr_jl2_end = cr_jl1_end + 3 + 3 + 2 + 2     # extra 3 for the `sub ecx,[ebp-0xc]`
    cr_jmp_exempt_end = cr_jl2_end + 5
    cr_do_scroll = cr_jmp_exempt_end
    cr_end = cr_do_scroll + 7 + 5
    cave_right = b"".join([
        b"\xE8" + rel32(cr_va + 5, sm_va),                       # call strip_metrics
        bytes.fromhex("8B4DF8"),                                  # mov ecx,[ebp-8]  (p.y)
        bytes.fromhex("3BCA"),                                    # cmp ecx,edx
        b"\x7C" + rel8(cr_jl1_end, cr_do_scroll),                 # jl do_scroll
        bytes.fromhex("8B4DC0"),                                  # mov ecx,[ebp-0x40] (w)
        bytes.fromhex("2B4DF4"),                                  # sub ecx,[ebp-0xc]  (w-p.x)
        bytes.fromhex("3BC8"),                                    # cmp ecx,eax
        b"\x7C" + rel8(cr_jl2_end, cr_do_scroll),                 # jl do_scroll
        b"\xE9" + rel32(cr_jmp_exempt_end, SKIP_TOP),             # jmp exempt
        DISPLACED,                                                # do_scroll: mov [ebp-0x1c],1
        b"\xE9" + rel32(cr_end, RET_RIGHT),                       # jmp back
    ])
    assert len(cave_right) == cr_end - cr_va

    cave = strip_metrics + cave_left + cave_right

    # ---- detour site new_bytes: E9 rel32 + 90 90 ----
    site_left_new  = b"\xE9" + rel32(SITE_LEFT + 5,  cl_va) + b"\x90\x90"
    site_right_new = b"\xE9" + rel32(SITE_RIGHT + 5, cr_va) + b"\x90\x90"

    return {
        "cave": cave, "cave_va": CAVE_VA,
        "sm_va": sm_va, "cl_va": cl_va, "cr_va": cr_va, "cave_end": cr_end,
        "site_left_new": site_left_new, "site_right_new": site_right_new,
    }


def hx(b): return " ".join(f"{x:02X}" for x in b)


if __name__ == "__main__":
    r = build()
    print(f"cave VA 0x{r['cave_va']:08X} .. 0x{r['cave_end']:08X}  ({len(r['cave'])} bytes)")
    print(f"  strip_metrics @ 0x{r['sm_va']:08X}")
    print(f"  cave_left     @ 0x{r['cl_va']:08X}")
    print(f"  cave_right    @ 0x{r['cr_va']:08X}")
    print()
    print("CAVE CONTENTS (single content blob at cave base):")
    print(f"  {hx(r['cave'])}")
    print()
    print("SITE new_bytes:")
    print(f"  left  @ 0x{SITE_LEFT:08X}  orig {hx(DISPLACED)}  ->  {hx(r['site_left_new'])}")
    print(f"  right @ 0x{SITE_RIGHT:08X}  orig {hx(DISPLACED)}  ->  {hx(r['site_right_new'])}")
