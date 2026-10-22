"""Smooth "round people" cartoon style (flat vector look, thick outlines).

Same interface as `sprites` so render.py can switch styles per story:
W, H, U, FLOOR_Y, SCX, SFEET, background(), draw_character(), prop_image(),
draw_prop(), ground_shadow(), hexc().

Everything is drawn supersampled (SS) with PIL and downscaled, which gives
clean antialiased edges. Frames are 1080x1920 and upscaled to 4K by ffmpeg.
"""
import json
import math

from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import sprites
from .sprites import hexc, mix

U = 8
W, H = 135 * U, 240 * U
FLOOR_Y = 172 * U
SS = 2                       # supersampling factor
PXU = 3.6                    # character design unit -> canvas px
OLC = (43, 35, 64)           # outline colour
WHITE = (255, 255, 255)
DARK = (40, 24, 70)
OUTLINE_U = 1.7              # outline width in design units

_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(size):
    try:
        return ImageFont.truetype(_FONT, int(size))
    except OSError:
        return sprites._font(size)


def shade_of(c):
    return mix(c, (60, 40, 110), 0.28)


# --------------------------------------------------------------------------
# Painter: draws outlined, cel-shaded parts in design units
# --------------------------------------------------------------------------

class Painter:
    def __init__(self, w, h, scale, k=1.0, cx=0, F=0):
        self.s = scale
        self.k, self.cx, self.F = k, cx, F
        self.img = Image.new("RGBA", (int(w * scale), int(h * scale)), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.ow = OUTLINE_U * scale

    # design units -> px (characters shrink around their feet when k < 1)
    def X(self, x):
        return (self.cx + (x - self.cx) * self.k) * self.s

    def Y(self, y):
        return (self.F + (y - self.F) * self.k) * self.s

    def L(self, v):
        return v * self.k * self.s

    def box(self, b, g=0):
        x0, y0, x1, y1 = self.X(b[0]) - g, self.Y(b[1]) - g, self.X(b[2]) + g, self.Y(b[3]) + g
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]

    def _draw(self, d, op, a, fill, g=0.0):
        if op == "ellipse":
            d.ellipse(self.box(a[0], g), fill=fill)
        elif op == "rrect":
            b = self.box(a[0], g)
            r = max(0, min(self.L(a[1]) + g, (b[2] - b[0]) / 2, (b[3] - b[1]) / 2))
            d.rounded_rectangle(b, radius=r, fill=fill)
        elif op == "chord":
            d.chord(self.box(a[0], g), a[1], a[2], fill=fill)
        elif op == "poly":
            pts = [(self.X(x), self.Y(y)) for x, y in a[0]]
            d.polygon(pts, fill=fill)
            if g:
                d.line(pts + [pts[0]], fill=fill, width=max(1, int(2 * g)), joint="curve")
                for x, y in pts:
                    d.ellipse([x - g, y - g, x + g, y + g], fill=fill)
        elif op == "cap":  # capsule: thick line with round ends
            pts = [(self.X(x), self.Y(y)) for x, y in a[0]]
            w = self.L(a[1]) + 2 * g
            d.line(pts, fill=fill, width=max(1, int(w)), joint="curve")
            for x, y in pts:
                d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=fill)

    def part(self, shapes, color, outline=True, shade=True, gloss=False, ol=None):
        color = hexc(color)
        if outline:
            for op, a in shapes:
                self._draw(self.d, op, a, ol or OLC, self.ow * (0.7 + 0.3 * self.k))
        for op, a in shapes:
            self._draw(self.d, op, a, color)
        if not (shade or gloss):
            return
        m = Image.new("L", self.img.size, 0)
        md = ImageDraw.Draw(m)
        for op, a in shapes:
            self._draw(md, op, a, 255)
        bb = m.getbbox()
        if not bb:
            return
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        if shade:
            dd = max(2, int(min(bw, bh) * 0.16))
            moved = Image.new("L", m.size, 0)
            moved.paste(m, (-dd, -dd))
            self.img.paste(shade_of(color) + (255,), mask=ImageChops.subtract(m, moved))
        if gloss:
            g = Image.new("L", m.size, 0)
            ImageDraw.Draw(g).ellipse([bb[0] + bw * .16, bb[1] + bh * .1, bb[0] + bw * .36, bb[1] + bh * .24],
                                      fill=150)
            self.img.paste((255, 255, 255, 255), mask=ImageChops.multiply(g, m))

    def fill(self, op, a, color):
        self._draw(self.d, op, a, hexc(color) if not isinstance(color, tuple) or len(color) == 3 else color)

    def arc(self, b, a0, a1, width, color=OLC):
        self.d.arc(self.box(b), a0, a1, fill=color, width=max(1, int(self.L(width))))

    def line(self, pts, width, color=OLC):
        self._draw(self.d, "cap", (pts, width), color)


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------

SKINS = {"light": "#f9d7bd", "medium": "#e2a77f", "tan": "#c1845b", "dark": "#7f4f36"}
DEFAULT_CHAR = dict(sprites.DEFAULT_CHAR)

SW_U, SH_U = 200, 226        # sprite box in design units
_CX, _F = 100, 218
SCX, SFEET = int(_CX * PXU), int(_F * PXU)   # anchor in canvas px

_char_cache = {}


