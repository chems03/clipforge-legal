"""Procedural pixel-art sprites: characters, props and backgrounds.

Everything is drawn on a low-res canvas (135x240) and upscaled with
nearest-neighbour later, which gives the chunky pixel look.
"""
import math

from PIL import ImageDraw

W, H = 135, 240
FLOOR_Y = 172
OL = (34, 30, 48)  # outline colour
WHITE = (250, 250, 245)


def hexc(c):
    if isinstance(c, (tuple, list)):
        return tuple(c)
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def R(d, x, y, w, h, c):
    if w > 0 and h > 0:
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=c)


def ORect(d, x, y, w, h, c):
    """Rectangle with a 1px outline."""
    R(d, x, y, w, h, OL)
    R(d, x + 1, y + 1, w - 2, h - 2, c)


def P(d, x, y, c):
    d.point((x, y), fill=c)


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------

SKINS = {
    "light": "#f6d2b0", "medium": "#d9a27a", "tan": "#b77b52", "dark": "#7a4a30",
}

DEFAULT_CHAR = {
    "skin": "light", "hair": "short", "hair_color": "#3b2a20",
    "shirt": "#3d6fd6", "pants": "#2b2f45", "shoes": "#f4f4f4",
    "size": 1.0, "acc": [],
}


def draw_character(img, x, feet, spec, expr="neutral", pose="stand",
                   blink=False, flip=False, hold=None, t=0.0):
    """Draw a chibi character centred on x with feet at `feet`.

    The body is drawn on a 26x48 grid; `size` < 1 gives a kid (shorter legs/body).
    """
    s = dict(DEFAULT_CHAR)
    s.update(spec or {})
    d = ImageDraw.Draw(img)
    skin = hexc(SKINS.get(s["skin"], s["skin"]))
    hair = hexc(s["hair_color"])
    shirt = hexc(s["shirt"])
    pants = hexc(s["pants"])
    shoes = hexc(s["shoes"])
    kid = s["size"] < 1.0
    acc = s["acc"]

    leg_h = 7 if kid else 10
    body_h = 11 if kid else 14
    body_w = 14 if kid else 16
    head = 16 if kid else 18

    # --- legs & shoes
    ly = feet - 3 - leg_h
    R(d, x - 5, ly, 4, leg_h, OL)
    R(d, x + 1, ly, 4, leg_h, OL)
    R(d, x - 4, ly, 2, leg_h, pants)
    R(d, x + 2, ly, 2, leg_h, pants)
    ORect(d, x - 7, feet - 4, 7, 4, shoes)
    ORect(d, x, feet - 4, 7, 4, shoes)

    # --- body
    by = ly - body_h + 1
    bx = x - body_w // 2
    ORect(d, bx, by, body_w, body_h, shirt)
    R(d, bx + 1, by + body_h - 3, body_w - 2, 2, shade(shirt, 0.8))
    if "dress" in acc:
        ORect(d, bx - 2, by + body_h - 4, body_w + 4, leg_h - 1, shirt)
    if "hoodie" in acc:
        R(d, x - 1, by + 2, 1, 4, WHITE)
        R(d, x + 1, by + 2, 1, 4, WHITE)
        R(d, bx + 4, by + 7, body_w - 8, 3, shade(shirt, 0.85))

    # --- arms
    arm_len = body_h - 2
    for side in (-1, 1):
        ax = bx - 3 if side < 0 else bx + body_w - 1
        up = pose == "arms_up" or (pose == "wave" and side == 1 and int(t * 4) % 2 == 0)
        if up:
            R(d, ax, by - arm_len + 3, 4, arm_len, OL)
            R(d, ax + 1, by - arm_len + 4, 2, arm_len - 2, shirt)
            ORect(d, ax, by - arm_len, 4, 4, skin)
        else:
            R(d, ax, by + 1, 4, arm_len, OL)
            R(d, ax + 1, by + 2, 2, arm_len - 2, shirt)
            ORect(d, ax, by + arm_len - 1, 4, 4, skin)

    if hold:
        hx = bx + body_w + 1 if not flip else bx - 11
        draw_prop(img, hold, hx + 5, by + arm_len - 4, scale=0.8, t=t)

    # --- head
    hy = by - head + 1
    hx = x - head // 2
    R(d, hx + 1, hy, head - 2, head, OL)  # outline with cut corners
    R(d, hx, hy + 1, head, head - 2, OL)
    R(d, hx + 1, hy + 1, head - 2, head - 2, skin)
    R(d, hx + 1, hy + head - 3, head - 2, 1, shade(skin, 0.9))

    _draw_hair(d, img, s["hair"], hair, hx, hy, head)
    _draw_face(d, hx, hy, head, expr, blink, flip, acc, skin)
    _draw_acc(d, acc, hx, hy, head, hair)
    return hy  # top of head, useful for bubbles


