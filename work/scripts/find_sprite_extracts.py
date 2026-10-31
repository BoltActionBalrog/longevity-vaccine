"""Enumerate all calls to Sprite_extract_2 (0x5E39A0) and harvest the
(x, y, width, height) immediates passed at each site.

Sprite_extract_2 is __thiscall:
    int Sprite_extract_2(Sprite* This, Buffer* a2, int a3,
                         int x, int y, int width, int height, void* a8);

Convention on x86 VC5/VC6 builds:
    args pushed right-to-left, then ECX = This, then CALL.
So, walking backward from CALL through the 7 nearest stack-arg sites
(PUSH imm OR MOV [ESP+n], imm), the push order is:
    nearest-to-CALL : a8        (void*)
                      height    <-- want
                      width     <-- want
                      y         <-- want
                      x         <-- want
                      a3        (int)
    farthest        : a2        (Buffer*)

The compiler may also pre-allocate a frame with SUB ESP, N and use
MOV [ESP+offset], imm32 instead of PUSH. We handle both, then sort
by stack offset to recover argument order.

Output: a table of (caller, call_va, x, y, w, h) for every call site,
plus a quick filter for calls reachable from load_interface (0x455610).

Run via D:\\SmacxUi\\work\\run-find-sprite-extracts.bat.
"""

import sys
from collections import defaultdict, deque

import pyghidra

pyghidra.start()

PROJECT_LOCATION = r"D:\SmacxUi\work\ghidra-projects"
PROJECT_NAME = "terranx"
PROGRAM_NAME = "terranx.exe"

SPRITE_EXTRACT_2_VA = 0x005E39A0
LOAD_INTERFACE_VA = 0x00455610
LOAD_FIXED_SPRITES_VA = 0x00455E80
LOAD_DESWIN_SPRITES_VA = 0x00455E50

# How many instructions to walk back from a CALL when harvesting args.
WALK_BACK = 40
# How deep to walk the static call-graph from load_interface.
REACHABILITY_DEPTH = 4


