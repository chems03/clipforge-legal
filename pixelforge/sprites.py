"""Procedural HD pixel art: characters, props and backgrounds.

Scenes are drawn on a 270x480 canvas (8x upscale = 4K vertical). Story files
keep using the old 135x240 coordinates; multiply by U to get canvas pixels.

Every shape goes through `paint()`, which adds a hue-shifted outline, a
shadow band on the bottom-right and a highlight on the top-left, so parts
read as shaded pixel art instead of flat fills.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

U = 2
W, H = 135 * U, 240 * U
FLOOR_Y = 172 * U
OL = (34, 26, 52)
WHITE = (252, 250, 244)
DARK = (40, 24, 70)

BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16.0

_FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
               "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]


def _font(size):
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, int(size))
        except OSError:
            continue
    return ImageFont.load_default(int(size))


# --------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------

def hexc(c):
    if isinstance(c, (tuple, list)):
        return tuple(c)
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def ramp(c):
    return {"shadow": mix(c, (52, 36, 98), 0.34), "deep": mix(c, DARK, 0.55),
            "light": mix(c, (255, 250, 225), 0.38),
            "line": mix(mix(c, (0, 0, 0), 0.62), DARK, 0.4)}


# --------------------------------------------------------------------------
# Masks & painting
# --------------------------------------------------------------------------

def _box(b):
    x0, y0, x1, y1 = [int(round(v)) for v in b]
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


class Shape:
    """A boolean mask built from PIL primitives (no antialiasing).

    Coordinates are in design units; `k` rasterises them k times bigger, which
    adds detail instead of fattening pixels.
    """

    def __init__(self, w, h, k=1.0):
        self.k = k
        self.img = Image.new("L", (int(w * k), int(h * k)), 0)
        self.d = ImageDraw.Draw(self.img)
        self.d.fontmode = "1"

    def _b(self, b):
        return _box([v * self.k for v in b])

    def ellipse(self, b, v=255):
        self.d.ellipse(self._b(b), fill=v)
        return self

    def rrect(self, b, r, v=255):
        b = self._b(b)
        r = max(0, min(int(r * self.k), (b[2] - b[0]) // 2, (b[3] - b[1]) // 2))
        self.d.rounded_rectangle(b, r, fill=v)
        return self

    def rect(self, b, v=255):
        self.d.rectangle(self._b(b), fill=v)
        return self

    def poly(self, pts, v=255):
        self.d.polygon([(int(round(x * self.k)), int(round(y * self.k))) for x, y in pts], fill=v)
        return self

    def chord(self, b, a0, a1, v=255):
        self.d.chord(self._b(b), a0, a1, fill=v)
        return self

    def line(self, pts, width, v=255):
        pts = [(int(round(x * self.k)), int(round(y * self.k))) for x, y in pts]
        width = max(1, int(round(width * self.k)))
        self.d.line(pts, fill=v, width=width)
        if width > 2:
            r = width / 2
            for x, y in pts:
                self.d.ellipse(_box([x - r + 0.5, y - r + 0.5, x + r - 0.5, y + r - 0.5]), fill=v)
        return self

    def arc(self, b, a0, a1, width, v=255):
        self.d.arc(self._b(b), a0, a1, fill=v, width=max(1, int(round(width * self.k))))
        return self

    def text(self, xy, s, size, v=255):
        f = _font(size * self.k)
        x0, y0, x1, y1 = self.d.textbbox((0, 0), s, font=f)
        self.d.text((xy[0] * self.k - (x0 + x1) / 2, xy[1] * self.k - (y0 + y1) / 2), s, font=f, fill=v)
        return self

    @property
    def m(self):
        return np.array(self.img) > 127


def shift(m, dx, dy):
    """out[p] = m[p - (dx, dy)]"""
    out = np.zeros_like(m)
    h, w = m.shape
    if abs(dx) >= w or abs(dy) >= h:
        return out
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = \
        m[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def dilate(m, r=1):
    o = m.copy()
    for _ in range(r):
        o = o | shift(o, 1, 0) | shift(o, -1, 0) | shift(o, 0, 1) | shift(o, 0, -1)
    return o


def erode(m, r=1):
    return ~dilate(~m, r)


def put(arr, m, c, a=255):
    arr[m, 0], arr[m, 1], arr[m, 2] = c[0], c[1], c[2]
    arr[m, 3] = a


def paint(arr, m, c, outline=1, shade_px=None, light=True, line=None):
    """Fill mask `m` with colour `c`, plus outline, shadow and highlight."""
    if not m.any():
        return
    c = hexc(c)
    r = ramp(c)
    if outline:
        put(arr, dilate(m, outline) & ~m, line or r["line"])
    put(arr, m, c)
    if shade_px is None:
        ys, xs = np.nonzero(m)
        shade_px = max(1, int(min(np.ptp(ys) + 1, np.ptp(xs) + 1) * 0.16))
    if shade_px:
        sh = m & ~shift(m, -shade_px, -shade_px)
        put(arr, sh, r["shadow"])
        if shade_px >= 4:
            put(arr, m & ~shift(m, -(shade_px // 3), -(shade_px // 3)), r["deep"])
    if light:
        inner = erode(m, 1)
        hl = inner & ~shift(inner, 2, 2)
        if shade_px:
            hl &= shift(m, -shade_px, -shade_px)
        put(arr, hl, r["light"])


def grad(arr, box, c1, c2, levels=6, mask=None, radial=None):
    """Ordered-dither gradient (vertical, or radial=(cx, cy, radius))."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    if radial:
        cx, cy, rad = radial
        t = np.clip(np.hypot(xx - cx, yy - cy) / rad, 0, 1)
    else:
        t = (yy - y0) / max(1, y1 - y0 - 1)
    v = t * (levels - 1)
    lo = np.floor(v)
    idx = np.clip(lo + ((v - lo) > BAYER[yy % 4, xx % 4]), 0, levels - 1) / (levels - 1)
    c1, c2 = np.array(c1, float), np.array(c2, float)
    col = (c1 + (c2 - c1) * idx[..., None]).astype(np.uint8)
    reg = arr[y0:y1, x0:x1]
    m = np.ones(idx.shape, bool) if mask is None else mask[y0:y1, x0:x1]
    reg[m, :3] = col[m]
    reg[m, 3] = 255


def vignette(arr, strength=0.22, levels=4):
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    t = np.clip((np.hypot((xx - w / 2) / (w / 2), (yy - h * 0.45) / (h * 0.62)) - 0.55) / 0.6, 0, 1)
    v = t * (levels - 1)
    lo = np.floor(v)
    idx = np.clip(lo + ((v - lo) > BAYER[yy % 4, xx % 4]), 0, levels - 1) / (levels - 1)
    f = 1 - strength * idx
    arr[..., :3] = (arr[..., :3] * f[..., None]).astype(np.uint8)


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------

SKINS = {"light": "#f7d4b5", "medium": "#dca27c", "tan": "#b97c55", "dark": "#7c4b32"}

DEFAULT_CHAR = {
    "skin": "light", "hair": "short", "hair_color": "#3b2a20",
    "shirt": "#3d6fd6", "pants": "#2b2f45", "shoes": "#f4f4f4", "eyes": "#5a3a22",
    "size": 1.0, "acc": [],
}

CK = 1.25               # characters are rasterised bigger than their design
SW, SH = 180, 250       # sprite box (design units)
_CX, _F = 90, 244       # anchor in design units
SCX, SFEET = int(_CX * CK), int(_F * CK)  # anchor in sprite pixels
ROWS = (np.arange(int(SH * CK)) / CK)[:, None]  # design-unit y of each sprite row


