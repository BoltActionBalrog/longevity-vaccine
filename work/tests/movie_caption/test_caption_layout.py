"""Checks caption_layout.py against the measured vanilla SUPERCOLLIDER numbers, with real GDI metrics."""
import ctypes, sys
from ctypes import wintypes as W
from caption_layout import layout

g = ctypes.WinDLL("gdi32")
class TM(ctypes.Structure):
    _fields_ = [(n, W.LONG) for n in ("tmHeight","tmAscent","tmDescent","tmInternalLeading","tmExternalLeading",
        "tmAveCharWidth","tmMaxCharWidth","tmWeight","tmOverhang","tmDigitizedAspectX","tmDigitizedAspectY")] + \
        [(n, ctypes.c_ubyte) for n in ("a","b","c","d","tmItalic","tmUnderlined","tmStruckOut","tmPitchAndFamily","tmCharSet")]
g.CreateCompatibleDC.restype = W.HDC; g.CreateFontA.restype = W.HANDLE
g.SelectObject.restype = W.HANDLE; g.SelectObject.argtypes = [W.HDC, W.HANDLE]
g.GetTextMetricsA.argtypes = [W.HDC, ctypes.c_void_p]
g.GetTextExtentPoint32A.argtypes = [W.HDC, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
dc = g.CreateCompatibleDC(None)                    # engine measure DC [0x9BB488] is CreateCompatibleDC(NULL)
def mkfont(face, style, size):                     # Font_init 0x618F40 LOGFONT
    return g.CreateFontA(-size, 0, 0, 0, 700 if style & 1 else 0, (style >> 1) & 1, (style >> 2) & 1, 0,
                         0, 7, 0, 0, 0, face.encode())   # ANSI_CHARSET, OUT_TT_ONLY_PRECIS, DEFAULT_QUALITY
spec = [("Arial", 0, 10), ("Arial", 1, 14), ("Arial", 1, 14)]
hf = [mkfont(*s) for s in spec]; fonts = []
for h in hf:
    g.SelectObject(dc, h); tm = TM(); g.GetTextMetricsA(dc, ctypes.byref(tm))
    fonts.append({k: getattr(tm, k) for k in ("tmHeight","tmAscent","tmDescent","tmInternalLeading","tmExternalLeading")})
def extent(i, s):
    g.SelectObject(dc, hf[i]); sz = W.SIZE(); b = s.encode("cp1252")
    g.GetTextExtentPoint32A(dc, b, len(b), ctypes.byref(sz)); return sz.cx

lines = ["^^[The Supercollider]", "^", "^", "^^$LINK<Research output=45> at this base is doubled."]
r = layout(lines, (160, 150, 320, 180), fonts, extent)
for i, f in enumerate(fonts): print("font", i, spec[i], f)
print("H", r["H"], "y0", r["y0"], "LH", r["line_height"], "y_shift", r["y_shift"])
t = r["lines"][0]["runs"][0]; b = r["lines"][3]["runs"][0]
rows = [("title TextOut y (cell top)", t["y_textout"], 225), ("title baseline", t["baseline"], 238),
        ("title cap-top (baseline-10)", t["baseline"] - 10, 228), ("title origin x (ink 259 = +2 bearing)", t["x"], 257),
        ("body baseline", b["baseline"], 274), ("body cap-top (baseline-7)", b["baseline"] - 7, 267),
        ("body origin x", b["x"], 226), ("title->body baseline delta", b["baseline"] - t["baseline"], 36)]
bad = 0
for n, p, m in rows:
    print(f"{n:42s} predicted {p:4d}  measured {m:4d}  {'OK' if abs(p-m) <= 1 else 'MISMATCH'}"); bad += abs(p-m) > 1
for l in r["lines"]: print(l["y"], l["kind"], [(q["text"], q["slot"], q["x"], q["y_textout"]) for q in l["runs"]])
def test_supercollider(): assert bad == 0
sys.exit(bad) if __name__ == "__main__" else None
