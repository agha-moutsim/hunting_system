"""
Build the wordmark hero.

Type is converted to outlines, because an SVG loaded through <img> cannot fetch
a web font: <text font-family="Plus Jakarta Sans"> would silently fall back to
whatever the viewer happens to have, which is not a wordmark.
"""
import base64
import io
import pathlib
import re
import urllib.request

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

TMP = pathlib.Path(r"C:\Users\Agha Moutsim\AppData\Local\Temp\opencode")
REPO = pathlib.Path(r"C:\Users\Agha Moutsim\Desktop\ebay-hunter")
OUT = REPO / "assets" / "brand" / "hero.svg"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

WORD = "eBay Hunter"

# ---------------------------------------------------------------- palette
BG        = "#27233F"
BG_MID    = "#2E2950"
BLUE      = "#0D1CC4"
LIME      = "#CBFD03"
WHITE     = "#FFFFFF"
DIM       = "#8A90A0"

# ---------------------------------------------------------------- font
css_url = ("https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans"
           ":wght@700&display=swap")
req = urllib.request.Request(css_url, headers={"User-Agent": UA})
css = urllib.request.urlopen(req, timeout=40).read().decode("utf-8")
print(f"  css: {len(css)} bytes")

# Google returns one @font-face per subset; take the basic-latin one.
blocks = re.findall(r"@font-face\s*\{(.*?)\}", css, re.S)
pick = None
for b in blocks:
    rng = re.search(r"unicode-range:\s*([^;]+);", b)
    url = re.search(r"url\((https://[^)]+\.woff2)\)", b)
    if url and rng and "U+0000-00FF" in rng.group(1).replace(" ", ""):
        pick = url.group(1)
if not pick:
    raise SystemExit("could not find a latin woff2 in the Google CSS")

print(f"  font: {pick.rsplit('/', 1)[-1]}")
font_bytes = urllib.request.urlopen(
    urllib.request.Request(pick, headers={"User-Agent": UA}), timeout=40).read()
(TMP / "jakarta700.woff2").write_bytes(font_bytes)
print(f"  woff2: {len(font_bytes)/1024:.1f} KB (subset)")

font = TTFont(io.BytesIO(font_bytes))
upem = font["head"].unitsPerEm
cmap = font.getBestCmap()
glyphset = font.getGlyphSet()
hmtx = font["hmtx"]
try:
    cap = font["OS/2"].sCapHeight
except Exception:
    cap = int(upem * 0.70)
print(f"  upem={upem}  capHeight={cap}")

# ---------------------------------------------------------------- glyphs
missing = [c for c in WORD if c != " " and ord(c) not in cmap]
if missing:
    raise SystemExit(f"subset lacks glyphs: {missing}")

shapes = []          # (x_cursor_in_font_units, path_d)
cursor = 0.0
for ch in WORD:
    if ch == " ":
        cursor += hmtx[cmap[ord(" ")]] [0]
        continue
    gname = cmap[ord(ch)]
    pen = SVGPathPen(glyphset)
    glyphset[gname].draw(pen)
    d = pen.getCommands()
    if d:
        shapes.append((cursor, d))
    cursor += hmtx[gname][0]

advance = cursor
print(f"  word: {len(shapes)} glyphs, advance={advance} units")

# ---------------------------------------------------------------- layout
W, H = 2560, 640
TEXT_W = 1180.0
scale = TEXT_W / advance
cap_px = cap * scale
MARK = cap_px                        # mark sized to the cap band
GAP = cap_px * 0.46
lockup_w = MARK + GAP + TEXT_W
left = (W - lockup_w) / 2.0
baseline = H / 2.0 + cap_px / 2.0 + cap_px * 0.012

print(f"  scale={scale:.4f}  cap={cap_px:.1f}px  mark={MARK:.1f}px")
print(f"  lockup={lockup_w:.0f}px  left={left:.0f}  baseline={baseline:.1f}")

tx = left + MARK + GAP