def draw_character(spec, expr="neutral", pose="stand", blink=False, flip=False,
                   hold=None, t=0.0):
    """Return (RGBA sprite, head_top_y) with feet at (SCX, SFEET)."""
    s = dict(DEFAULT_CHAR)
    s.update(spec or {})
    acc = s["acc"]
    skin = hexc(SKINS.get(s["skin"], s["skin"]))
    hair = hexc(s["hair_color"])
    shirt = hexc(s["shirt"])
    pants = hexc(s["pants"])
    shoes = hexc(s["shoes"])
    kid = s["size"] < 1.0
    bk = s["size"]
    hk = 0.9 if kid else 1.0

    arr = np.zeros((int(SH * CK), int(SW * CK), 4), np.uint8)
    S = lambda: Shape(SW, SH, CK)
    cx, F = _CX, _F

    shoe_h = 13
    leg_len = int(38 * bk)
    tor_h = int(54 * bk)
    tor_w = int(48 * (0.82 + 0.18 * bk))
    head_w, head_h = int(60 * hk), int(58 * hk)
    y_shoe = F - shoe_h
    y_hip = y_shoe - leg_len
    y_tbot = y_hip + 8
    y_ttop = y_tbot - tor_h
    y_hbot = y_ttop + 8
    y_htop = y_hbot - head_h
    hx0, hx1 = cx - head_w / 2, cx + head_w / 2
    ymid = y_htop + head_h * 0.56
    g = dict(cx=cx, F=F, hx0=hx0, hx1=hx1, y_htop=y_htop, y_hbot=y_hbot, head_w=head_w,
             head_h=head_h, ymid=ymid, y_ttop=y_ttop, y_tbot=y_tbot, tor_w=tor_w)

    # ---- back layers (behind the body)
    _hair_back(arr, S, s["hair"], hair, g)
    if "hoodie" in acc:
        paint(arr, S().rrect([cx - tor_w / 2 + 3, y_ttop - 12, cx + tor_w / 2 - 3, y_ttop + 14], 10).m,
              mix(shirt, DARK, 0.18))

    # ---- legs & shoes
    legs = S().rect([cx - 16, y_hip, cx - 3, y_shoe + 2]).rect([cx + 3, y_hip, cx + 16, y_shoe + 2]).m
    paint(arr, legs, pants, shade_px=3)
    for x0 in (cx - 21, cx + 1):
        sm = S().rrect([x0, y_shoe, x0 + 21, F], 5).m
        paint(arr, sm, shoes, shade_px=2)
        put(arr, sm & (ROWS >= F - 3), mix(shoes, (120, 120, 140), 0.5))

    # ---- neck, dress, torso
    paint(arr, S().rect([cx - 7, y_hbot - 8, cx + 7, y_ttop + 6]).m, skin, shade_px=3)
    if "dress" in acc:
        skirt = S().poly([(cx - tor_w / 2 + 3, y_tbot - 10), (cx + tor_w / 2 - 3, y_tbot - 10),
                          (cx + tor_w / 2 + 9, y_hip + leg_len * 0.62),
                          (cx - tor_w / 2 - 9, y_hip + leg_len * 0.62)]).m
        paint(arr, skirt, shirt)
    torso = S().rrect([cx - tor_w / 2, y_ttop, cx + tor_w / 2, y_tbot], 13).m
    paint(arr, torso, shirt)
    if "dress" not in acc:
        rows = ROWS
        band = torso & (rows >= y_tbot - 8)
        paint(arr, band, pants, outline=0, shade_px=2, light=False)
        put(arr, torso & (rows == y_tbot - 9), ramp(pants)["line"])
    collar = S().ellipse([cx - 9, y_ttop - 3, cx + 9, y_ttop + 7]).m & torso
    put(arr, collar, mix(skin, (150, 90, 80), 0.25))
    if "hoodie" in acc:
        for dx in (-5, 5):
            put(arr, S().line([(cx + dx, y_ttop + 6), (cx + dx, y_ttop + 20)], 2).m, WHITE)
        paint(arr, S().rrect([cx - tor_w / 2 + 9, y_tbot - 26, cx + tor_w / 2 - 9, y_tbot - 12], 4).m,
              mix(shirt, DARK, 0.12), shade_px=2)

    # ---- arms
    arm_len = int(36 * bk)
    sy = y_ttop + 10
    hands = {}
    for side in (-1, 1):
        sx = cx + side * (tor_w / 2 - 6)
        up = pose == "arms_up" or (pose == "wave" and side == 1)
        if up:
            wob = 5 * math.sin(t * 12) if pose == "wave" else 0
            hx, hy = sx + side * (16 + wob), sy - arm_len + 6
        else:
            hx, hy = sx + side * 8, sy + arm_len
        wx, wy = sx + (hx - sx) * 0.82, sy + (hy - sy) * 0.82
        paint(arr, S().line([(sx, sy), (wx, wy)], 13).m, shirt, shade_px=3)
        paint(arr, S().ellipse([hx - 7, hy - 7, hx + 7, hy + 7]).m, skin, shade_px=2)
        hands[side] = (hx, hy)

    # ---- head
    for side in (-1, 1):
        ex = hx0 if side < 0 else hx1
        paint(arr, S().ellipse([ex - 7, ymid - 10, ex + 7, ymid + 8]).m, skin, shade_px=2)
        if "earrings" in acc:
            paint(arr, S().ellipse([ex - 3, ymid + 7, ex + 3, ymid + 13]).m, (245, 200, 60), shade_px=1)
    head = S().rrect([hx0, y_htop, hx1, y_hbot], head_w * 0.4).m
    paint(arr, head, skin, shade_px=7)
    if s["hair"] == "bald":
        put(arr, S().ellipse([hx0 + 12, y_htop + 6, hx0 + 24, y_htop + 12]).m, ramp(skin)["light"])

    if "beard" in acc:
        rows = ROWS
        beard = head & (rows > ymid + 12) & ~S().ellipse([cx - 9, y_hbot - 16, cx + 15, y_hbot - 5]).m
        paint(arr, beard, hair, outline=0, shade_px=3)
    _face(arr, S, g, expr, blink, skin, hexc(s["eyes"]))
    _hair_front(arr, S, s["hair"], hair, g)
    _accessories(arr, S, acc, hair, g, t)

    img = Image.fromarray(arr, "RGBA")
    if hold:
        hx, hy = hands[1]
        p = prop_image(hold, 30 * CK, t)
        img.alpha_composite(p, (int((hx + 6) * CK - p.width / 2), int((hy - 8) * CK - p.height / 2)))
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    top = y_htop - 14 if s["hair"] in ("bun", "spiky", "afro", "mohawk") or "crown" in acc else y_htop
    return img, int(top * CK)


def _hair_back(arr, S, style, c, g):
    cx, hx0, hx1, y_htop, head_h, head_w = g["cx"], g["hx0"], g["hx1"], g["y_htop"], g["head_h"], g["head_w"]
    if style == "long":
        paint(arr, S().rrect([hx0 - 7, y_htop + 8, hx1 + 7, g["y_ttop"] + 30], 12).m, c)
    elif style == "afro":
        paint(arr, S().ellipse([hx0 - 18, y_htop - 26, hx1 + 18, y_htop + head_h * 0.78]).m, c)
    elif style == "ponytail":
        paint(arr, S().ellipse([hx0 - 24, y_htop + 6, hx0 + 6, y_htop + 58]).m, c)
    elif style == "bun":
        paint(arr, S().ellipse([cx - 15, y_htop - 26, cx + 15, y_htop + 4]).m, c)
        put(arr, S().rrect([cx - 10, y_htop - 2, cx + 10, y_htop + 4], 2).m, (240, 110, 160))