def draw_character(spec, expr="neutral", pose="stand", blink=False, flip=False, hold=None, t=0.0):
    """Return (RGBA sprite at canvas scale, head_top_y in sprite px)."""
    s = dict(DEFAULT_CHAR)
    s.update(spec or {})
    wave = int(t * 4) % 2 if pose == "wave" else 0
    key = (json.dumps(s, sort_keys=True), expr, pose, blink, flip, hold, wave)
    if key in _char_cache:
        return _char_cache[key]

    k = 0.8 if s["size"] < 1 else 1.0
    p = Painter(SW_U, SH_U, PXU * SS, k=k, cx=_CX, F=_F)
    acc = s["acc"]
    skin = hexc(SKINS.get(s["skin"], s["skin"]))
    hair = hexc(s["hair_color"])
    shirt = hexc(s["shirt"])
    pants = hexc(s["pants"])
    shoes = hexc(s["shoes"])
    cx, F = _CX, _F
    hcy = F - 120                   # head centre
    hw, hh = 86, 80
    hx0, hx1, hy0, hy1 = cx - hw / 2, cx + hw / 2, hcy - hh / 2, hcy + hh / 2

    # ---- back layers
    _hair_back(p, s["hair"], hair, cx, hcy, hx0, hx1, hy0, hy1)
    if "hoodie" in acc:
        p.part([("ellipse", ([cx - 30, F - 92, cx + 30, F - 66],))], mix(shirt, DARK, 0.15), shade=False)

    # ---- legs, shoes
    for dx in (-10, 10):
        p.part([("cap", ([(cx + dx, F - 30), (cx + dx, F - 10)], 14))], pants, shade=False)
    for x0 in (cx - 24, cx + 2):
        p.part([("ellipse", ([x0, F - 13, x0 + 22, F + 1],))], shoes)
    # ---- body
    p.part([("rrect", ([cx - 30, F - 48, cx + 30, F - 20], 14))], pants)
    if "dress" in acc:
        p.part([("poly", ([(cx - 24, F - 60), (cx + 24, F - 60), (cx + 38, F - 20), (cx - 38, F - 20)],))],
               shirt)
    p.part([("rrect", ([cx - 32, F - 86, cx + 32, F - 38], 24))], shirt)
    sleeve = shirt
    if "labcoat" in acc:  # long white coat with a V showing the shirt
        sleeve = (246, 248, 252)
        p.part([("rrect", ([cx - 34, F - 88, cx + 34, F - 24], 18))], sleeve)
        p.part([("poly", ([(cx - 11, F - 88), (cx + 11, F - 88), (cx, F - 62)],))], shirt, shade=False)
        p.part([("rrect", ([cx + 10, F - 62, cx + 24, F - 50], 3))], sleeve, shade=False)
        p.line([(cx + 14, F - 66), (cx + 14, F - 56)], 2.2, (60, 110, 230))
    if "hoodie" in acc:
        p.line([(cx - 6, F - 82), (cx - 6, F - 68)], 2.2, WHITE)
        p.line([(cx + 6, F - 82), (cx + 6, F - 68)], 2.2, WHITE)
        p.part([("rrect", ([cx - 18, F - 60, cx + 18, F - 46], 6))], mix(shirt, DARK, 0.12), shade=False)
    else:
        p.fill("chord", ([cx - 12, F - 94, cx + 12, F - 76], 0, 180), mix(skin, (160, 90, 80), 0.25))

    # ---- arms
    hands = {}
    for side in (-1, 1):
        sx, sy = cx + side * 26, F - 76
        up = pose == "arms_up" or (pose == "wave" and side == 1)
        if up:
            hx, hy = cx + side * (44 + (6 if wave else 0)), F - 112 - (4 if wave else 0)
        else:
            hx, hy = cx + side * 40, F - 46
        p.part([("cap", ([(sx, sy), (hx, hy)], 15))], sleeve, shade=False)
        p.part([("ellipse", ([hx - 9, hy - 9, hx + 9, hy + 9],))], skin, shade=False)
        hands[side] = (hx, hy)

    # ---- head
    for side in (-1, 1):
        ex = cx + side * hw / 2
        p.part([("ellipse", ([ex - 9, hcy - 2, ex + 9, hcy + 16],))], skin, shade=False)
        if "earrings" in acc:
            p.part([("ellipse", ([ex - 3.5, hcy + 15, ex + 3.5, hcy + 22],))], (250, 200, 60), shade=False)
    p.part([("ellipse", ([hx0, hy0, hx1, hy1],))], skin, gloss=s["hair"] == "bald")
    if "beard" in acc:
        p.part([("chord", ([hx0, hy0, hx1, hy1], 15, 165))], hair, outline=False)
    _face(p, expr, blink, skin, hexc(s["eyes"]), cx, hcy)
    _hair_front(p, s["hair"], hair, cx, hcy, hx0, hx1, hy0, hy1)
    _accessories(p, acc, hair, cx, hcy, hx0, hx1, hy0, hy1)

    img = p.img.resize((p.img.width // SS, p.img.height // SS), Image.LANCZOS)
    if hold:
        hx, hy = hands[1]
        px, py = (cx + (hx - cx) * k) * PXU, (F + (hy - F) * k) * PXU
        pr = prop_image(hold, 34 * PXU * k)
        img.alpha_composite(pr, (int(px + 10 - pr.width / 2), int(py - 14 - pr.height / 2)))
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    tall = s["hair"] in ("bun", "spiky", "afro", "mohawk") or "crown" in acc or "beanie" in acc
    top = int((F + ((hy0 - (16 if tall else 2)) - F) * k) * PXU)
    if len(_char_cache) > 300:
        _char_cache.clear()
    _char_cache[key] = (img, top)
    return img, top


def _hair_back(p, style, c, cx, hcy, hx0, hx1, hy0, hy1):
    if style == "long":
        p.part([("rrect", ([hx0 - 6, hcy - 26, hx1 + 6, hcy + 66], 34))], c)
    elif style == "afro":
        p.part([("ellipse", ([hx0 - 16, hy0 - 22, hx1 + 16, hcy + 30],))], c)
    elif style == "ponytail":
        p.part([("ellipse", ([hx0 - 30, hcy - 30, hx0 + 6, hcy + 26],))], c)
    elif style == "bun":
        p.part([("ellipse", ([cx - 17, hy0 - 26, cx + 17, hy0 + 6],))], c, gloss=True)


def _hair_front(p, style, c, cx, hcy, hx0, hx1, hy0, hy1):
    if style == "bald":
        return
    if style == "mohawk":
        p.part([("rrect", ([cx - 9, hy0 - 18, cx + 9, hy0 + 22], 9))], c)
        return
    shapes = [("chord", ([hx0 - 3, hy0 - 4, hx1 + 3, hcy + 14], 180, 360))]
    fy = hcy - 18                 # fringe line
    n = 6 if style != "bun" else 5
    for i in range(n):
        x = hx0 + 8 + i * (hx1 - hx0 - 16) / (n - 1)
        r = 9 if i % 2 == 0 else 8
        shapes.append(("ellipse", ([x - r, fy - r - 4, x + r, fy + r - 4],)))
    shapes.append(("rrect", ([hx0 - 2, hcy - 26, hx0 + 7, hcy + 2], 4)))
    shapes.append(("rrect", ([hx1 - 7, hcy - 26, hx1 + 2, hcy + 2], 4)))
    if style == "spiky":
        for i in range(5):
            x = hx0 + 6 + i * (hx1 - hx0 - 12) / 4
            shapes.append(("poly", ([(x - 11, hy0 + 10), (x + 11, hy0 + 10), (x + 4, hy0 - 14 - (i % 2) * 6)],)))
    if style in ("curly", "afro"):
        for i in range(9):
            a = math.pi * (1.02 + i * 0.96 / 8)
            x = cx + (hx1 - hx0) / 2 * math.cos(a)
            y = hcy + 2 + (hy1 - hy0) / 2 * math.sin(a)
            shapes.append(("ellipse", ([x - 10, y - 10, x + 10, y + 10],)))
    if style == "long":
        shapes.append(("rrect", ([hx0 - 7, hcy - 24, hx0 + 6, hcy + 34], 6)))
        shapes.append(("rrect", ([hx1 - 6, hcy - 24, hx1 + 7, hcy + 34], 6)))
    p.part(shapes, c, gloss=True)


def _face(p, expr, blink, skin, eye_c, cx, hcy):
    ey = hcy + 4
    exs = (cx - 16, cx + 16)
    my = hcy + 24
    mx = cx + 1
    pink = (255, 125, 145)
    k = 0.6 if expr in ("happy", "laugh", "love") else 0.35
    for ex in exs:
        p.fill("ellipse", ([ex - 10, ey + 11, ex + 2, ey + 17],), mix(skin, pink, k))

    for i, ex in enumerate(exs):
        if blink or expr in ("happy", "laugh"):
            if expr in ("happy", "laugh") and not blink:
                p.arc([ex - 8, ey - 4, ex + 8, ey + 10], 200, 340, 3)
            else:
                p.arc([ex - 8, ey - 8, ex + 8, ey + 4], 20, 160, 3)
            continue
        if expr == "love":
            p.part([("ellipse", ([ex - 8, ey - 7, ex, ey + 1],)), ("ellipse", ([ex, ey - 7, ex + 8, ey + 1],)),
                    ("poly", ([(ex - 8, ey - 2), (ex + 8, ey - 2), (ex, ey + 9)],))], (235, 60, 95))
            continue
        big = expr == "shocked"
        w2, h2 = (10, 12) if big else (8, 10)
        p.part([("ellipse", ([ex - w2, ey - h2, ex + w2, ey + h2],))], WHITE, shade=False)
        if big:
            p.fill("ellipse", ([ex - 3, ey - 3, ex + 3, ey + 3],), OLC)
        else:
            p.fill("ellipse", ([ex - 5.5, ey - 4, ex + 5.5, ey + 7],), eye_c)
            p.fill("ellipse", ([ex - 3, ey - 1, ex + 3, ey + 5],), OLC)
            p.fill("ellipse", ([ex - 4, ey - 4, ex - .5, ey - .5],), WHITE)
        if expr in ("angry", "smirk"):
            p.fill("chord", ([ex - w2 - 1, ey - h2 - 1, ex + w2 + 1, ey + h2 + 1], 180, 360), skin)
            p.line([(ex - w2, ey), (ex + w2, ey)], 2.2)
        if expr == "sad":
            p.part([("ellipse", ([ex - 3, ey + 12, ex + 3, ey + 20],))], (120, 190, 250), shade=False)

    by = ey - 15
    for i, ex in enumerate(exs):
        inner = 1 if i == 0 else -1
        if expr == "angry":
            p.line([(ex - 7 * inner, by - 3), (ex + 7 * inner, by + 3)], 3.4)
        elif expr in ("sad", "worried"):
            p.line([(ex - 7 * inner, by + 2), (ex + 7 * inner, by - 3)], 3.4)
        elif expr == "shocked":
            p.arc([ex - 8, by - 8, ex + 8, by + 2], 200, 340, 3.4)
        elif expr == "smirk" and i == 1:
            p.line([(ex - 7, by - 4), (ex + 7, by - 1)], 3.4)
        else:
            p.line([(ex - 7, by), (ex + 7, by)], 3.4)

    red, tongue = (160, 35, 55), (240, 110, 130)
    if expr in ("happy", "love"):
        p.arc([mx - 10, my - 10, mx + 10, my + 4], 20, 160, 3)
    elif expr == "laugh":
        p.part([("chord", ([mx - 12, my - 10, mx + 12, my + 12], 0, 180))], red, shade=False)
        p.fill("ellipse", ([mx - 6, my + 3, mx + 6, my + 11],), tongue)
        p.fill("rrect", ([mx - 9, my + 1, mx + 9, my + 4], 1), WHITE)
    elif expr == "sad":
        p.arc([mx - 8, my - 1, mx + 8, my + 11], 200, 340, 3)
    elif expr == "shocked":
        p.part([("ellipse", ([mx - 6, my - 5, mx + 6, my + 10],))], red, shade=False)
        p.fill("ellipse", ([mx - 3.5, my + 3, mx + 3.5, my + 9],), tongue)
    elif expr == "angry":
        p.part([("rrect", ([mx - 11, my - 3, mx + 11, my + 7], 3))], WHITE, shade=False)
        p.line([(mx - 10, my + 2), (mx + 10, my + 2)], 1)
    elif expr == "worried":
        p.line([(mx - 8, my + 1), (mx - 3, my - 1), (mx + 2, my + 1), (mx + 7, my - 1)], 2.4)
    elif expr == "smirk":
        p.line([(mx - 7, my + 1), (mx + 5, my + 1), (mx + 9, my - 3)], 2.6)
    else:
        p.line([(mx - 6, my), (mx + 6, my)], 2.6)


def _accessories(p, acc, hair, cx, hcy, hx0, hx1, hy0, hy1):
    ey = hcy + 4
    exs = (cx - 16, cx + 16)
    my = hcy + 24
    gold = (250, 200, 60)
    if "glasses" in acc:
        for ex in exs:
            p.d.ellipse(p.box([ex - 13, ey - 12, ex + 13, ey + 12]), outline=OLC, width=int(p.L(2.6)))
        p.line([(exs[0] + 12, ey - 2), (exs[1] - 12, ey - 2)], 2.4)
        for ex in exs:
            p.line([(ex + 5, ey - 7), (ex + 9, ey - 3)], 1.6, WHITE)
    if "mustache" in acc:
        p.part([("ellipse", ([cx - 13, my - 11, cx + 2, my - 3],)), ("ellipse", ([cx, my - 11, cx + 15, my - 3],))],
               hair, shade=False)
    if "crown" in acc:
        base = hy0 + 2
        pts = [(cx - 24, base), (cx - 24, base - 20), (cx - 12, base - 9), (cx, base - 26), (cx + 12, base - 9),
               (cx + 24, base - 20), (cx + 24, base)]
        p.part([("poly", (pts,))], gold, gloss=True)
        for x, col in ((cx - 13, (60, 120, 230)), (cx, (230, 50, 70)), (cx + 13, (60, 190, 110))):
            p.part([("ellipse", ([x - 3.5, base - 8, x + 3.5, base - 1],))], col, shade=False)
    if "cap" in acc:
        red = (220, 60, 60)
        p.part([("chord", ([hx0 - 4, hy0 - 6, hx1 + 4, hcy + 8], 180, 360))], red, gloss=True)
        p.part([("ellipse", ([hx1 - 22, hcy - 16, hx1 + 26, hcy - 6],))], mix(red, DARK, 0.2), shade=False)
    if "beanie" in acc:
        col = (150, 90, 210)
        p.part([("chord", ([hx0 - 4, hy0 - 12, hx1 + 4, hcy + 6], 180, 360))], col)
        p.part([("rrect", ([hx0 - 5, hcy - 22, hx1 + 5, hcy - 10], 5))], mix(col, DARK, 0.15), shade=False)
        p.part([("ellipse", ([cx - 9, hy0 - 22, cx + 9, hy0 - 4],))], WHITE, shade=False)
    if "headphones" in acc:
        p.d.arc(p.box([hx0 - 8, hy0 - 10, hx1 + 8, hcy + 30]), 185, 355, fill=OLC, width=int(p.L(6)))
        for x in (hx0 - 4, hx1 + 4):
            p.part([("rrect", ([x - 8, hcy - 12, x + 8, hcy + 16], 6))], (70, 70, 90), shade=False)
    if "police" in acc:
        col = (40, 60, 90)
        p.part([("rrect", ([hx0 - 4, hy0 - 14, hx1 + 4, hy0 + 14], 10))], col)
        p.part([("ellipse", ([hx0 + 6, hy0 + 8, hx1 + 18, hy0 + 18],))], (25, 25, 35), shade=False)
        p.part([("ellipse", ([cx - 6, hy0 - 6, cx + 6, hy0 + 6],))], gold, shade=False)


# --------------------------------------------------------------------------
# Props: the pixel prop shapes, rasterised big with thick outlines
# --------------------------------------------------------------------------

PROPS = sprites.PROPS
_prop_cache = {}


CUSTOM_PROPS = ("brain", "brain_alarm", "label", "report", "door")


def _text(p, xy, txt, size, fill, stroke=0.0):
    f = _font(size * p.s)
    x0, y0, x1, y1 = p.d.textbbox((0, 0), txt, font=f, stroke_width=int(stroke * p.s))
    p.d.text((xy[0] * p.s - (x0 + x1) / 2, xy[1] * p.s - (y0 + y1) / 2), txt, font=f, fill=fill,
             stroke_width=int(stroke * p.s), stroke_fill=OLC)


def _custom_prop(kind, size, t):
    """Vector props drawn natively in the cartoon style. kind may carry "|text|colour"."""
    base, *extra = kind.split("|")
    text = extra[0] if extra else ""
    col = hexc(extra[1]) if len(extra) > 1 else (94, 224, 122)
    s = size / 2
    if base == "label":
        tw = _font(s * .9).getlength(text)
        Wd, Hd = tw + s * 1.4, s * 2
        p = Painter(Wd, Hd, SS)
        p.ow = 0.06 * s * SS
        p.part([("rrect", ([s * .2, s * .3, Wd - s * .2, Hd - s * .3], s * .7))], col)
        _text(p, (Wd / 2, Hd / 2), text, s * .9, WHITE, stroke=s * .09)
        return p.img
    B = size * 1.9
    c = B / 2
    p = Painter(B, B * (1.5 if base == "door" else 1), SS)
    p.ow = max(3, 0.07 * s) * SS
    if base in ("brain", "brain_alarm"):
        pink = (247, 150, 172)
        body = [("ellipse", ([c - s, c - .7 * s, c + s, c + .8 * s],))]
        for dx, dy, r in ((-.55, -.55, .42), (0, -.72, .42), (.55, -.55, .42), (-.85, -.05, .35), (.85, -.05, .35)):
            body.append(("ellipse", ([c + (dx - r) * s, c + (dy - r) * s, c + (dx + r) * s, c + (dy + r) * s],)))
        p.part(body, pink, gloss=True)
        fold = mix(pink, DARK, 0.25)
        p.line([(c, c - 1.05 * s), (c, c + .7 * s)], .05 * s, fold)
        for dx in (-1, 1):
            p.arc([c + dx * .35 * s - .25 * s, c - .75 * s, c + dx * .35 * s + .25 * s, c - .25 * s], 200, 340,
                  .05 * s, fold)
        ey = c + .05 * s
        for dx in (-.35, .35):
            p.part([("ellipse", ([c + (dx - .2) * s, ey - .22 * s, c + (dx + .2) * s, ey + .22 * s],))], WHITE,
                   shade=False)
            p.fill("ellipse", ([c + (dx - .08) * s, ey - .08 * s, c + (dx + .08) * s, ey + .12 * s],), OLC)
        if base == "brain_alarm":
            p.part([("rrect", ([c - .32 * s, c + .38 * s, c + .32 * s, c + .58 * s], .06 * s))], WHITE, shade=False)
            for dx in (-.16, 0, .16):
                p.line([(c + dx * s, c + .4 * s), (c + dx * s, c + .56 * s)], .03 * s)
            p.part([("rrect", ([c - .35 * s, c - 1.2 * s, c + .35 * s, c - 1.08 * s], .04 * s))], (60, 60, 75),
                   shade=False)
            on = int(t * 6) % 2 == 0
            p.part([("chord", ([c - .28 * s, c - 1.5 * s, c + .28 * s, c - .95 * s], 180, 360))],
                   (240, 60, 60) if on else (190, 40, 50), gloss=True)
            for dx in (-1, 1):
                x = c + dx * 1.05 * s
                p.part([("ellipse", ([x - .14 * s, c - .3 * s, x + .14 * s, c - .02 * s],)),
                        ("poly", ([(x - .13 * s, c - .2 * s), (x + .13 * s, c - .2 * s), (x, c - .55 * s)],))],
                       (140, 190, 245), shade=False)
        else:
            p.arc([c - .25 * s, c + .2 * s, c + .25 * s, c + .55 * s], 20, 160, .06 * s)
    elif base == "report":
        p.part([("rrect", ([c - .75 * s, c - s, c + .75 * s, c + s], .08 * s))], WHITE)
        p.part([("rrect", ([c - .75 * s, c - s, c + .75 * s, c - .62 * s], .08 * s))], (70, 120, 220), shade=False)
        _text(p, (c, c - .81 * s), "BULLETIN", .2 * s, WHITE)
        for i in range(3):
            y = c - .4 * s + i * .18 * s
            p.line([(c - .55 * s, y), (c + .55 * s, y)], .04 * s, (180, 185, 200))
        _text(p, (c, c + .5 * s), text or "12/20", .48 * s, hexc(extra[1]) if len(extra) > 1 else (225, 50, 60),
              stroke=.04 * s)
    elif base == "door":
        h0, h1 = c - .2 * s, c + 2.6 * s
        p.part([("rrect", ([c - .85 * s, h0 - .15 * s, c + .85 * s, h1], .05 * s))], (150, 95, 60), shade=False)
        p.part([("rrect", ([c - .72 * s, h0, c + .72 * s, h1], .04 * s))], (248, 244, 236))
        for y0, y1 in ((h0 + .15 * s, h0 + 1.2 * s), (h0 + 1.4 * s, h1 - .15 * s)):
            p.d.rounded_rectangle(p.box([c - .55 * s, y0, c + .55 * s, y1]), radius=.05 * s * p.s, outline=OLC,
                                  width=int(.04 * s * p.s))
        p.part([("ellipse", ([c + .45 * s, h0 + 1.25 * s, c + .62 * s, h0 + 1.42 * s],))], (240, 190, 60),
               shade=False)
        if text:
            p.part([("rrect", ([c - .4 * s, h0 + .45 * s, c + .4 * s, h0 + .8 * s], .06 * s))], (60, 110, 230),
                   shade=False)
            _text(p, (c, h0 + .63 * s), text, .24 * s, WHITE)
    return p.img


def prop_image(kind, size, t=0.0):
    key = (kind, int(size), int(t * 8) if kind.startswith(("clock", "brain_alarm")) else 0)
    if key in _prop_cache:
        return _prop_cache[key]
    if kind.split("|")[0] in CUSTOM_PROPS:
        img = _custom_prop(kind, size, t)
        img = img.resize((max(1, img.width // SS), max(1, img.height // SS)), Image.LANCZOS)
        _prop_cache[key] = img
        return img
    big = int(size * SS)
    old = sprites.OUTLINE_PX, sprites.DITHER
    sprites.OUTLINE_PX, sprites.DITHER = max(2, round(big / 26)), False
    try:
        img = sprites.prop_image(kind, big, t)
    finally:
        sprites.OUTLINE_PX, sprites.DITHER = old
    img = img.resize((img.width // SS, img.height // SS), Image.LANCZOS)
    if len(_prop_cache) > 300:
        _prop_cache.clear()
    _prop_cache[key] = img
    return img


def draw_prop(img, kind, cx, cy, size=128, t=0.0):
    pimg = prop_image(kind, size, t)
    img.alpha_composite(pimg, (int(cx - pimg.width / 2), int(cy - pimg.height / 2)))


def ground_shadow(img, x, feet, w=200):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([x - w / 2, feet - 16, x + w / 2, feet + 16], fill=(30, 20, 50, 70))
    img.alpha_composite(sh)
    return img


# --------------------------------------------------------------------------
# Backgrounds (canvas px, drawn at SS and downscaled)
# --------------------------------------------------------------------------

class BG:
    def __init__(self):
        self.img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 255))
        self.d = ImageDraw.Draw(self.img)

    def _b(self, b):
        return [v * SS for v in b]

    def rect(self, b, fill, ol=None, w=6):
        self.d.rectangle(self._b(b), fill=fill, outline=ol, width=w * SS if ol else 0)

    def rrect(self, b, r, fill, ol=OLC, w=6):
        self.d.rounded_rectangle(self._b(b), radius=r * SS, fill=fill, outline=ol, width=w * SS if ol else 0)

    def ellipse(self, b, fill, ol=OLC, w=6):
        self.d.ellipse(self._b(b), fill=fill, outline=ol, width=w * SS if ol else 0)

    def poly(self, pts, fill, ol=OLC, w=6):
        pts = [(x * SS, y * SS) for x, y in pts]
        self.d.polygon(pts, fill=fill)
        if ol:
            self.d.line(pts + [pts[0]], fill=ol, width=w * SS, joint="curve")

    def line(self, pts, fill, w=6):
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=fill, width=w * SS, joint="curve")

    def vgrad(self, b, c1, c2):
        x0, y0, x1, y1 = [int(v * SS) for v in b]
        for y in range(y0, y1):
            t = (y - y0) / max(1, y1 - y0 - 1)
            self.d.line([(x0, y), (x1, y)], fill=mix(c1, c2, t))

    def text(self, xy, s, size, fill, stroke=10):
        f = _font(size * SS)
        x0, y0, x1, y1 = self.d.textbbox((0, 0), s, font=f, stroke_width=stroke * SS)
        self.d.text((xy[0] * SS - (x0 + x1) / 2, xy[1] * SS - (y0 + y1) / 2), s, font=f, fill=fill,
                    stroke_width=stroke * SS, stroke_fill=OLC)

    def done(self):
        return self.img.resize((W, H), Image.LANCZOS)


_bg_cache = {}


def background(bg, t=0.0):
    kind = bg.get("type", "room")
    animated = kind in ("burst", "intro")
    key = (repr(sorted(bg.items())), round(t * 12) if animated else 0)
    if key not in _bg_cache:
        if len(_bg_cache) > 60:
            _bg_cache.clear()
        g = BG()
        _draw_bg(g, bg, kind, t)
        _bg_cache[key] = g.done()
    return _bg_cache[key].copy()


def _wall(g, x0, x1, wall):
    g.rect([x0, 0, x1, FLOOR_Y], wall)
    light = mix(wall, WHITE, 0.12)
    for x in range(x0 + 20, x1, 90):
        g.rect([x, 0, min(x + 40, x1), FLOOR_Y], light)
    base = mix(wall, WHITE, 0.6)
    g.rect([x0, FLOOR_Y - 40, x1, FLOOR_Y], base)
    g.line([(x0, FLOOR_Y - 40), (x1, FLOOR_Y - 40)], OLC, 5)


def _floor(g, floor, tiles=False):
    g.rect([0, FLOOR_Y, W, H], floor)
    if tiles:
        alt = mix(floor, WHITE, 0.35)
        for i, y in enumerate(range(FLOOR_Y, H, 110)):
            for j, x in enumerate(range(-55 * (i % 2), W, 110)):
                if (i + j) % 2:
                    g.rect([x, y, x + 110, y + 110], alt)
    else:
        line = mix(floor, DARK, 0.28)
        for i, x in enumerate(range(0, W, 120)):
            g.line([(x, FLOOR_Y), (x, H)], line, 4)
            jy = FLOOR_Y + 120 + (i * 170) % 380
            g.line([(x, jy), (x + 120, jy)], line, 4)
        for i in range(8):
            gx, gy = (i * 233) % W, FLOOR_Y + 60 + (i * 157) % 480
            g.line([(gx, gy), (gx + 46, gy)], mix(floor, DARK, 0.12), 4)
    g.line([(0, FLOOR_Y), (W, FLOOR_Y)], OLC, 6)


def _window(g, x0, y0, x1, y1, curtain):
    g.rrect([x0, y0, x1, y1], 12, (250, 248, 240))
    g.vgrad([x0 + 22, y0 + 22, x1 - 22, y1 - 22], (140, 200, 245), (205, 236, 255))
    g.rrect([x0 + 22, y0 + 22, x1 - 22, y1 - 22], 6, None)
    g.ellipse([x0 + 50, y0 + 70, x0 + 160, y0 + 110], WHITE, None)
    g.ellipse([x0 + 80, y0 + 50, x0 + 140, y0 + 100], WHITE, None)
    cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
    g.rect([cxm - 9, y0 + 22, cxm + 9, y1 - 22], (250, 248, 240), OLC, 4)
    g.rect([x0 + 22, cym - 9, x1 - 22, cym + 9], (250, 248, 240), OLC, 4)
    g.rrect([x0 - 30, y1 - 6, x1 + 30, y1 + 22], 8, (250, 248, 240))
    g.rrect([x0 - 70, y0 - 44, x1 + 70, y0 - 28], 8, (130, 85, 60))
    for side in (0, 1):
        cxa = x0 - 60 if side == 0 else x1 - 30
        pts = [(cxa, y0 - 30), (cxa + 90, y0 - 30), (cxa + (70 if side == 0 else 90), y1 * 0.5 + y0 * 0.5),
               (cxa + 90, y1 + 60), (cxa, y1 + 60), (cxa + (0 if side == 0 else 20), y1 * 0.5 + y0 * 0.5)]
        g.poly(pts, curtain)
        for kx in (28, 58):
            g.line([(cxa + kx, y0 - 20), (cxa + kx, y1 + 50)], mix(curtain, DARK, 0.18), 5)


def _frame(g, x0, y0, x1, y1):
    g.rrect([x0, y0, x1, y1], 10, (205, 145, 90))
    g.rect([x0 + 18, y0 + 18, x1 - 18, y1 - 18], (250, 246, 232), OLC, 4)
    # a tiny family portrait
    for i, (fx, col) in enumerate(((0.33, (230, 170, 130)), (0.67, (200, 140, 100)))):
        x = x0 + (x1 - x0) * fx
        y = y0 + (y1 - y0) * 0.5
        g.ellipse([x - 26, y - 26, x + 26, y + 26], col, OLC, 4)
        g.ellipse([x - 9, y - 6, x - 3, y + 2], OLC, None)
        g.ellipse([x + 3, y - 6, x + 9, y + 2], OLC, None)


def _draw_bg(g, bg, kind, t):
    wall = hexc(bg.get("color", bg.get("wall", "#a6dccd")))
    floor = hexc(bg.get("floor", "#d79a62"))
    curtain = hexc(bg.get("curtain", "#f7a943"))

    if kind in ("burst", "intro"):
        c1 = hexc(bg.get("color", "#2c2f4a" if kind == "intro" else "#ffe08a"))
        c2 = hexc(bg.get("color2", "#3d4170" if kind == "intro" else "#ffd04a"))
        g.rect([0, 0, W, H], c1)
        cx, cy = W / 2, H * 0.42
        rot = t * (0.6 if kind == "intro" else 0.35)
        for i in range(16):
            a0 = rot + i * math.pi / 8
            a1 = a0 + math.pi / 16
            g.poly([(cx, cy), (cx + 3000 * math.cos(a0), cy + 3000 * math.sin(a0)),
                    (cx + 3000 * math.cos(a1), cy + 3000 * math.sin(a1))], c2, None)
        if kind == "intro":
            lines = bg.get("text", "C'est que|chez moi ?").upper().split("|")
            plate = hexc(bg.get("plate", "#e8414f"))
            ph = 150 * len(lines) + 60
            g.rrect([70, cy - ph / 2 + 14, W - 70, cy + ph / 2 + 14], 50, mix(plate, DARK, 0.3), None)
            g.rrect([70, cy - ph / 2, W - 70, cy + ph / 2], 50, plate, OLC, 10)
            for i, ln in enumerate(lines):
                y = cy + (i - (len(lines) - 1) / 2) * 150
                size = 128
                while _font(size).getlength(ln) > W - 220 and size > 40:
                    size -= 4
                g.text((cx, y), ln, size, hexc(bg.get("accent", "#ffd93b")) if i == len(lines) - 1 else WHITE)
        return

    if kind == "plain":
        g.rect([0, 0, W, H], wall)
        dot = mix(wall, DARK, 0.08)
        for y in range(40, H, 90):
            for x in range(40 + (y // 90 % 2) * 45, W, 90):
                g.ellipse([x - 6, y - 6, x + 6, y + 6], dot, None)
        return

    if kind == "split":
        left = hexc(bg.get("left", "#fbe3a0"))
        right = hexc(bg.get("right", "#c9ccd8"))
        _wall(g, 0, W // 2, left)
        _wall(g, W // 2, W, right)
        _floor(g, floor)
        g.rect([W // 2 - 6, 0, W // 2 + 6, H], OLC)
        return

    if kind == "night":
        g.vgrad([0, 0, W, FLOOR_Y], (22, 24, 64), (86, 58, 120))
        for i in range(60):
            sx, sy = (i * 389 + 50) % W, (i * 241 + 30) % (FLOOR_Y - 400)
            r = 3 if i % 5 else 6
            g.ellipse([sx - r, sy - r, sx + r, sy + r], (255, 245, 210), None)
        g.ellipse([760, 180, 1000, 420], (90, 70, 130), None)
        g.ellipse([800, 220, 960, 380], (250, 240, 200))
        for dx, dy, r in ((-30, -20, 18), (25, 20, 14), (-5, 40, 10)):
            g.ellipse([880 + dx - r, 300 + dy - r, 880 + dx + r, 300 + dy + r], (225, 214, 172), None)
        x, i = 0, 0
        while x < W:
            bw = 120 + (i * 53) % 90
            bh = 160 + (i * 137) % 280
            g.rect([x, FLOOR_Y - bh, x + bw, FLOOR_Y], (40, 34, 74), OLC, 4)
            for wy in range(FLOOR_Y - bh + 30, FLOOR_Y - 30, 60):
                for wx in range(x + 20, x + bw - 30, 45):
                    if (wx * 7 + wy * 3 + i) % 4 == 0:
                        g.rect([wx, wy, wx + 22, wy + 28], (255, 215, 110))
            x += bw + 8
            i += 1
        g.rect([0, FLOOR_Y, W, H], (40, 70, 64))
        g.line([(0, FLOOR_Y), (W, FLOOR_Y)], OLC, 6)
        return

    if kind == "street":
        g.vgrad([0, 0, W, FLOOR_Y], hexc(bg.get("sky", "#86cdf5")), (215, 240, 255))
        for cxx, cyy in ((220, 220), (820, 140)):
            g.ellipse([cxx - 110, cyy - 34, cxx + 110, cyy + 34], WHITE, None)
            g.ellipse([cxx - 50, cyy - 70, cxx + 60, cyy + 20], WHITE, None)
        b = hexc(bg.get("color", "#e8916f"))
        g.rect([360, 240, W + 10, FLOOR_Y], b, OLC, 6)
        mortar = mix(b, DARK, 0.12)
        for y in range(270, FLOOR_Y, 60):
            g.line([(366, y), (W, y)], mortar, 3)
        for wy in (320, 560):
            for wx in (430, 650, 870):
                if wy == 560 and wx == 650:
                    continue
                g.rrect([wx, wy, wx + 150, wy + 170], 10, (250, 245, 235))
                g.rect([wx + 18, wy + 18, wx + 132, wy + 152], (255, 214, 130), OLC, 4)
        g.rrect([620, FLOOR_Y - 300, 790, FLOOR_Y + 6], 16, (130, 80, 55))
        g.ellipse([755, FLOOR_Y - 160, 771, FLOOR_Y - 144], (250, 210, 70), None)
        g.rect([100, FLOOR_Y - 600, 120, FLOOR_Y], (70, 72, 90), OLC, 4)
        g.rrect([70, FLOOR_Y - 660, 150, FLOOR_Y - 590], 16, (255, 226, 120))
        g.rect([0, FLOOR_Y, W, FLOOR_Y + 240], (210, 210, 220))
        for x in range(0, W, 140):
            g.line([(x, FLOOR_Y), (x, FLOOR_Y + 240)], (170, 170, 185), 4)
        g.rect([0, FLOOR_Y + 240, W, FLOOR_Y + 266], (130, 130, 145))
        g.rect([0, FLOOR_Y + 266, W, H], (110, 112, 130))
        for x in range(30, W, 220):
            g.rrect([x, FLOOR_Y + 390, x + 120, FLOOR_Y + 406], 8, WHITE, None)
        g.line([(0, FLOOR_Y), (W, FLOOR_Y)], OLC, 6)
        return

    if kind == "classroom":
        _wall(g, 0, W, wall)
        g.rrect([80, 260, 1000, 760], 16, (170, 115, 75))
        g.rect([110, 290, 970, 730], (60, 105, 82), OLC, 5)
        for x, y, w in ((170, 360, 360), (170, 420, 520), (170, 480, 280)):
            g.line([(x, y), (x + w, y)], (230, 240, 230), 6)
        g.text((420, 620), "1 + 1 = 2", 90, (230, 240, 230), stroke=0)
        _floor(g, floor)
        return

    if kind == "kitchen":
        tile = mix(wall, WHITE, 0.55)
        g.rect([0, 0, W, FLOOR_Y], wall)
        for y in range(560, 1080, 70):
            g.line([(0, y), (W, y)], tile, 4)
        for x in range(0, W, 70):
            g.line([(x, 560), (x, 1080)], tile, 4)
        g.rrect([40, 120, 520, 460], 16, (250, 246, 236))
        g.line([(280, 130), (280, 450)], OLC, 5)
        for x in (250, 310):
            g.rrect([x - 6, 260, x + 6, 330], 6, (190, 190, 205))
        g.rrect([20, 1060, W - 20, 1110], 12, (240, 236, 226))
        g.rect([40, 1110, W - 40, FLOOR_Y], (120, 170, 210), OLC, 6)
        for x in range(40, W - 40, 250):
            g.line([(x, 1110), (x, FLOOR_Y)], OLC, 5)
            g.rrect([x + 100, 1160, x + 150, 1176], 8, (230, 230, 240))
        g.rrect([640, 120, 1040, 1060], 30, (235, 240, 248))
        g.line([(640, 470), (1040, 470)], OLC, 6)
        g.rrect([680, 300, 700, 420], 8, (190, 190, 205))
        g.rrect([680, 520, 700, 680], 8, (190, 190, 205))
        g.ellipse([300, 950, 440, 1060], (250, 150, 60))
        g.ellipse([420, 970, 540, 1060], (230, 60, 70))
        _floor(g, hexc(bg.get("floor", "#e8e0d0")), tiles=True)
        return

    if kind == "bedroom":
        _wall(g, 0, W, wall)
        _window(g, 120, 260, 420, 620, curtain)
        g.rrect([620, 280, 960, 700], 12, (60, 70, 120))
        g.ellipse([700, 360, 880, 540], (250, 200, 80), None)
        g.text((790, 620), "GAMER", 56, WHITE, stroke=4)
        _floor(g, floor)
        g.ellipse([140, FLOOR_Y + 160, 940, FLOOR_Y + 420], mix(wall, DARK, 0.2), None)
        g.rrect([560, 980, 1100, FLOOR_Y + 80], 30, (140, 100, 70))
        g.rrect([600, 900, 800, 1000], 30, WHITE)
        g.rrect([560, 1020, 1100, 1180], 30, (90, 130, 220))
        return

    if kind == "salon":
        _wall(g, 0, W, wall)
        _frame(g, 120, 280, 420, 520)
        g.rrect([660, 320, 980, 560], 14, (40, 40, 52))
        g.rect([684, 344, 956, 536], (90, 190, 230), OLC, 4)
        g.rrect([780, 560, 860, 600], 6, (40, 40, 52))
        _floor(g, floor)
        g.ellipse([60, FLOOR_Y + 180, 1020, FLOOR_Y + 440], (210, 90, 90), None)
        g.rrect([40, 1000, 640, FLOOR_Y + 40], 60, (130, 160, 200))
        g.rrect([20, 940, 140, FLOOR_Y + 40], 50, (110, 140, 185))
        g.rrect([540, 940, 660, FLOOR_Y + 40], 50, (110, 140, 185))
        g.rrect([120, 920, 560, 1090], 40, (150, 180, 215))
        return

    # room
    _wall(g, 0, W, wall)
    _window(g, 640, 300, 960, 680, curtain)
    _frame(g, 110, 360, 360, 560)
    _floor(g, floor)