# Glyph runs, one <path> each, offset by its own advance.
glyph_svg = "\n    ".join(
    f'<path transform="translate({x:.1f} 0)" d="{d}"/>' for x, d in shapes
)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{W}" height="{H}" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">
  <defs>
    <!-- Quiet base: a slow vertical lift, so the field is not a flat fill but
         still reads as one colour. -->
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0"    stop-color="#242038"/>
      <stop offset="0.5"  stop-color="{BG_MID}"/>
      <stop offset="1"    stop-color="#242038"/>
    </linearGradient>

    <!-- Light behind the lockup. Very low opacity: it should register as the
         surface being lit, never as a shape. -->
    <radialGradient id="glow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0"   stop-color="{LIME}" stop-opacity="0.10"/>
      <stop offset="0.55" stop-color="{BLUE}" stop-opacity="0.07"/>
      <stop offset="1"   stop-color="{BLUE}" stop-opacity="0"/>
    </radialGradient>

    <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75">
      <stop offset="0.55" stop-color="#000000" stop-opacity="0"/>
      <stop offset="1"    stop-color="#000000" stop-opacity="0.36"/>
    </radialGradient>

    <!-- Fine hairline grid: structure you notice only if you look. -->
    <pattern id="grid" patternUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
      <path d="M64 0 L0 0 0 64" fill="none" stroke="{WHITE}" stroke-opacity="0.045" stroke-width="1"/>
    </pattern>
  </defs>

  <rect x="0" y="0" width="{W}" height="{H}" fill="url(#bg)"/>
  <rect x="0" y="0" width="{W}" height="{H}" fill="url(#grid)"/>
  <ellipse cx="{W/2:.0f}" cy="{H/2:.0f}" rx="{lockup_w*0.72:.0f}" ry="{H*0.72:.0f}" fill="url(#glow)"/>
  <rect x="0" y="0" width="{W}" height="{H}" fill="url(#vignette)"/>

  <!-- The mark: facing selection brackets around a single point. Says "one
       thing chosen from a field". A rounded square with a dot was rejected
       after render: at this weight it is the media-record glyph. Kept
       deliberately open at the top and bottom so it does not close into a
       frame, and sized to the cap band so it locks to the type. -->
  <g fill="none" stroke="{LIME}" stroke-width="{MARK*0.085:.1f}"
     stroke-linecap="round" stroke-linejoin="round">
    <path d="M{left + MARK*0.40:.1f} {baseline - cap_px:.1f} H{left:.1f} V{baseline:.1f} H{left + MARK*0.40:.1f}"/>
    <path d="M{left + MARK*0.60:.1f} {baseline - cap_px:.1f} H{left + MARK:.1f} V{baseline:.1f} H{left + MARK*0.60:.1f}"/>
  </g>
  <circle cx="{left + MARK/2:.1f}" cy="{baseline - cap_px/2:.1f}" r="{MARK*0.135:.1f}" fill="{WHITE}"/>

  <!-- Wordmark, set in Plus Jakarta Sans Bold and converted to outlines. -->
  <g transform="translate({tx:.1f} {baseline:.1f}) scale({scale:.6f} {-scale:.6f})"
     fill="{WHITE}">
    {glyph_svg}
  </g>
</svg>
'''

OUT.write_text(svg, encoding="utf-8", newline="")
print(f"\n  wrote {OUT}  ({len(svg.encode('utf-8'))/1024:.2f} KB)")


# --- guard -------------------------------------------------------------
import re as _re, xml.dom.minidom as _m
_s = OUT.read_text(encoding="utf-8")
assert _m.parse(str(OUT)), "not well-formed XML"
_bad = [c for c in _re.findall(r"<!--(.*?)-->", _s, _re.S) if "--" in c]
assert not _bad, f"double hyphen inside a comment breaks strict XML: {_bad}"
_ids = set(_re.findall(r'\sid="([^"]+)"', _s))
_refs = set(_re.findall(r'url\(#([^)]+)\)', _s))
assert not (_refs - _ids), f"unresolved refs: {_refs - _ids}"
print(f"  guard passed: well-formed, {len(_ids)} defs, "
      f"{len(_refs)} refs, no illegal comments")