def _hair_front(arr, S, style, c, g):
    if style == "bald":
        return
    cx, hx0, hx1, y_htop, head_h, head_w = g["cx"], g["hx0"], g["hx1"], g["y_htop"], g["head_h"], g["head_w"]
    rows = ROWS
    cap_y = y_htop + head_h * 0.30
    if style == "mohawk":
        paint(arr, S().rrect([cx - 8, y_htop - 18, cx + 8, y_htop + 18], 6).m, c)
        return
    cap = S().ellipse([hx0 - 4, y_htop - 6, hx1 + 4, y_htop + head_h * 0.98]).m & (rows < cap_y)
    sh = S()
    # fringe: a zigzag of locks along the cap edge
    n = 7
    for i in range(n):
        x = hx0 + 2 + i * (head_w - 4) / n
        drop = 10 if i % 2 == 0 else 6
        if style == "bun":
            drop = 4 if i > 2 else 8
        sh.poly([(x - 1, cap_y - 2), (x + (head_w - 4) / n + 1, cap_y - 2),
                 (x + (head_w - 4) / n * 0.7, cap_y + drop)])
    sh.poly([(hx0 - 3, cap_y - 6), (hx0 + 5, cap_y - 6), (hx0 + 3, y_htop + head_h * 0.5), (hx0 - 2, y_htop + head_h * 0.5)])
    sh.poly([(hx1 - 5, cap_y - 6), (hx1 + 3, cap_y - 6), (hx1 + 2, y_htop + head_h * 0.5), (hx1 - 3, y_htop + head_h * 0.5)])
    if style == "spiky":
        for i in range(5):
            x = hx0 + 4 + i * (head_w - 8) / 4
            sh.poly([(x - 9, y_htop + 6), (x + 9, y_htop + 6), (x + 3, y_htop - 12 - (i % 2) * 5)])
    if style in ("curly", "afro"):
        for i in range(9):
            a = math.pi * (1.05 + i * 0.9 / 8)
            x = cx + (head_w / 2 + 1) * math.cos(a)
            y = y_htop + head_h * 0.42 + (head_h * 0.5) * math.sin(a)
            sh.ellipse([x - 8, y - 8, x + 8, y + 8])
    if style in ("long",):
        sh.rrect([hx0 - 7, cap_y - 6, hx0 + 6, g["y_hbot"] + 8], 4)
        sh.rrect([hx1 - 6, cap_y - 6, hx1 + 7, g["y_hbot"] + 8], 4)
    hm = cap | sh.m
    paint(arr, hm, c, shade_px=4)
    # strands
    r = ramp(c)
    st = S()
    for i in range(4):
        x = hx0 + 14 + i * (head_w - 28) / 3
        st.line([(x, y_htop + 4), (x + 4, cap_y - 4)], 1)
    put(arr, st.m & erode(hm, 2), r["shadow"])
    shine = S().arc([hx0 + 8, y_htop + 3, hx1 - 4, y_htop + head_h * 0.75], 205, 250, 2).m
    put(arr, shine & erode(hm, 1), r["light"])


def _face(arr, S, g, expr, blink, skin, eye_c):
    cx, y_htop, head_h, head_w = g["cx"], g["y_htop"], g["head_h"], g["head_w"]
    ey = y_htop + head_h * 0.56
    exs = (cx - head_w * 0.2 + 2, cx + head_w * 0.2 + 3)
    my = y_htop + head_h * 0.83
    mx = cx + 3
    pink = (255, 120, 140)

    # cheeks
    k = 0.55 if expr in ("happy", "laugh", "love") else 0.28
    for ex in exs:
        put(arr, S().ellipse([ex - 8, ey + 9, ex + 3, ey + 14]).m, mix(skin, pink, k))
    # nose
    put(arr, S().rect([cx + 5, ey + 9, cx + 7, ey + 10]).m, ramp(skin)["shadow"])

    # eyes
    for i, ex in enumerate(exs):
        if blink or expr in ("happy", "laugh"):
            if expr in ("happy", "laugh") and not blink:
                put(arr, S().arc([ex - 6, ey - 4, ex + 6, ey + 6], 200, 340, 3).m, OL)
            else:
                put(arr, S().arc([ex - 6, ey - 6, ex + 6, ey + 4], 20, 160, 3).m, OL)
            continue
        if expr == "love":
            heart = S().ellipse([ex - 6, ey - 5, ex, ey + 1]).ellipse([ex, ey - 5, ex + 6, ey + 1]) \
                       .poly([(ex - 6, ey - 1), (ex + 6, ey - 1), (ex, ey + 7)]).m
            paint(arr, heart, (235, 55, 90), shade_px=2)
            continue
        big = expr == "shocked"
        w2, h2 = (7, 8) if big else (5, 7)
        sclera = S().rrect([ex - w2, ey - h2, ex + w2, ey + h2], 4).m
        put(arr, dilate(sclera) & ~sclera, OL)
        put(arr, sclera, WHITE)
        put(arr, sclera & ~shift(sclera, 0, 3), (210, 215, 235))  # lid shadow
        if big:
            put(arr, S().rect([ex - 1, ey - 1, ex + 2, ey + 2]).m, OL)
        else:
            iris = S().rrect([ex - 3, ey - 3, ex + 4, ey + 7], 2).m & sclera
            put(arr, iris, eye_c)
            put(arr, S().rect([ex - 1, ey - 1, ex + 2, ey + 4]).m & sclera, OL)
            put(arr, S().rect([ex - 2, ey - 3, ex - 1, ey - 2]).m, WHITE)
            put(arr, S().rect([ex + 3, ey + 4, ex + 3, ey + 4]).m, WHITE)
        put(arr, S().rect([ex - w2, ey - h2 - 1, ex + w2, ey - h2]).m, OL)  # lash line
        if expr in ("angry", "smirk"):
            put(arr, sclera & (ROWS < ey - 2), skin)
            put(arr, S().rect([ex - w2, ey - 3, ex + w2, ey - 2]).m & dilate(sclera), OL)
        if expr == "sad":
            paint(arr, S().ellipse([ex - 2, ey + 10, ex + 3, ey + 17]).m, (120, 190, 250), shade_px=1)

    # brows
    by = ey - 12
    bs = S()
    for i, ex in enumerate(exs):
        inner = 1 if i == 0 else -1  # +1: inner end is to the right
        if expr == "angry":
            bs.line([(ex - 6 * inner, by - 3), (ex + 6 * inner, by + 3)], 3)
        elif expr in ("sad", "worried"):
            bs.line([(ex - 6 * inner, by + 2), (ex + 6 * inner, by - 3)], 3)
        elif expr == "shocked":
            bs.arc([ex - 7, by - 6, ex + 7, by + 2], 200, 340, 3)
        elif expr == "smirk" and i == 1:
            bs.line([(ex - 6, by - 4), (ex + 6, by - 2)], 3)
        else:
            bs.line([(ex - 6, by), (ex + 6, by)], 3)
    put(arr, bs.m, OL)

    # mouth
    red = (170, 40, 60)
    if expr == "happy" or expr == "love":
        put(arr, S().arc([mx - 8, my - 8, mx + 8, my + 3], 20, 160, 2).m, OL)
    elif expr == "laugh":
        mouth = S().chord([mx - 10, my - 9, mx + 10, my + 9], 0, 180).m
        put(arr, dilate(mouth) & ~mouth, OL)
        put(arr, mouth, red)
        put(arr, mouth & (ROWS <= my + 1), WHITE)
        put(arr, S().ellipse([mx - 5, my + 4, mx + 5, my + 12]).m & mouth, (240, 110, 130))
    elif expr == "sad":
        put(arr, S().arc([mx - 7, my - 1, mx + 7, my + 9], 200, 340, 2).m, OL)
    elif expr == "shocked":
        mouth = S().ellipse([mx - 5, my - 5, mx + 5, my + 8]).m
        put(arr, dilate(mouth) & ~mouth, OL)
        put(arr, mouth, red)
        put(arr, S().ellipse([mx - 3, my + 2, mx + 3, my + 7]).m & mouth, (240, 110, 130))
    elif expr == "angry":
        mouth = S().rrect([mx - 9, my - 3, mx + 9, my + 5], 2).m
        put(arr, dilate(mouth) & ~mouth, OL)
        put(arr, mouth, WHITE)
        put(arr, S().rect([mx - 9, my + 1, mx + 9, my + 1]).m, (180, 180, 200))
    elif expr == "worried":
        put(arr, S().line([(mx - 7, my + 1), (mx - 3, my - 1), (mx + 1, my + 1), (mx + 5, my - 1),
                           (mx + 8, my + 1)], 2).m, OL)
    elif expr == "smirk":
        put(arr, S().line([(mx - 6, my + 1), (mx + 4, my + 1), (mx + 8, my - 3)], 2).m, OL)
    else:
        put(arr, S().line([(mx - 5, my), (mx + 5, my)], 2).m, OL)


