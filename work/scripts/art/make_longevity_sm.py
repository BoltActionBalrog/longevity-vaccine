"""Render the Longevity Mods logo mark (the geometry of the website's SVG logo) as a
200x120 8-bit PCX in the game's popup-art format (palette of space_sm.pcx / ac_logo_sm.pcx,
index 255 = the four corner key pixels), plus a 4x PNG preview.

Usage: py make_longevity_sm.py <game_dir> <out_dir>
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

GAME = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

W, H = 200, 120           # popup art size (every *_sm.pcx)
MARK = 104                # mark height in art pixels (64 svg units -> MARK px)
S = 8                     # supersampling
U = MARK * S / 64.0       # px per svg unit at supersample
PALE = (0xB9, 0xD3, 0xD1) # website "pale icon tone"
DIM = (0x6E, 0x8A, 0x88)  # planet body, a darker take on the same hue

def P(x, y):
    return (x * U, y * U)

def poly(cmds):
    """Tiny SVG path reader for M/H/V/Z absolute commands."""
    pts, x, y = [], 0.0, 0.0
    tok = cmds.replace('Z', ' Z ').replace('M', ' M ').replace('H', ' H ').replace('V', ' V ').split()
    i = 0
    while i < len(tok):
        t = tok[i]
        if t == 'M':
            x, y = float(tok[i + 1]), float(tok[i + 2]); pts.append((x, y)); i += 3
        elif t == 'H':
            x = float(tok[i + 1]); pts.append((x, y)); i += 2
        elif t == 'V':
            y = float(tok[i + 1]); pts.append((x, y)); i += 2
        else:
            i += 1
    return [P(*p) for p in pts]

size = int(64 * U)
# --- layer 1: the outer stepped frame (stroke 3, no fill) ---
frame = Image.new('L', (size, size), 0)
d = ImageDraw.Draw(frame)
d.line(poly('M4 10H7V7H10V4H54V7H57V10H60V54H57V57H54V60H10V57H7V54H4Z') + [P(4, 10)],
       fill=255, width=int(round(3 * U)), joint='miter')

# --- clip: the inside region ---
clip = Image.new('L', (size, size), 0)
ImageDraw.Draw(clip).polygon(poly('M9 13H11V11H13V9H51V11H53V13H55V51H53V53H51V55H13V53H11V51H9Z'), fill=255)

# --- layer 2: the planet (filled circle) ---
planet = Image.new('L', (size, size), 0)
cx, cy, r = P(32, 78.5) + (40 * U,)
ImageDraw.Draw(planet).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)

# --- layer 3: sun, horizon, meridian, rays (masked outside r=42.6 of the planet centre) ---
sky = Image.new('L', (size, size), 0)
d = ImageDraw.Draw(sky)
sx, sy, sr = P(32, 33.7) + (7.5 * U,)
d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=255)
d.rectangle([P(0, 32.7), P(64, 34.7)], fill=255)
d.rectangle([P(31, 0), P(33, 33.7)], fill=255)
for a, b in [((26.5, 24.2), (23.5, 19)), ((37.5, 24.2), (40.5, 19)),
             ((22.5, 28.2), (17.3, 25.2)), ((41.5, 28.2), (46.7, 25.2))]:
    d.line([P(*a), P(*b)], fill=255, width=int(round(3 * U)))
gap = Image.new('L', (size, size), 255)
gr = 42.6 * U
ImageDraw.Draw(gap).ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=0)
sky = Image.composite(sky, Image.new('L', (size, size), 0), gap)

# apply the clip to the inside layers
planet = Image.composite(planet, Image.new('L', (size, size), 0), clip)
sky = Image.composite(sky, Image.new('L', (size, size), 0), clip)

# --- compose RGBA mark ---
mark = Image.new('RGBA', (size, size), (0, 0, 0, 0))
mark.paste(Image.new('RGBA', (size, size), DIM + (255,)), mask=planet)
mark.paste(Image.new('RGBA', (size, size), PALE + (255,)), mask=sky)
mark.paste(Image.new('RGBA', (size, size), PALE + (255,)), mask=frame)
mark = mark.resize((MARK, MARK), Image.LANCZOS)

# --- backdrop: black with a faint teal glow low-centre (behind the planet) ---
art = Image.new('RGB', (W, H), (0, 0, 0))
glow = Image.new('L', (W, H), 0)
gd = ImageDraw.Draw(glow)
gcx, gcy = W // 2, H - 10
for rr, v in ((70, 22), (52, 40), (34, 58)):
    gd.ellipse([gcx - rr, gcy - rr * 0.55, gcx + rr, gcy + rr * 0.55], fill=v)
glow = glow.filter(ImageFilter.GaussianBlur(10))
art.paste(Image.new('RGB', (W, H), (10, 40, 44)), mask=glow)
art.paste(mark, ((W - MARK) // 2, (H - MARK) // 2), mark)

# --- quantise to the game's popup-art palette (space_sm.pcx == ac_logo_sm.pcx) ---
ref = Image.open(GAME / 'space_sm.pcx')
pal = ref.getpalette()
palimg = Image.new('P', (1, 1)); palimg.putpalette(pal)
q = art.quantize(palette=palimg, dither=Image.Dither.NONE)
px = q.load()
bad = sum(1 for y in range(H) for x in range(W) if px[x, y] == 255)
assert bad == 0, f'{bad} interior pixels mapped to the key index'
for x, y in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)):
    px[x, y] = 255
q.save(OUT / 'longevity_sm.pcx')

# --- preview: 4x nearest, plus the reference beside it ---
pv = Image.new('RGB', (W * 4 * 2 + 16, H * 4), (60, 60, 60))
pv.paste(q.convert('RGB').resize((W * 4, H * 4), Image.NEAREST), (0, 0))
pv.paste(ref.convert('RGB').resize((W * 4, H * 4), Image.NEAREST), (W * 4 + 16, 0))
pv.save(OUT / 'longevity_sm_preview.png')
chk = Image.open(OUT / 'longevity_sm.pcx')
print('wrote', OUT / 'longevity_sm.pcx', chk.size, chk.mode, 'palette==space_sm:', chk.getpalette() == pal)