def _draw_hair(d, img, style, c, hx, hy, hs):
    dark = shade(c, 0.75)
    if style == "bald":
        return
    if style in ("short", "spiky", "curly", "bun", "long", "ponytail", "afro", "mohawk"):
        R(d, hx - 1, hy - 1, hs + 2, 5, OL)
        R(d, hx, hy, hs, 4, c)
        R(d, hx, hy + 4, 2, 3, c)
        R(d, hx + hs - 2, hy + 4, 2, 3, c)
        R(d, hx + 3, hy + 3, 5, 2, c)  # fringe
        R(d, hx + 1, hy + 1, hs - 2, 1, shade(c, 1.25))
    if style == "spiky":
        for i in range(4):
            sx = hx + 1 + i * 4
            R(d, sx, hy - 4, 3, 3, OL)
            R(d, sx + 1, hy - 3, 1, 3, c)
    if style == "mohawk":
        R(d, hx + hs // 2 - 3, hy - 6, 6, 6, OL)
        R(d, hx + hs // 2 - 2, hy - 5, 4, 6, c)
    if style == "curly":
        for i in range(5):
            ORect(d, hx - 2 + i * 4, hy - 3, 5, 4, c)
    if style == "afro":
        ORect(d, hx - 4, hy - 6, hs + 8, 12, c)
        for i in range(6):
            P(d, hx - 2 + i * 4, hy - 4, dark)
        R(d, hx + 1, hy + 5, hs - 2, 1, OL)
    if style == "bun":
        bx, by = hx + hs // 2 - 4, hy - 7
        R(d, bx + 1, by, 6, 8, OL)
        R(d, bx, by + 1, 8, 6, OL)
        R(d, bx + 1, by + 1, 6, 6, c)
        R(d, bx + 2, by + 2, 2, 1, shade(c, 1.4))
        R(d, bx + 1, by + 6, 6, 2, (240, 120, 160))
    if style in ("long", "ponytail"):
        R(d, hx - 2, hy + 2, 3, hs + 2, OL)
        R(d, hx + hs - 1, hy + 2, 3, hs + 2, OL)
        R(d, hx - 1, hy + 2, 2, hs + 1, c)
        R(d, hx + hs - 1, hy + 2, 2, hs + 1, c)
    if style == "ponytail":
        ORect(d, hx + hs, hy + 1, 5, 9, c)


def _draw_face(d, hx, hy, hs, expr, blink, flip, acc, skin):
    ey = hy + 8
    lx, rx = hx + 4, hx + hs - 6
    look = -1 if flip else 0
    # eyes
    if blink or expr in ("happy", "laugh"):
        if expr in ("happy", "laugh") and not blink:
            for ex in (lx, rx):  # ^ ^ eyes
                P(d, ex, ey + 1, OL); P(d, ex + 1, ey, OL); P(d, ex + 2, ey + 1, OL)
        else:
            R(d, lx, ey + 1, 3, 1, OL)
            R(d, rx, ey + 1, 3, 1, OL)
    elif expr == "shocked":
        for ex in (lx, rx):
            ORect(d, ex - 1, ey - 1, 4, 4, WHITE)
            P(d, ex + 1, ey + 1, OL)
    else:
        for ex in (lx, rx):
            R(d, ex + 1 + look, ey, 2, 3, OL)
            P(d, ex + 1 + look, ey, WHITE)
    # brows
    if expr == "angry":
        P(d, lx, ey - 3, OL); R(d, lx + 1, ey - 2, 2, 1, OL)
        P(d, rx + 2, ey - 3, OL); R(d, rx, ey - 2, 2, 1, OL)
    elif expr in ("sad", "worried"):
        R(d, lx, ey - 2, 2, 1, OL); P(d, lx + 2, ey - 3, OL)
        R(d, rx + 1, ey - 2, 2, 1, OL); P(d, rx, ey - 3, OL)
    # cheeks
    if expr in ("happy", "laugh", "love"):
        R(d, hx + 2, ey + 4, 2, 1, (240, 140, 140))
        R(d, hx + hs - 4, ey + 4, 2, 1, (240, 140, 140))
    # mouth
    mx, my = hx + hs // 2, hy + hs - 5
    if expr == "happy":
        R(d, mx - 3, my, 6, 1, OL); P(d, mx - 4, my - 1, OL); P(d, mx + 3, my - 1, OL)
    elif expr == "laugh":
        ORect(d, mx - 3, my - 1, 7, 4, (200, 60, 70)); R(d, mx - 2, my - 1, 5, 1, WHITE)
    elif expr == "sad":
        R(d, mx - 2, my, 5, 1, OL); P(d, mx - 3, my + 1, OL); P(d, mx + 3, my + 1, OL)
    elif expr == "shocked":
        ORect(d, mx - 2, my - 1, 4, 4, (120, 30, 40))
    elif expr == "angry":
        R(d, mx - 3, my, 7, 2, OL); R(d, mx - 2, my, 5, 1, WHITE)
    elif expr == "worried":
        for i in range(6):
            P(d, mx - 3 + i, my + (i % 2), OL)
    elif expr == "smirk":
        R(d, mx - 1, my, 4, 1, OL); P(d, mx + 3, my - 1, OL)
    elif expr == "love":
        R(d, mx - 2, my, 5, 1, OL)
    else:
        R(d, mx - 2, my, 4, 1, OL)
    if expr == "love" and not blink:
        for ex in (lx, rx):
            R(d, ex, ey, 1, 2, (230, 50, 80)); R(d, ex + 2, ey, 1, 2, (230, 50, 80))
            P(d, ex + 1, ey + 1, (230, 50, 80)); P(d, ex + 1, ey + 2, (230, 50, 80))
    if expr == "sad" and not blink:
        R(d, lx + 1, ey + 3, 1, 3, (110, 180, 240))


def _draw_acc(d, acc, hx, hy, hs, hair):
    if "glasses" in acc:
        ey = hy + 7
        for ex in (hx + 2, hx + hs - 8):
            R(d, ex, ey, 6, 1, OL); R(d, ex, ey + 4, 6, 1, OL)
            R(d, ex, ey, 1, 5, OL); R(d, ex + 5, ey, 1, 5, OL)
        R(d, hx + 8, ey + 1, hs - 16, 1, OL)
    if "mustache" in acc:
        R(d, hx + hs // 2 - 4, hy + hs - 7, 8, 2, OL)
    if "beard" in acc:
        R(d, hx + 1, hy + hs - 6, hs - 2, 6, shade(hair, 1.0))
        R(d, hx + hs // 2 - 2, hy + hs - 5, 4, 1, (120, 40, 50))
    if "earrings" in acc:
        R(d, hx - 1, hy + 12, 2, 3, (240, 200, 50))
        R(d, hx + hs - 1, hy + 12, 2, 3, (240, 200, 50))
    if "crown" in acc:
        gy = hy - 7
        ORect(d, hx + 2, gy + 3, hs - 4, 5, (250, 200, 40))
        for i in range(3):
            px = hx + 3 + i * ((hs - 7) // 2)
            R(d, px, gy, 3, 4, OL); P(d, px + 1, gy + 1, (250, 200, 40)); R(d, px + 1, gy + 2, 1, 2, (250, 200, 40))
        P(d, hx + hs // 2, gy + 5, (230, 50, 80))
    if "cap" in acc:
        ORect(d, hx - 1, hy - 3, hs + 2, 7, (220, 60, 60))
        R(d, hx + hs - 2, hy + 2, 7, 2, OL)
    if "beanie" in acc:
        ORect(d, hx - 1, hy - 4, hs + 2, 8, (150, 90, 210))
        R(d, hx, hy + 1, hs, 2, shade((150, 90, 210), 0.8))
        ORect(d, hx + hs // 2 - 2, hy - 7, 4, 4, WHITE)
    if "headphones" in acc:
        R(d, hx - 1, hy - 2, hs + 2, 2, OL)
        ORect(d, hx - 3, hy + 6, 4, 6, (60, 60, 70))
        ORect(d, hx + hs - 1, hy + 6, 4, 6, (60, 60, 70))
    if "police" in acc:
        ORect(d, hx - 1, hy - 4, hs + 2, 7, (40, 70, 60))
        R(d, hx - 1, hy + 2, hs + 4, 2, OL)
        R(d, hx + hs // 2 - 1, hy - 2, 3, 2, (250, 200, 40))


# --------------------------------------------------------------------------
# Props
# --------------------------------------------------------------------------

PROPS = ["phone", "gift", "tv", "lock", "heart", "x", "check", "question",
         "exclam", "controller", "money", "book", "pizza", "clock", "star",
         "zzz", "bulb", "trophy", "sweat", "anger"]


def draw_prop(img, kind, cx, cy, scale=1, t=0.0):
    """Draw a prop centred on (cx, cy), `scale` = integer pixel size (1, 2, 3)."""
    from PIL import Image
    k = max(1, int(round(scale)))
    tmp = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    _prop(ImageDraw.Draw(tmp), kind, 16, 16, t)
    if k > 1:
        tmp = tmp.resize((32 * k, 32 * k), Image.NEAREST)
    img.paste(tmp, (int(cx) - 16 * k, int(cy) - 16 * k), tmp)


def _prop(d, kind, cx, cy, t):
    if kind == "phone":
        ORect(d, cx - 4, cy - 7, 9, 14, (40, 40, 50))
        R(d, cx - 3, cy - 5, 7, 9, (90, 170, 240))
        R(d, cx - 2, cy - 4, 2, 2, WHITE)
    elif kind == "gift":
        ORect(d, cx - 7, cy - 4, 15, 11, (230, 70, 100))
        ORect(d, cx - 8, cy - 7, 17, 4, (240, 90, 120))
        R(d, cx - 1, cy - 6, 3, 13, (250, 210, 60))
        R(d, cx - 4, cy - 10, 3, 3, (250, 210, 60)); R(d, cx + 2, cy - 10, 3, 3, (250, 210, 60))
    elif kind == "tv":
        ORect(d, cx - 9, cy - 6, 19, 13, (50, 50, 60))
        R(d, cx - 7, cy - 4, 15, 9, (80, 200, 230))
        R(d, cx - 1, cy - 1, 3, 3, WHITE)
        R(d, cx - 4, cy + 7, 9, 2, OL)
    elif kind == "lock":
        R(d, cx - 4, cy - 9, 9, 6, OL); R(d, cx - 2, cy - 7, 5, 5, (0, 0, 0, 0))
        R(d, cx - 3, cy - 8, 1, 5, (180, 180, 190)); R(d, cx + 3, cy - 8, 1, 5, (180, 180, 190))
        ORect(d, cx - 6, cy - 3, 13, 10, (245, 190, 50))
        R(d, cx, cy, 1, 3, OL)
    elif kind == "heart":
        c = (235, 60, 90)
        for y, row in enumerate([".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."]):
            for x, ch in enumerate(row):
                if ch == "#":
                    P(d, cx - 3 + x, cy - 3 + y, c)
        P(d, cx - 2, cy - 2, WHITE)
    elif kind == "x":
        c = (230, 50, 60)
        for i in range(9):
            R(d, cx - 4 + i, cy - 4 + i, 2, 2, c)
            R(d, cx + 4 - i, cy - 4 + i, 2, 2, c)
    elif kind == "check":
        c = (60, 200, 90)
        for i in range(4):
            R(d, cx - 5 + i, cy + i - 1, 2, 2, c)
        for i in range(7):
            R(d, cx - 2 + i, cy + 2 - i, 2, 2, c)
    elif kind in ("question", "exclam"):
        ORect(d, cx - 5, cy - 7, 11, 13, WHITE)
        c = (60, 110, 230) if kind == "question" else (230, 60, 60)
        if kind == "question":
            R(d, cx - 2, cy - 5, 5, 1, c); R(d, cx + 2, cy - 4, 1, 3, c)
            R(d, cx, cy - 1, 2, 1, c); R(d, cx, cy, 1, 2, c); R(d, cx, cy + 3, 1, 1, c)
        else:
            R(d, cx, cy - 5, 2, 6, c); R(d, cx, cy + 2, 2, 2, c)
    elif kind == "controller":
        ORect(d, cx - 8, cy - 3, 17, 8, (60, 60, 75))
        R(d, cx - 6, cy, 3, 1, WHITE); R(d, cx - 5, cy - 1, 1, 3, WHITE)
        P(d, cx + 4, cy - 1, (230, 60, 60)); P(d, cx + 6, cy + 1, (60, 200, 90))
    elif kind == "money":
        ORect(d, cx - 8, cy - 4, 17, 9, (110, 200, 110))
        ORect(d, cx - 2, cy - 2, 5, 5, (70, 160, 80))
    elif kind == "book":
        ORect(d, cx - 6, cy - 7, 13, 15, (70, 120, 220))
        R(d, cx - 5, cy + 4, 11, 2, WHITE)
        R(d, cx - 3, cy - 4, 7, 1, WHITE)
    elif kind == "pizza":
        for i in range(10):
            R(d, cx - 5 + i // 2, cy - 5 + i, 11 - i, 1, (245, 200, 90) if i else (200, 120, 50))
        P(d, cx - 1, cy - 2, (210, 60, 50)); P(d, cx + 1, cy, (210, 60, 50)); P(d, cx, cy + 2, (210, 60, 50))
    elif kind == "clock":
        d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=WHITE, outline=OL)
        a = t * 2.0
        d.line([cx, cy, cx, cy - 6], fill=OL)
        d.line([cx, cy, cx + int(5 * math.cos(a)), cy + int(5 * math.sin(a))], fill=(230, 60, 60))
    elif kind == "star":
        c = (250, 210, 50)
        for y, row in enumerate(["...#...", "..###..", "#######", ".#####.", ".##.##.", "#.....#"]):
            for x, ch in enumerate(row):
                if ch == "#":
                    P(d, cx - 3 + x, cy - 3 + y, c)
    elif kind == "zzz":
        for i, (ox, oy) in enumerate(((0, 4), (5, -1), (9, -6))):
            z = 3 + i
            R(d, cx + ox, cy + oy, z, 1, WHITE); R(d, cx + ox, cy + oy + z, z, 1, WHITE)
            for j in range(z):
                P(d, cx + ox + z - 1 - j, cy + oy + j, WHITE)
    elif kind == "bulb":
        d.ellipse([cx - 5, cy - 8, cx + 5, cy + 2], fill=(255, 230, 90), outline=OL)
        ORect(d, cx - 3, cy + 2, 7, 4, (170, 170, 180))
    elif kind == "trophy":
        ORect(d, cx - 6, cy - 8, 13, 9, (250, 200, 40))
        ORect(d, cx - 1, cy + 1, 3, 4, (250, 200, 40))
        ORect(d, cx - 5, cy + 5, 11, 3, (200, 140, 40))
    elif kind == "sweat":
        R(d, cx, cy - 2, 2, 2, (120, 190, 250)); R(d, cx - 1, cy, 4, 3, (120, 190, 250))
    elif kind == "anger":
        c = (230, 50, 60)
        for ox, oy in ((-3, -3), (2, -3), (-3, 2), (2, 2)):
            R(d, cx + ox, cy + oy, 2, 2, c)


# --------------------------------------------------------------------------
# Backgrounds
# --------------------------------------------------------------------------

def draw_background(img, bg, t=0.0):
    d = ImageDraw.Draw(img)
    kind = bg.get("type", "room")
    wall = hexc(bg.get("color", bg.get("wall", "#9fd8c8")))
    floor = hexc(bg.get("floor", "#c8925a"))

    if kind == "burst":
        c2 = hexc(bg.get("color2", "#f7b4b4"))
        R(d, 0, 0, W, H, wall)
        cx, cy = W // 2, int(H * 0.45)
        rot = t * 0.4
        for i in range(12):
            a0 = rot + i * math.pi / 6
            a1 = a0 + math.pi / 12
            d.polygon([(cx, cy), (cx + 300 * math.cos(a0), cy + 300 * math.sin(a0)),
                       (cx + 300 * math.cos(a1), cy + 300 * math.sin(a1))], fill=c2)
        return

    if kind == "split":
        left = hexc(bg.get("left", "#fbe3a0"))
        right = hexc(bg.get("right", "#c9ccd8"))
        R(d, 0, 0, W // 2, H, left)
        R(d, W // 2, 0, W - W // 2, H, right)
        R(d, 0, FLOOR_Y, W, H - FLOOR_Y, floor)
        _planks(d, floor)
        R(d, W // 2 - 1, 0, 2, H, OL)
        return

    if kind == "plain":
        R(d, 0, 0, W, H, wall)
        dot = shade(wall, 0.93)
        for y in range(4, H, 10):
            for x in range(4 + (y // 10 % 2) * 5, W, 10):
                P(d, x, y, dot)
        return

    if kind == "night":
        R(d, 0, 0, W, H, (28, 30, 70))
        for i in range(40):
            sx, sy = (i * 47) % W, (i * 89) % (FLOOR_Y - 10)
            if (i + int(t * 3)) % 7:
                P(d, sx, sy, (240, 240, 200))
        d.ellipse([95, 20, 115, 40], fill=(250, 240, 190))
        d.ellipse([101, 17, 121, 37], fill=(28, 30, 70))
        R(d, 0, FLOOR_Y, W, H - FLOOR_Y, (40, 50, 60))
        return

    if kind == "street":
        R(d, 0, 0, W, H, hexc(bg.get("sky", "#9fd6f2")))
        b = hexc(bg.get("color", "#e48a6a"))
        ORect(d, 50, 40, 90, FLOOR_Y - 40, b)
        for wy in range(52, FLOOR_Y - 30, 26):
            for wx in (62, 92, 118):
                ORect(d, wx, wy, 12, 14, (250, 230, 150))
        ORect(d, 85, FLOOR_Y - 28, 16, 28, (120, 70, 50))
        ORect(d, 4, FLOOR_Y - 60, 3, 60, (60, 60, 70))
        ORect(d, 1, FLOOR_Y - 64, 9, 6, (250, 230, 120))
        R(d, 0, FLOOR_Y, W, 12, (190, 190, 200))
        R(d, 0, FLOOR_Y + 12, W, H, (110, 115, 130))
        for x in range(0, W, 24):
            R(d, x + int(t * 20) % 24 - 12, FLOOR_Y + 36, 12, 2, WHITE)
        return

    if kind == "classroom":
        R(d, 0, 0, W, FLOOR_Y, wall)
        ORect(d, 14, 40, 107, 55, (50, 90, 70))
        R(d, 22, 52, 40, 1, WHITE); R(d, 22, 60, 60, 1, WHITE); R(d, 22, 68, 30, 1, WHITE)
        R(d, 0, FLOOR_Y, W, H - FLOOR_Y, floor)
        _planks(d, floor)
        return

    # default: room
    R(d, 0, 0, W, FLOOR_Y, wall)
    stripe = shade(wall, 0.95)
    for x in range(0, W, 8):
        R(d, x, 0, 3, FLOOR_Y, stripe)
    # window
    ORect(d, 80, 30, 44, 50, (180, 225, 250))
    R(d, 101, 31, 2, 48, OL); R(d, 81, 54, 42, 2, OL)
    R(d, 84, 60, 12, 10, (130, 150, 210))
    ORect(d, 74, 26, 56, 5, (120, 80, 60))
    ORect(d, 74, 30, 9, 56, (250, 175, 60))
    ORect(d, 121, 30, 9, 56, (250, 175, 60))
    # picture frame
    ORect(d, 14, 44, 24, 18, (200, 150, 90))
    R(d, 16, 46, 20, 14, (250, 245, 230))
    R(d, 19, 50, 4, 4, (240, 190, 150)); R(d, 28, 50, 4, 4, (240, 190, 150))
    R(d, 0, FLOOR_Y - 3, W, 3, shade(wall, 0.75))
    R(d, 0, FLOOR_Y, W, H - FLOOR_Y, floor)
    _planks(d, floor)


def _planks(d, floor):
    line = shade(floor, 0.82)
    for x in range(0, W, 14):
        R(d, x, FLOOR_Y, 1, H - FLOOR_Y, line)