def _accessories(arr, S, acc, hair, g, t):
    cx, hx0, hx1, y_htop, head_h, head_w = g["cx"], g["hx0"], g["hx1"], g["y_htop"], g["head_h"], g["head_w"]
    ey = y_htop + head_h * 0.56
    exs = (cx - head_w * 0.2 + 2, cx + head_w * 0.2 + 3)
    my = y_htop + head_h * 0.83
    gold = (248, 196, 56)
    if "glasses" in acc:
        fr = np.zeros(ROWS.shape[:1] + (int(SW * CK),), bool)
        for ex in exs:
            o = S().rrect([ex - 11, ey - 10, ex + 11, ey + 10], 5).m
            fr |= o & ~erode(o, 2)
        fr |= S().line([(exs[0] + 11, ey - 3), (exs[1] - 11, ey - 3)], 2) \
                 .line([(hx0 - 2, ey - 5), (exs[0] - 11, ey - 5)], 2).m
        put(arr, fr, (40, 34, 58))
        for ex in exs:
            put(arr, S().line([(ex + 4, ey - 7), (ex + 8, ey - 3)], 2).m, (220, 240, 255))
    if "mustache" in acc:
        mu = S().ellipse([cx - 11, my - 10, cx + 4, my - 2]).ellipse([cx + 2, my - 10, cx + 17, my - 2]).m
        paint(arr, mu, hair, shade_px=2)
    if "crown" in acc:
        base = y_htop - 2
        cr = S().rect([cx - 22, base - 8, cx + 22, base + 4])
        for x in (cx - 22, cx, cx + 22):
            cr.poly([(x - 9, base - 6), (x + 9, base - 6), (x, base - 24)])
        paint(arr, cr.m & ~S().rect([0, 0, cx - 23, SH]).m & ~S().rect([cx + 23, 0, SW, SH]).m, gold)
        for x, col in ((cx - 13, (60, 120, 230)), (cx, (230, 50, 70)), (cx + 13, (60, 190, 110))):
            paint(arr, S().ellipse([x - 3, base - 5, x + 3, base + 1]).m, col, shade_px=1)
    if "cap" in acc:
        red = (220, 60, 60)
        dome = S().ellipse([hx0 - 5, y_htop - 8, hx1 + 5, y_htop + head_h * 0.9]).m & \
            (ROWS < y_htop + head_h * 0.32)
        paint(arr, dome, red)
        paint(arr, S().poly([(hx1 - 10, y_htop + head_h * 0.26), (hx1 + 22, y_htop + head_h * 0.28),
                             (hx1 + 20, y_htop + head_h * 0.36), (hx1 - 10, y_htop + head_h * 0.36)]).m,
              shade(red, 0.8), shade_px=2)
    if "beanie" in acc:
        col = (150, 90, 210)
        b = S().rrect([hx0 - 5, y_htop - 12, hx1 + 5, y_htop + head_h * 0.36], 16).m
        paint(arr, b, col)
        rows = ROWS
        band = b & (rows > y_htop + head_h * 0.36 - 8)
        put(arr, band, ramp(col)["shadow"])
        for x in range(int(hx0), int(hx1) + 4, 5):
            put(arr, band & S().rect([x, 0, x, SH]).m, ramp(col)["deep"])
        paint(arr, S().ellipse([cx - 8, y_htop - 22, cx + 8, y_htop - 6]).m, WHITE, shade_px=2)
    if "headphones" in acc:
        put(arr, S().arc([hx0 - 8, y_htop - 12, hx1 + 8, y_htop + head_h], 185, 355, 5).m, (60, 60, 75))
        for x in (hx0 - 4, hx1 + 4):
            paint(arr, S().rrect([x - 7, ey - 14, x + 7, ey + 12], 4).m, (70, 70, 90))
    if "police" in acc:
        col = (40, 60, 90)
        paint(arr, S().rrect([hx0 - 3, y_htop - 16, hx1 + 3, y_htop + 10], 6).m, col)
        paint(arr, S().rect([hx0 - 2, y_htop + 6, hx1 + 2, y_htop + 12]).m, (30, 30, 40), shade_px=1)
        paint(arr, S().poly([(hx0 + 4, y_htop + 12), (hx1 + 14, y_htop + 12), (hx1 + 8, y_htop + 18),
                             (hx0 + 4, y_htop + 18)]).m, (25, 25, 35), shade_px=1)
        paint(arr, S().ellipse([cx - 5, y_htop - 8, cx + 5, y_htop + 2]).m, gold, shade_px=1)


# --------------------------------------------------------------------------
# Props
# --------------------------------------------------------------------------

PROPS = ["thermometer", "eye_blue", "eye_brown", "eye_honey", "photo", "cake", "paper", "phone", "gift", "tv", "lock", "heart", "x", "check", "question",
         "exclam", "controller", "money", "book", "pizza", "clock", "star",
         "zzz", "bulb", "trophy", "sweat", "anger"]

_prop_cache = {}


