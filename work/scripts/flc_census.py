"""Offline census of turn.flc (TURN COMPLETE banner art).

Decides pair-remap vs averaging-resample for the 1920x1080 (g=22) banner banding
(fractional-NN class, see skill scaling-frames section 7b):
  - vertical runs <=2 dominating for an index pair => scanline dither => pair-remap viable
  - long runs / many distinct indices / gradients   => continuous art => averaging blit

Decodes frame 0 (COLOR_256 + BYTE_RUN = the static TURN COMPLETE banner) and applies
the SS2 deltas for the remaining frames (flash anim). Pure stdlib.

Usage: python work/scripts/flc_census.py [path-to-flc]
"""
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import game_dir


def sbyte(b):
    return b - 256 if b >= 128 else b


def decode_byte_run(data, off, size, w, h, pix):
    end = off + size - 6
    p = off
    for y in range(h):
        p += 1  # obsolete packet-count byte
        x = 0
        while x < w and p < end:
            c = sbyte(data[p]); p += 1
            if c > 0:
                pix[y * w + x:y * w + x + c] = bytes([data[p]]) * c
                p += 1
                x += c
            elif c < 0:
                n = -c
                pix[y * w + x:y * w + x + n] = data[p:p + n]
                p += n
                x += n
    return p


def decode_ss2(data, off, size, w, h, pix):
    p = off
    lines = struct.unpack_from('<H', data, p)[0]; p += 2
    y = 0
    for _ in range(lines):
        packets = None
        while packets is None:
            word = struct.unpack_from('<H', data, p)[0]; p += 2
            top = word & 0xC000
            if top == 0xC000:
                y += 0x10000 - word  # word is negative signed line-skip
            elif top == 0x8000:
                pix[y * w + (w - 1)] = word & 0xFF
            else:
                packets = word
        x = 0
        for _ in range(packets):
            x += data[p]; p += 1
            c = sbyte(data[p]); p += 1
            if c > 0:
                n = 2 * c
                pix[y * w + x:y * w + x + n] = data[p:p + n]
                p += n
                x += n
            else:
                pat = data[p:p + 2]; p += 2
                n = -c
                pix[y * w + x:y * w + x + 2 * n] = pat * n
                x += 2 * n
        y += 1
    return p


def decode_color256(data, off, pal):
    p = off
    packets = struct.unpack_from('<H', data, p)[0]; p += 2
    idx = 0
    for _ in range(packets):
        idx += data[p]; p += 1
        count = data[p] or 256; p += 1
        for i in range(count):
            r, g, b = data[p], data[p + 1], data[p + 2]
            pal[idx + i] = (r, g, b)
            p += 3
        idx += count


def census(pix, w, h, pal, label):
    cnt = Counter(pix)
    print(f"\n--- {label}: {w}x{h}, {len(cnt)} distinct indices ---")
    print("top indices (idx: count, rgb):")
    for idx, n in cnt.most_common(10):
        print(f"  0x{idx:02X}: n={n:5d}  rgb={pal.get(idx, '?')}")
    # vertical run stats per index
    maxrun = Counter()
    run_le2 = 0
    total = 0
    alt_pairs = Counter()
    for x in range(w):
        run = 0
        prev = None
        for y in range(h):
            v = pix[y * w + x]
            if v == prev:
                run += 1
            else:
                if prev is not None:
                    if run <= 2:
                        run_le2 += run
                    total += run
                    if maxrun[prev] < run:
                        maxrun[prev] = run
                    alt_pairs[tuple(sorted((prev, v)))] += 1
                run = 1
            prev = v
        if prev is not None:
            if run <= 2:
                run_le2 += run
            total += run
            if maxrun[prev] < run:
                maxrun[prev] = run
    print("max vertical run per top index:", {f"0x{i:02X}": maxrun[i] for i, _ in cnt.most_common(10)})
    print(f"pixels in vertical runs <=2: {run_le2}/{total} = {100.0 * run_le2 / max(total, 1):.1f}%")
    print("top vertical-neighbor transitions (a<->b: count):")
    for (a, b), n in alt_pairs.most_common(8):
        print(f"  0x{a:02X}<->0x{b:02X}: {n}")
    return cnt


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else game_dir() / "turn.flc"
    data = path.read_bytes()
    size, magic, frames, w, h, depth, flags, speed = struct.unpack_from('<IHHHHHHI', data, 0)
    print(f"{path}: size={size} magic=0x{magic:04X} frames={frames} {w}x{h} depth={depth} flags=0x{flags:04X}")
    assert magic == 0xAF12, "not an FLC"

    pal = {}
    pix = bytearray(w * h)
    p = 128
    frame_no = 0
    while p + 16 <= len(data) and frame_no <= frames + 1:
        fsize, fmagic, chunks = struct.unpack_from('<IHH', data, p)
        if fmagic != 0xF1FA:
            p += fsize
            continue
        q = p + 16
        for _ in range(chunks):
            csize, ctype = struct.unpack_from('<IH', data, q)
            body = q + 6
            if ctype == 4:
                decode_color256(data, body, pal)
            elif ctype == 15:
                decode_byte_run(data, body, csize, w, h, pix)
            elif ctype == 7:
                try:
                    decode_ss2(data, body, csize, w, h, pix)
                except Exception as e:
                    print(f"  (frame {frame_no} SS2 decode failed: {e})")
            elif ctype == 16:
                pix[:] = data[body:body + w * h]
            elif ctype == 13:
                pix[:] = bytes(w * h)
            q += csize
        if frame_no == 0:
            census(pix, w, h, pal, "FRAME 0 (static TURN COMPLETE banner)")
            print("\nframe 0 rows (hex):")
            for y in range(h):
                print(f"  y{y:02d} " + bytes(pix[y * w:(y + 1) * w]).hex())
        elif frame_no in (1, 9, 18):
            census(pix, w, h, pal, f"FRAME {frame_no} (flash anim, cumulative)")
        p += fsize
        frame_no += 1
    print(f"\nframes walked: {frame_no}")


if __name__ == "__main__":
    main()