def main() -> int:
    with pyghidra.open_program(
        binary_path=None,
        project_location=PROJECT_LOCATION,
        project_name=PROJECT_NAME,
        program_name=PROGRAM_NAME,
        analyze=False,
        nested_project_location=False,
    ) as api:
        program = api.getCurrentProgram()
        fm = program.getFunctionManager()
        ref_mgr = program.getReferenceManager()
        af = program.getAddressFactory()
        listing = program.getListing()

        from ghidra.program.model.scalar import Scalar

        def addr(value):
            return af.getDefaultAddressSpace().getAddress(value)

        # ---- 0. Sanity check Sprite_extract_2 exists ----
        target = fm.getFunctionAt(addr(SPRITE_EXTRACT_2_VA))
        if target is None:
            # Maybe Ghidra didn't define a function there, but xrefs still work.
            print(f"WARN: no function defined at 0x{SPRITE_EXTRACT_2_VA:08x} "
                  "— continuing on raw xrefs.")
        else:
            print(f"target: {target.getName()} @ 0x{SPRITE_EXTRACT_2_VA:08x}")

        # ---- 1. Static call-graph reachability from load_interface ----
        reachable = set()
        queue = deque()
        for root in (LOAD_INTERFACE_VA, LOAD_FIXED_SPRITES_VA, LOAD_DESWIN_SPRITES_VA):
            f = fm.getFunctionAt(addr(root))
            if f is None:
                print(f"WARN: no function at root 0x{root:08x}")
                continue
            queue.append((f, 0))
            reachable.add(f.getEntryPoint().getOffset())

        while queue:
            f, depth = queue.popleft()
            if depth >= REACHABILITY_DEPTH:
                continue
            body = f.getBody()
            it = body.getAddresses(True)
            while it.hasNext():
                a = it.next()
                for r in ref_mgr.getReferencesFrom(a):
                    if not r.getReferenceType().isCall():
                        continue
                    callee = fm.getFunctionAt(r.getToAddress())
                    if callee is None:
                        continue
                    off = callee.getEntryPoint().getOffset()
                    if off in reachable:
                        continue
                    reachable.add(off)
                    queue.append((callee, depth + 1))

        print(f"reachable from UI-loader roots within depth {REACHABILITY_DEPTH}: "
              f"{len(reachable)} functions")

        # ---- 2. Find every call site of Sprite_extract_2 ----
        call_sites = []
        for r in ref_mgr.getReferencesTo(addr(SPRITE_EXTRACT_2_VA)):
            if not r.getReferenceType().isCall():
                continue
            site_addr = r.getFromAddress()
            caller = fm.getFunctionContaining(site_addr)
            call_sites.append((site_addr, caller))
        print(f"call sites: {len(call_sites)}")

        # ---- 3. For each call site, harvest stack-pushed args ----
        results = []
        for site_addr, caller in call_sites:
            caller_va = caller.getEntryPoint().getOffset() if caller else None
            caller_name = caller.getName() if caller else "<no-function>"
            in_ui_loader = caller_va in reachable if caller_va is not None else False

            # Walk backward from the call site within the caller's body only.
            body = caller.getBody() if caller else None
            instr_at = listing.getInstructionAt(site_addr)
            if instr_at is None:
                results.append({
                    "site": site_addr, "caller": caller_name, "caller_va": caller_va,
                    "in_ui_loader": in_ui_loader, "error": "no instruction at site",
                })
                continue

            # collect previous N instructions
            prev = []
            cur = instr_at.getPrevious()
            steps = 0
            while cur is not None and steps < WALK_BACK:
                if body is not None and not body.contains(cur.getAddress()):
                    break
                prev.append(cur)
                cur = cur.getPrevious()
                steps += 1
            prev.reverse()  # now in program order

            # Two patterns to capture:
            #  (a) PUSH imm32              — stack offset implicit (sequential)
            #  (b) MOV [ESP+N], imm32      — stack offset explicit
            # If any PUSH appears in the window, treat the call as PUSH-based and
            # take the last 7 PUSH-imms in order; else fall back to MOV+ESP.

            pushes = []  # list of (addr, imm)
            mov_stack_imms = []  # list of (offset, imm)
            for ins in prev:
                mnem = ins.getMnemonicString().upper()
                if mnem == "PUSH":
                    # PUSH imm: single operand, Scalar
                    if ins.getNumOperands() == 1:
                        objs = ins.getOpObjects(0)
                        if len(objs) == 1 and isinstance(objs[0], Scalar):
                            pushes.append((ins.getAddress(), objs[0].getUnsignedValue()))
                elif mnem == "MOV":
                    # Look for MOV [ESP+N], imm
                    if ins.getNumOperands() == 2:
                        dst_objs = ins.getOpObjects(0)
                        src_objs = ins.getOpObjects(1)
                        # Source must be a scalar immediate
                        if not (len(src_objs) == 1 and isinstance(src_objs[0], Scalar)):
                            continue
                        imm = src_objs[0].getUnsignedValue()
                        # Dest must be [ESP+disp] or [ESP] — represented as a Register + Scalar pair
                        regs = [o for o in dst_objs if hasattr(o, "getName") and o.getName().upper() == "ESP"]
                        if not regs:
                            continue
                        scs = [o for o in dst_objs if isinstance(o, Scalar)]
                        disp = scs[0].getUnsignedValue() if scs else 0
                        mov_stack_imms.append((disp, imm, ins.getAddress()))

            args = None
            mode = None
            if pushes:
                # Take last 7 PUSHes (closest to the call) in code order.
                tail = pushes[-7:]
                if len(tail) == 7:
                    # Push order: a2, a3, x, y, w, h, a8 — last to oldest.
                    # In code order tail[0]=a2 ... tail[6]=a8.
                    a2, a3, x, y, w, h, a8 = (v for _a, v in tail)
                    args = {"a2": a2, "a3": a3, "x": x, "y": y, "w": w, "h": h, "a8": a8}
                    mode = "PUSH"
                else:
                    args = {"raw_pushes": [v for _a, v in tail]}
                    mode = f"PUSH (only {len(tail)})"

            if args is None and mov_stack_imms:
                # Sort by offset ascending; offset 0 = a2 if frame is sized to fit.
                # Just emit the raw map for inspection.
                sorted_movs = sorted(mov_stack_imms, key=lambda t: t[0])
                args = {"stack_movs": [(hex(o), v) for o, v, _ in sorted_movs]}
                mode = "MOV[ESP]"

            results.append({
                "site": site_addr,
                "caller": caller_name,
                "caller_va": caller_va,
                "in_ui_loader": in_ui_loader,
                "mode": mode,
                "args": args,
            })

        # ---- 4. Print, UI-loader-reachable first, sorted by caller then site ----
        def keyfn(r):
            return (0 if r.get("in_ui_loader") else 1, r.get("caller") or "", str(r["site"]))

        results.sort(key=keyfn)

        print()
        print("=" * 100)
        print("call sites (UI-loader-reachable first):")
        print("=" * 100)
        current_caller = None
        for r in results:
            if r["caller"] != current_caller:
                current_caller = r["caller"]
                tag = "  [UI-loader reachable]" if r["in_ui_loader"] else ""
                cv = f"0x{r['caller_va']:08x}" if r["caller_va"] is not None else "n/a"
                print(f"\n--- {current_caller} @ {cv}{tag} ---")
            site = r["site"]
            mode = r.get("mode") or "?"
            args = r.get("args") or {}
            if isinstance(args, dict) and "x" in args:
                # Pretty-print the canonical case
                fmt = (f"  call @ {site}  ({mode})  "
                       f"x={args['x']:5d}  y={args['y']:5d}  "
                       f"w={args['w']:5d}  h={args['h']:5d}  "
                       f"a2=0x{args['a2']:x}  a3=0x{args['a3']:x}  a8=0x{args['a8']:x}")
                # Flag widths in the interesting range
                w = args["w"]
                tags = []
                if w == 300:
                    tags.append("** WIDTH=300 (matches 0x4ADFA5 logical) **")
                elif 250 <= w <= 350:
                    tags.append("** width near 300 **")
                if tags:
                    fmt += "    " + " ".join(tags)
                print(fmt)
            else:
                print(f"  call @ {site}  ({mode})  raw={args}")

        # ---- 5. Sum stats ----
        print()
        print("=" * 100)
        ui_reach = sum(1 for r in results if r.get("in_ui_loader"))
        print(f"total call sites: {len(results)}  |  UI-loader reachable: {ui_reach}")
        width_300 = [r for r in results
                     if isinstance(r.get("args"), dict)
                     and r["args"].get("w") == 300]
        print(f"sites with width==300: {len(width_300)}")
        for r in width_300:
            print(f"  - {r['caller']}  @  {r['site']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