def prop_image(kind, size, t=0.0):
    """RGBA image of a prop whose main body is about `size` pixels wide."""
    key = (kind, int(size), int(t * 8) if kind == "clock" else 0)
    if key in _prop_cache:
        return _prop_cache[key]
    B = int(size * 1.6) + 6
    arr = np.zeros((B, B, 4), np.uint8)
    S = lambda: Shape(B, B)
    c, s = B / 2, size / 2
    rows = np.arange(B)[:, None]

    if kind == "phone":
        body = S().rrect([c - .45 * s, c - .85 * s, c + .45 * s, c + .85 * s], .18 * s).m
        paint(arr, body, (50, 48, 66))
        scr = S().rrect([c - .34 * s, c - .7 * s, c + .34 * s, c + .7 * s], .08 * s).m
        grad(arr, (0, c - .7 * s, B, c + .7 * s + 1), (90, 160, 250), (170, 225, 255), mask=scr)
        put(arr, S().line([(c - .2 * s, c - .45 * s), (c + .05 * s, c - .7 * s)], 2).m & scr, WHITE)
        put(arr, S().rrect([c - .12 * s, c - .78 * s, c + .12 * s, c - .72 * s], 2).m, (30, 30, 40))
    elif kind == "gift":
        paint(arr, S().rrect([c - .8 * s, c - .3 * s, c + .8 * s, c + .85 * s], 3).m, (230, 70, 100))
        paint(arr, S().rrect([c - .92 * s, c - .55 * s, c + .92 * s, c - .22 * s], 3).m, (245, 95, 125))
        paint(arr, S().rect([c - .13 * s, c - .55 * s, c + .13 * s, c + .85 * s]).m, (250, 210, 70), shade_px=2)
        for d in (-1, 1):
            paint(arr, S().ellipse([c + d * .02 * s, c - .98 * s, c + d * .55 * s, c - .5 * s]).m,
                  (250, 210, 70), shade_px=2)
    elif kind == "tv":
        for d in (-1, 1):
            put(arr, S().line([(c + d * .5 * s, c + .7 * s), (c + d * .7 * s, c + .95 * s)], 4).m, OL)
        for x1, y1 in ((c - .5 * s, c - 1.15 * s), (c + .45 * s, c - 1.2 * s)):
            put(arr, S().line([(c, c - .65 * s), (x1, y1)], 2).m, (90, 90, 100))
            paint(arr, S().ellipse([x1 - 3, y1 - 3, x1 + 3, y1 + 3]).m, (230, 60, 60), shade_px=1)
        paint(arr, S().rrect([c - .98 * s, c - .68 * s, c + .98 * s, c + .72 * s], .2 * s).m, (90, 70, 100))
        scr = S().rrect([c - .8 * s, c - .52 * s, c + .55 * s, c + .56 * s], .14 * s).m
        grad(arr, (0, c - .52 * s, B, c + .56 * s), (90, 210, 235), (40, 130, 190), mask=scr)
        put(arr, dilate(scr) & ~scr, (40, 30, 50))
        put(arr, S().line([(c - .55 * s, c - .3 * s), (c - .3 * s, c - .45 * s)], 2).m & scr, WHITE)
        for yy in (-.3, .1):
            paint(arr, S().ellipse([c + .66 * s, c + yy * s, c + .86 * s, c + (yy + .2) * s]).m,
                  (220, 200, 90), shade_px=1)
    elif kind == "lock":
        ring = S().ellipse([c - .6 * s, c - 1.05 * s, c + .6 * s, c + .15 * s]).m & \
            ~S().ellipse([c - .38 * s, c - .83 * s, c + .38 * s, c - .07 * s]).m & (rows < c - .2 * s)
        ring |= S().rect([c - .6 * s, c - .45 * s, c - .38 * s, c - .1 * s]).rect(
            [c + .38 * s, c - .45 * s, c + .6 * s, c - .1 * s]).m
        paint(arr, ring, (190, 196, 214))
        paint(arr, S().rrect([c - .8 * s, c - .3 * s, c + .8 * s, c + .9 * s], .2 * s).m, (248, 192, 56))
        put(arr, S().ellipse([c - .14 * s, c + .05 * s, c + .14 * s, c + .33 * s])
            .poly([(c - .08 * s, c + .25 * s), (c + .08 * s, c + .25 * s), (c, c + .6 * s)]).m, (70, 40, 30))
    elif kind == "heart":
        hm = S().ellipse([c - .95 * s, c - .8 * s, c + .02 * s, c + .15 * s]) \
            .ellipse([c - .02 * s, c - .8 * s, c + .95 * s, c + .15 * s]) \
            .poly([(c - .9 * s, c - .2 * s), (c + .9 * s, c - .2 * s), (c, c + .9 * s)]).m
        paint(arr, hm, (236, 58, 92))
        put(arr, S().ellipse([c - .65 * s, c - .55 * s, c - .4 * s, c - .3 * s]).m, WHITE)
    elif kind == "x":
        paint(arr, S().line([(c - .7 * s, c - .7 * s), (c + .7 * s, c + .7 * s)], .34 * s)
              .line([(c + .7 * s, c - .7 * s), (c - .7 * s, c + .7 * s)], .34 * s).m, (232, 52, 64))
    elif kind == "check":
        paint(arr, S().line([(c - .75 * s, c), (c - .2 * s, c + .55 * s), (c + .8 * s, c - .6 * s)],
                            .34 * s).m, (60, 200, 100))
    elif kind in ("question", "exclam"):
        bub = S().rrect([c - .85 * s, c - .85 * s, c + .85 * s, c + .65 * s], .3 * s) \
            .poly([(c - .3 * s, c + .5 * s), (c + .15 * s, c + .5 * s), (c - .45 * s, c + 1.05 * s)]).m
        paint(arr, bub, WHITE, shade_px=3)
        glyph = S().text((c, c - .1 * s), "?" if kind == "question" else "!", 1.2 * s).m
        paint(arr, glyph, (60, 110, 230) if kind == "question" else (230, 60, 60), outline=0, shade_px=2)
    elif kind == "controller":
        body = S().rrect([c - .95 * s, c - .45 * s, c + .95 * s, c + .28 * s], .3 * s) \
            .ellipse([c - 1.0 * s, c - .3 * s, c - .35 * s, c + .7 * s]) \
            .ellipse([c + .35 * s, c - .3 * s, c + 1.0 * s, c + .7 * s]).m
        paint(arr, body, (75, 72, 100))
        put(arr, S().rect([c - .72 * s, c - .2 * s, c - .3 * s, c - .08 * s])
            .rect([c - .57 * s, c - .35 * s, c - .45 * s, c + .07 * s]).m, (35, 32, 48))
        for (dx, dy), col in (((.55, -.3), (230, 60, 60)), ((.75, -.12), (60, 200, 100)),
                              ((.35, -.12), (60, 120, 230)), ((.55, .06), (250, 210, 60))):
            paint(arr, S().ellipse([c + dx * s - 3, c + dy * s - 3, c + dx * s + 3, c + dy * s + 3]).m,
                  col, shade_px=1)
    elif kind == "thermometer":
        tube = S().rrect([c - .16 * s, c - .95 * s, c + .16 * s, c + .55 * s], .16 * s) \
            .ellipse([c - .32 * s, c + .4 * s, c + .32 * s, c + 1.0 * s]).m
        paint(arr, tube, WHITE, shade_px=2)
        put(arr, S().rect([c - .06 * s, c - .5 * s, c + .06 * s, c + .6 * s])
            .ellipse([c - .2 * s, c + .52 * s, c + .2 * s, c + .88 * s]).m, (230, 50, 60))
        for i in range(5):
            y = c - .8 * s + i * .25 * s
            put(arr, S().rect([c + .06 * s, y, c + .14 * s, y]).m, (150, 150, 170))
    elif kind.startswith("eye_"):
        iris_c = {"eye_blue": (60, 140, 230), "eye_brown": (110, 66, 36), "eye_honey": (205, 145, 45)}[kind]
        white = S().ellipse([c - 1.0 * s, c - .6 * s, c + 1.0 * s, c + .6 * s]).m
        paint(arr, white, WHITE, shade_px=3)
        iris = S().ellipse([c - .48 * s, c - .48 * s, c + .48 * s, c + .48 * s]).m & white
        grad(arr, (0, c - .48 * s, B, c + .5 * s), mix(iris_c, DARK, 0.25), mix(iris_c, WHITE, 0.25), mask=iris)
        put(arr, iris & ~erode(iris, 2), mix(iris_c, DARK, 0.5))
        put(arr, S().ellipse([c - .2 * s, c - .2 * s, c + .2 * s, c + .2 * s]).m, (20, 14, 26))
        put(arr, S().ellipse([c - .32 * s, c - .34 * s, c - .12 * s, c - .14 * s]).m, WHITE)
        put(arr, S().arc([c - 1.0 * s, c - .62 * s, c + 1.0 * s, c + .62 * s], 190, 350, .14 * s).m, OL)
        for i in range(5):
            x = c - .7 * s + i * .35 * s
            put(arr, S().line([(x, c - .55 * s), (x - .05 * s, c - .8 * s)], .08 * s).m, OL)
    elif kind == "photo":
        paint(arr, S().rect([c - .75 * s, c - .9 * s, c + .75 * s, c + .9 * s]).m, WHITE, shade_px=3)
        pic = S().rect([c - .6 * s, c - .75 * s, c + .6 * s, c + .45 * s]).m
        grad(arr, (0, c - .75 * s, B, c + .45 * s), (140, 200, 245), (220, 240, 255), mask=pic)
        put(arr, S().ellipse([c - .9 * s, c + .1 * s, c + .3 * s, c + .9 * s]).m & pic, (110, 190, 110))
        paint(arr, S().ellipse([c - .1 * s, c - .45 * s, c + .3 * s, c - .05 * s]).m & pic, (247, 212, 181),
              outline=0, shade_px=1)
    elif kind == "cake":
        paint(arr, S().ellipse([c - 1.0 * s, c + .35 * s, c + 1.0 * s, c + .85 * s]).m, (235, 238, 250), shade_px=2)
        for (dx, dy), col in (((-.5, .2), (240, 170, 200)), ((.05, .25), (250, 210, 120)),
                              ((.55, .2), (200, 140, 90)), ((-.22, -.2), (250, 220, 140)),
                              ((.3, -.18), (240, 170, 200))):
            x0, y0 = c + dx * s, c + dy * s
            paint(arr, S().rrect([x0 - .26 * s, y0 - .2 * s, x0 + .26 * s, y0 + .22 * s], .1 * s).m, col,
                  shade_px=2)
            put(arr, S().rect([x0 - .14 * s, y0 - .12 * s, x0 + .1 * s, y0 - .06 * s]).m, WHITE)
        paint(arr, S().ellipse([c - .1 * s, c - .62 * s, c + .1 * s, c - .42 * s]).m, (220, 40, 60), shade_px=1)
    elif kind == "money":
        for off, col in ((-.15, (90, 175, 100)), (.1, (115, 205, 125))):
            note = S().rrect([c - .95 * s, c - .5 * s + off * s, c + .85 * s, c + .45 * s + off * s], 3).m
            paint(arr, note, col, shade_px=2)
        put(arr, S().ellipse([c - .3 * s, c - .3 * s, c + .2 * s, c + .45 * s]).m, (80, 160, 90))
        put(arr, S().text((c - .05 * s, c + .08 * s), "€", .55 * s).m, (230, 255, 230))
    elif kind == "book":
        paint(arr, S().rect([c + .45 * s, c - .82 * s, c + .72 * s, c + .82 * s]).m, WHITE, shade_px=1)
        paint(arr, S().rrect([c - .72 * s, c - .9 * s, c + .5 * s, c + .9 * s], 3).m, (70, 115, 220))
        put(arr, S().rect([c - .5 * s, c - .5 * s, c + .28 * s, c - .3 * s]).m, (250, 210, 70))
    elif kind == "paper":
        sheet = S().poly([(c - .7 * s, c - .95 * s), (c + .4 * s, c - .95 * s), (c + .7 * s, c - .65 * s),
                          (c + .7 * s, c + .95 * s), (c - .7 * s, c + .95 * s)]).m
        paint(arr, sheet, WHITE, shade_px=3)
        paint(arr, S().poly([(c + .4 * s, c - .95 * s), (c + .7 * s, c - .65 * s),
                             (c + .4 * s, c - .65 * s)]).m, (210, 214, 230), shade_px=0)
        for i in range(5):
            y = c - .55 * s + i * .25 * s
            put(arr, S().rect([c - .5 * s, y, c + (.5 if i % 2 == 0 else .2) * s, y + 1]).m, (150, 155, 175))
        st = S().ellipse([c + .05 * s, c + .4 * s, c + .6 * s, c + .9 * s]).m
        put(arr, st & ~erode(st, 2), (220, 50, 70))
    elif kind == "pizza":
        paint(arr, S().poly([(c - .8 * s, c - .65 * s), (c + .8 * s, c - .65 * s), (c, c + .95 * s)]).m,
              (250, 205, 90))
        paint(arr, S().rrect([c - .92 * s, c - .95 * s, c + .92 * s, c - .55 * s], .2 * s).m, (200, 125, 60))
        for dx, dy in ((-.35, -.35), (.3, -.3), (0, .15)):
            paint(arr, S().ellipse([c + (dx - .14) * s, c + (dy - .14) * s, c + (dx + .14) * s,
                                    c + (dy + .14) * s]).m, (205, 60, 50), shade_px=1)
    elif kind == "clock":
        paint(arr, S().ellipse([c - s, c - s, c + s, c + s]).m, (230, 70, 80))
        face = S().ellipse([c - .8 * s, c - .8 * s, c + .8 * s, c + .8 * s]).m
        paint(arr, face, WHITE, outline=0, shade_px=3)
        for i in range(12):
            a = i * math.pi / 6
            put(arr, S().rect([c + .65 * s * math.cos(a), c + .65 * s * math.sin(a),
                               c + .65 * s * math.cos(a) + 1, c + .65 * s * math.sin(a) + 1]).m, OL)
        a = t * 2.4 - math.pi / 2
        put(arr, S().line([(c, c), (c, c - .5 * s)], 3).m, OL)
        put(arr, S().line([(c, c), (c + .6 * s * math.cos(a), c + .6 * s * math.sin(a))], 2).m, (220, 50, 60))
    elif kind == "star":
        pts = []
        for i in range(10):
            r = s if i % 2 == 0 else .45 * s
            a = -math.pi / 2 + i * math.pi / 5
            pts.append((c + r * math.cos(a), c + .05 * s + r * math.sin(a)))
        paint(arr, S().poly(pts).m, (252, 212, 60))
    elif kind == "zzz":
        for dx, dy, k in ((-.6, .5, .55), (0, 0, .75), (.6, -.6, 1.0)):
            paint(arr, S().text((c + dx * s, c + dy * s), "Z", k * s).m, (235, 235, 255), shade_px=2)
    elif kind == "bulb":
        for i in range(8):
            a = i * math.pi / 4
            put(arr, S().line([(c + .8 * s * math.cos(a), c - .3 * s + .8 * s * math.sin(a)),
                               (c + 1.0 * s * math.cos(a), c - .3 * s + 1.0 * s * math.sin(a))], 2).m,
                (255, 230, 110))
        paint(arr, S().ellipse([c - .62 * s, c - .95 * s, c + .62 * s, c + .3 * s])
              .poly([(c - .35 * s, c + .1 * s), (c + .35 * s, c + .1 * s), (c + .25 * s, c + .45 * s),
                     (c - .25 * s, c + .45 * s)]).m, (255, 228, 100))
        paint(arr, S().rrect([c - .3 * s, c + .42 * s, c + .3 * s, c + .78 * s], 3).m, (175, 178, 195), shade_px=2)
    elif kind == "trophy":
        for d in (-1, 1):
            hm = S().ellipse([c + d * .45 * s - .35 * s, c - .8 * s, c + d * .45 * s + .35 * s, c - .1 * s]).m
            put(arr, hm & ~erode(hm, 3), (215, 160, 40))
        paint(arr, S().poly([(c - .65 * s, c - .9 * s), (c + .65 * s, c - .9 * s), (c + .3 * s, c - .05 * s),
                             (c - .3 * s, c - .05 * s)]).m, (250, 200, 50))
        paint(arr, S().rect([c - .1 * s, c - .1 * s, c + .1 * s, c + .45 * s]).m, (230, 175, 45), shade_px=1)
        paint(arr, S().rrect([c - .5 * s, c + .45 * s, c + .5 * s, c + .85 * s], 3).m, (150, 90, 50))
    elif kind == "sweat":
        paint(arr, S().ellipse([c - .45 * s, c - .1 * s, c + .45 * s, c + .8 * s])
              .poly([(c - .4 * s, c + .15 * s), (c + .4 * s, c + .15 * s), (c, c - .9 * s)]).m, (125, 195, 250))
    elif kind == "anger":
        a = S()
        for sx in (-1, 1):
            for sy in (-1, 1):
                a.line([(c + sx * .22 * s, c + sy * .9 * s), (c + sx * .22 * s, c + sy * .22 * s),
                        (c + sx * .9 * s, c + sy * .22 * s)], .24 * s)
        paint(arr, a.m, (235, 50, 62), shade_px=2)

    img = Image.fromarray(arr, "RGBA")
    if len(_prop_cache) > 400:
        _prop_cache.clear()
    _prop_cache[key] = img
    return img


def draw_prop(img, kind, cx, cy, size=32, t=0.0):
    p = prop_image(kind, size, t)
    img.alpha_composite(p, (int(cx - p.width / 2), int(cy - p.height / 2)))


# --------------------------------------------------------------------------
# Backgrounds
# --------------------------------------------------------------------------

_bg_cache = {}


def background(bg, t=0.0):
    """RGBA background image; static ones are cached."""
    kind = bg.get("type", "room")
    animated = kind in ("burst", "night", "street", "intro")
    key = (repr(sorted(bg.items())), round(t * 12) if animated else 0)
    if key not in _bg_cache:
        if len(_bg_cache) > 200:
            _bg_cache.clear()
        arr = np.zeros((H, W, 4), np.uint8)
        _draw_bg(arr, bg, kind, t)
        _bg_cache[key] = Image.fromarray(arr, "RGBA")
    return _bg_cache[key].copy()


def _wall(arr, x0, x1, wall):
    grad(arr, (x0, 0, x1, FLOOR_Y - 10), mix(wall, WHITE, 0.14), mix(wall, DARK, 0.06), levels=5)
    dot = mix(wall, DARK, 0.1)
    for y in range(14, FLOOR_Y - 20, 26):
        for x in range(x0 + 6 + (y // 26 % 2) * 13, x1 - 2, 26):
            arr[y - 1:y + 2, x, :3] = dot
            arr[y, x - 1:x + 2, :3] = dot
    base = mix(wall, WHITE, 0.55)
    arr[FLOOR_Y - 10:FLOOR_Y, x0:x1, :3] = base
    arr[FLOOR_Y - 10, x0:x1, :3] = mix(base, DARK, 0.35)
    arr[FLOOR_Y - 3:FLOOR_Y, x0:x1, :3] = mix(base, DARK, 0.15)
    arr[:FLOOR_Y, x0:x1, 3] = 255


def _floor(arr, floor):
    pw = 30
    for i, x in enumerate(range(0, W, pw)):
        tone = mix(floor, WHITE, 0.07) if i % 2 else floor
        grad(arr, (x, FLOOR_Y, x + pw, H), tone, mix(tone, DARK, 0.18), levels=4)
        arr[FLOOR_Y:, x, :3] = mix(floor, DARK, 0.35)
        jy = FLOOR_Y + 30 + (i * 57) % 110
        arr[jy, x:x + pw, :3] = mix(floor, DARK, 0.3)
        for k in range(3):
            gy = FLOOR_Y + 12 + ((i * 37 + k * 41) % (H - FLOOR_Y - 20))
            gx = x + 6 + (k * 7 + i * 3) % (pw - 14)
            arr[gy, gx:gx + 8, :3] = mix(tone, DARK, 0.12)
    arr[FLOOR_Y:FLOOR_Y + 4, :, :3] = mix(floor, DARK, 0.3)


def _window(arr, x0, y0, x1, y1, curtain):
    S = lambda: Shape(W, H)
    frame = (240, 236, 228)
    paint(arr, S().rect([x0, y0, x1, y1]).m, frame, shade_px=2)
    gl = S().rect([x0 + 7, y0 + 7, x1 - 7, y1 - 7]).m
    grad(arr, (x0, y0 + 7, x1, y1 - 6), (110, 180, 240), (205, 236, 255), mask=gl)
    for cxx, cyy in ((x0 + 28, y0 + 30), (x1 - 26, y0 + 60)):
        put(arr, S().ellipse([cxx - 14, cyy - 5, cxx + 14, cyy + 5]).ellipse([cxx - 6, cyy - 10, cxx + 8, cyy + 2]).m & gl,
            WHITE)
    put(arr, S().rect([(x0 + x1) // 2 - 2, y0 + 7, (x0 + x1) // 2 + 2, y1 - 7])
        .rect([x0 + 7, (y0 + y1) // 2 - 2, x1 - 7, (y0 + y1) // 2 + 2]).m, frame)
    put(arr, S().line([(x0 + 14, y0 + 40), (x0 + 30, y0 + 22)], 3).m & gl, (235, 248, 255))
    paint(arr, S().rect([x0 - 8, y1, x1 + 8, y1 + 8]).m, frame, shade_px=2)
    paint(arr, S().rect([x0 - 20, y0 - 12, x1 + 20, y0 - 8]).m, (110, 75, 55), shade_px=1)
    for xx in (x0 - 22, x1 + 22):
        paint(arr, S().ellipse([xx - 5, y0 - 15, xx + 5, y0 - 5]).m, (110, 75, 55), shade_px=1)
    for side in (0, 1):
        cxa = x0 - 18 if side == 0 else x1 - 12
        cur = S().poly([(cxa, y0 - 8), (cxa + 30, y0 - 8), (cxa + 24 if side == 0 else cxa + 30, y0 + 70),
                        (cxa + 30, y1 + 20), (cxa, y1 + 20), (cxa if side == 0 else cxa + 6, y0 + 70)]).m
        paint(arr, cur, curtain)
        for k in range(1, 4):
            put(arr, cur & S().rect([cxa + k * 8, 0, cxa + k * 8 + 1, H]).m, ramp(curtain)["shadow"])
        put(arr, cur & S().rect([0, y0 + 66, W, y0 + 72]).m, mix(curtain, DARK, 0.3))


def _frame(arr, x0, y0, x1, y1):
    S = lambda: Shape(W, H)
    paint(arr, S().rect([x0, y0, x1, y1]).m, (196, 136, 84), shade_px=3)
    pic = S().rect([x0 + 6, y0 + 6, x1 - 6, y1 - 6]).m
    grad(arr, (x0, y0 + 6, x1, y1 - 6), (150, 210, 245), (230, 245, 255), mask=pic)
    put(arr, S().ellipse([x0, y1 - 20, x1 - 10, y1 + 14]).m & pic, (110, 190, 110))
    put(arr, S().ellipse([x0 + 20, y1 - 16, x1 + 14, y1 + 18]).m & pic, (80, 160, 95))
    put(arr, S().ellipse([x1 - 22, y0 + 10, x1 - 12, y0 + 20]).m & pic, (255, 220, 90))


def _draw_bg(arr, bg, kind, t):
    S = lambda: Shape(W, H)
    wall = hexc(bg.get("color", bg.get("wall", "#9fd8c8")))
    floor = hexc(bg.get("floor", "#c8925a"))
    curtain = hexc(bg.get("curtain", "#f7a943"))

    if kind == "burst":
        c2 = hexc(bg.get("color2", "#f7b4b4"))
        grad(arr, (0, 0, W, H), mix(wall, WHITE, 0.15), wall, levels=4, radial=(W / 2, H * .42, H * .6))
        cx, cy = W / 2, H * 0.42
        rays = S()
        rot = t * 0.4
        for i in range(14):
            a0 = rot + i * math.pi / 7
            a1 = a0 + math.pi / 14
            rays.poly([(cx, cy), (cx + 700 * math.cos(a0), cy + 700 * math.sin(a0)),
                       (cx + 700 * math.cos(a1), cy + 700 * math.sin(a1))])
        grad(arr, (0, 0, W, H), mix(c2, WHITE, 0.2), c2, levels=4, mask=rays.m, radial=(cx, cy, H * .6))
        vignette(arr, 0.18)
        return

    if kind == "intro":
        # signature title card: a stamp of text over a spinning burst
        c1 = hexc(bg.get("color", "#2c2f4a"))
        c2 = hexc(bg.get("color2", "#3d4170"))
        grad(arr, (0, 0, W, H), mix(c1, WHITE, 0.1), c1, levels=4, radial=(W / 2, H * .45, H * .6))
        cx, cy = W / 2, H * 0.45
        rays = S()
        for i in range(16):
            a0 = t * 0.6 + i * math.pi / 8
            a1 = a0 + math.pi / 16
            rays.poly([(cx, cy), (cx + 700 * math.cos(a0), cy + 700 * math.sin(a0)),
                       (cx + 700 * math.cos(a1), cy + 700 * math.sin(a1))])
        put(arr, rays.m, c2)
        lines = bg.get("text", "C'est que chez moi ?").upper().split("|")
        accent = hexc(bg.get("accent", "#ffd93b"))
        plate = S().rrect([18, cy - 34 * len(lines) - 14, W - 18, cy + 34 * len(lines) + 14], 14).m
        paint(arr, plate, hexc(bg.get("plate", "#e8414f")), outline=3, shade_px=6)
        for i, ln in enumerate(lines):
            y = cy + (i - (len(lines) - 1) / 2) * 62
            size = 52
            while _font(size).getlength(ln) > W - 60 and size > 20:
                size -= 2
            m = S().text((cx, y), ln, size).m
            paint(arr, m, accent if i == len(lines) - 1 else WHITE, outline=3, shade_px=3, line=OL)
        vignette(arr, 0.25)
        return

    if kind == "split":
        left = hexc(bg.get("left", "#fbe3a0"))
        right = hexc(bg.get("right", "#c9ccd8"))
        _wall(arr, 0, W // 2, left)
        _wall(arr, W // 2, W, right)
        _floor(arr, floor)
        arr[:, W // 2 - 2:W // 2 + 2, :3] = OL
        return

    if kind == "plain":
        grad(arr, (0, 0, W, H), mix(wall, WHITE, 0.12), mix(wall, DARK, 0.08), levels=5)
        dot = mix(wall, DARK, 0.07)
        for y in range(10, H, 22):
            for x in range(10 + (y // 22 % 2) * 11, W, 22):
                arr[y - 2:y + 3, x, :3] = dot
                arr[y, x - 2:x + 3, :3] = dot
        vignette(arr, 0.2)
        return

    if kind == "night":
        grad(arr, (0, 0, W, FLOOR_Y), (16, 18, 52), (78, 52, 112), levels=7)
        for i in range(70):
            sx, sy = (i * 97 + 13) % W, (i * 61 + 7) % (FLOOR_Y - 90)
            tw = (i + int(t * 4)) % 9
            if tw == 0:
                continue
            arr[sy, sx, :3] = (250, 245, 210)
            if i % 7 == 0 and tw > 4:
                arr[max(0, sy - 2):sy + 3, sx, :3] = (250, 245, 210)
                arr[sy, max(0, sx - 2):sx + 3, :3] = (250, 245, 210)
        mx, my = 205, 78
        glow = S().ellipse([mx - 42, my - 42, mx + 42, my + 42]).m
        grad(arr, (0, 0, W, H), (120, 100, 150), (78, 60, 120), levels=3, mask=glow, radial=(mx, my, 42))
        paint(arr, S().ellipse([mx - 22, my - 22, mx + 22, my + 22]).m, (250, 240, 196), outline=0)
        for dx, dy, r in ((-8, -6, 5), (7, 5, 4), (-2, 10, 3)):
            put(arr, S().ellipse([mx + dx - r, my + dy - r, mx + dx + r, my + dy + r]).m, (222, 212, 170))
        x = 0
        i = 0
        while x < W:
            bw = 24 + (i * 13) % 22
            bh = 40 + (i * 37) % 70
            put(arr, S().rect([x, FLOOR_Y - bh, x + bw, FLOOR_Y]).m, (34, 30, 66))
            for wy in range(FLOOR_Y - bh + 8, FLOOR_Y - 8, 12):
                for wx in range(x + 5, x + bw - 6, 9):
                    if (wx * 7 + wy * 3 + i) % 5 == 0:
                        arr[wy:wy + 5, wx:wx + 4, :3] = (250, 214, 110)
            x += bw + 2
            i += 1
        grad(arr, (0, FLOOR_Y, W, H), (34, 62, 58), (20, 36, 40), levels=5)
        return

    if kind == "street":
        grad(arr, (0, 0, W, FLOOR_Y), hexc(bg.get("sky", "#7cc4f0")), (210, 238, 255), levels=6)
        for cxx, cyy in ((60, 50), (200, 30)):
            put(arr, S().ellipse([cxx - 26, cyy - 8, cxx + 26, cyy + 8]).ellipse([cxx - 12, cyy - 16, cxx + 14, cyy + 4]).m,
                WHITE)
        b = hexc(bg.get("color", "#e48a6a"))
        bx0 = 92
        put(arr, S().rect([bx0, 60, W, FLOOR_Y]).m, b)
        mortar = mix(b, DARK, 0.2)
        for y in range(60, FLOOR_Y, 8):
            arr[y, bx0:, :3] = mortar
            for x in range(bx0 + (y // 8 % 2) * 8, W, 16):
                arr[y:y + 8, x, :3] = mortar
        paint(arr, S().rect([bx0 - 4, 52, W + 2, 62]).m, mix(b, DARK, 0.25), shade_px=2)
        for wy in (78, 136):
            for wx in (106, 158, 210):
                if wy == 136 and wx == 158:
                    continue
                _mini_window(arr, wx, wy, 36, 40)
        paint(arr, S().rrect([150, FLOOR_Y - 76, 192, FLOOR_Y], 4).m, (120, 72, 50))
        put(arr, S().ellipse([182, FLOOR_Y - 40, 186, FLOOR_Y - 36]).m, (250, 210, 70))
        aw = S().poly([(142, FLOOR_Y - 92), (200, FLOOR_Y - 92), (206, FLOOR_Y - 78), (136, FLOOR_Y - 78)]).m
        put(arr, aw, (230, 70, 70))
        for x in range(136, 208, 12):
            put(arr, aw & S().rect([x, 0, x + 5, H]).m, WHITE)
        paint(arr, S().rect([26, FLOOR_Y - 150, 31, FLOOR_Y]).m, (60, 62, 80), shade_px=1)
        paint(arr, S().rrect([18, FLOOR_Y - 164, 40, FLOOR_Y - 148], 4).m, (255, 226, 120), shade_px=2)
        grad(arr, (0, FLOOR_Y, W, FLOOR_Y + 62), (205, 205, 215), (180, 180, 195), levels=3)
        for x in range(0, W, 30):
            arr[FLOOR_Y:FLOOR_Y + 62, x, :3] = (150, 150, 165)
        arr[FLOOR_Y + 62:FLOOR_Y + 68, :, :3] = (120, 120, 135)
        grad(arr, (0, FLOOR_Y + 68, W, H), (105, 108, 125), (80, 82, 100), levels=4)
        off = int(t * 60) % 48
        for x in range(-48, W, 48):
            arr[FLOOR_Y + 100:FLOOR_Y + 104, max(0, x + off):max(0, x + off + 26), :3] = WHITE
        return

    if kind == "classroom":
        _wall(arr, 0, W, wall)
        paint(arr, S().rect([20, 66, 250, 200]).m, (160, 110, 70), shade_px=3)
        board = S().rect([28, 74, 242, 192]).m
        grad(arr, (28, 74, 243, 193), (60, 100, 80), (44, 80, 64), mask=board, levels=4)
        chalk = S()
        for x, y, w in ((44, 92, 90), (44, 108, 130), (44, 124, 70), (150, 150, 70)):
            chalk.rect([x, y, x + w, y + 1])
        chalk.text((90, 160), "1+1=2", 20)
        put(arr, chalk.m & board, (230, 240, 230))
        paint(arr, S().rect([40, 200, 230, 205]).m, (160, 110, 70), shade_px=1)
        _floor(arr, floor)
        return

    # room
    _wall(arr, 0, W, wall)
    _window(arr, 168, 66, 246, 160, curtain)
    _frame(arr, 26, 86, 88, 132)
    _floor(arr, floor)


def _mini_window(arr, x, y, w, h):
    S = lambda: Shape(W, H)
    paint(arr, S().rect([x, y, x + w, y + h]).m, (245, 240, 232), shade_px=2)
    gl = S().rect([x + 4, y + 4, x + w - 4, y + h - 4]).m
    grad(arr, (x, y + 4, x + w, y + h - 3), (255, 222, 140), (250, 190, 100), mask=gl, levels=3)
    put(arr, S().rect([x + w // 2 - 1, y + 4, x + w // 2 + 1, y + h - 4]).m, (245, 240, 232))


def ground_shadow(img, x, feet, w=44):
    """Darken an ellipse of floor under a character."""
    arr = np.array(img)
    m = Shape(W, H).ellipse([x - w / 2, feet - 5, x + w / 2, feet + 5]).m
    arr[m, :3] = (arr[m, :3] * 0.72).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")
