"""Animated montage: kinetic captions + motion-graphics scenes over a moving background.

Inputs:
  timeline JSON: {"words": [{"w": str, "s": float, "e": float}], "blocks": [{"n", "s", "e"}]}
  visuals JSON : {"<block n>": {"type": "big|counter|quote|list|year|none", ...}}
  optional audio file, optional background clips dir (one mp4 per block, from Pexels)
Output: mp4 at 1920x1080, 30 fps.
"""
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
YELLOW, WHITE, BLACK = (255, 200, 0), (255, 255, 255), (0, 0, 0)
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/montserrat/Montserrat-Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_PATH = next(p for p in FONT_CANDIDATES if os.path.exists(p))
_fonts = {}


def font(size):
    size = max(8, int(size))
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT_PATH, size)
    return _fonts[size]


def ease_out(t):
    t = min(max(t, 0), 1)
    return 1 - (1 - t) ** 3


def ease_back(t):
    t = min(max(t, 0), 1)
    c = 1.9
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


# ---------- background ----------
def make_background():
    base = Image.new("RGB", (W + 400, H + 400), (10, 10, 14))
    blobs = Image.new("RGB", base.size, (0, 0, 0))
    d = ImageDraw.Draw(blobs)
    for (x, y, r, c) in [(300, 300, 380, (90, 60, 0)), (1700, 500, 420, (20, 40, 90)),
                         (900, 1200, 460, (60, 20, 50)), (1500, 1300, 300, (90, 70, 0))]:
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    blobs = blobs.filter(ImageFilter.GaussianBlur(160))
    return Image.blend(base, blobs, 0.85)


class Background:
    def __init__(self, clips_dir=None):
        self.img = make_background()
        self.clips_dir = clips_dir

    def frame(self, t):
        x = 200 + 160 * math.sin(t / 7)
        y = 200 + 120 * math.cos(t / 9)
        return self.img.crop((int(x), int(y), int(x) + W, int(y) + H))


# ---------- text helpers ----------
def text_img(text, size, fill=WHITE, stroke=8):
    f = font(size)
    l, t, r, b = f.getbbox(text, stroke_width=stroke)
    im = Image.new("RGBA", (r - l + 4, b - t + 4), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((2 - l, 2 - t), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=BLACK)
    return im


def paste_center(canvas, im, cx, cy, scale=1.0, alpha=1.0, angle=0):
    if scale <= 0.01 or alpha <= 0.01:
        return
    if scale != 1.0:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BICUBIC)
    if angle:
        im = im.rotate(angle, expand=True, resample=Image.BICUBIC)
    if alpha < 1.0:
        a = im.getchannel("A").point(lambda v: int(v * alpha))
        im.putalpha(a)
    canvas.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))


def fit_size(text, size, max_w):
    while size > 30 and font(size).getlength(text) > max_w:
        size -= 6
    return size


# ---------- scene layers ----------
def layer_big(canvas, v, lt, dur):
    lines = v["text"].split("\n")
    for i, line in enumerate(lines):
        t0 = i * 0.35
        k = ease_back((lt - t0) / 0.45)
        size = fit_size(line, v.get("size", 200), W - 240)
        shake = 6 * math.sin(lt * 60) * max(0, 1 - (lt - t0) / 0.3) if lt > t0 else 0
        paste_center(canvas, text_img(line, size, YELLOW if i == 0 else WHITE), W / 2 + shake,
                     330 + i * (size * 1.05) - (len(lines) - 1) * size * 0.3, scale=k, alpha=min(1, k * 1.5))


def fmt_number(x, decimals, sep=" "):
    s = f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return s


def layer_counter(canvas, v, lt, dur):
    k = ease_out(lt / v.get("speed", 1.4))
    val = v["value"] * k
    txt = f"{v.get('prefix', '')}{fmt_number(val, v.get('decimals', 0))}{v.get('suffix', '')}"
    size = fit_size(txt, 230, W - 200)
    pop = 1 + 0.08 * math.sin(min(lt / 0.25, 1) * math.pi)
    paste_center(canvas, text_img(txt, size, YELLOW, 10), W / 2, 330, scale=pop)
    if v.get("label"):
        a = ease_out((lt - 0.6) / 0.4)
        paste_center(canvas, text_img(v["label"], fit_size(v["label"], 64, W - 240), WHITE, 5), W / 2, 500,
                     alpha=a, scale=0.9 + 0.1 * a)


def layer_quote(canvas, v, lt, dur):
    full = "« " + v["text"] + " »"
    n = int(len(full) * min(1, lt / max(0.8, dur * 0.6)))
    shown = full[:n]
    size = fit_size(full, 92, W - 200)
    paste_center(canvas, text_img(shown or " ", size, WHITE, 6), W / 2, 330)
    if v.get("author") and n == len(full):
        paste_center(canvas, text_img("— " + v["author"], 46, YELLOW, 4), W / 2, 460)


def layer_list(canvas, v, lt, dur):
    items = v["items"]
    step = max(0.4, (dur * 0.8) / len(items))
    for i, it in enumerate(items):
        k = ease_back((lt - i * step) / 0.35)
        if k <= 0:
            continue
        size = fit_size(it, 84, W - 300)
        y = 220 + i * 120
        paste_center(canvas, text_img(it, size, YELLOW if i == len(items) - 1 else WHITE), W / 2 - 60 * (1 - k), y,
                     alpha=min(1, k), scale=0.8 + 0.2 * k)


def layer_year(canvas, v, lt, dur):
    k = ease_out(lt / 0.6)
    scale = 2.2 - 1.2 * k
    paste_center(canvas, text_img(v["text"], 260, YELLOW, 10), W / 2, 340, scale=scale, alpha=min(1, k * 1.4))
    if v.get("label"):
        a = ease_out((lt - 0.5) / 0.4)
        paste_center(canvas, text_img(v["label"], fit_size(v["label"], 60, W - 240), WHITE, 5), W / 2, 580, alpha=a)


LAYERS = {"big": layer_big, "counter": layer_counter, "quote": layer_quote, "list": layer_list, "year": layer_year}


# ---------- captions ----------
def caption_groups(words, max_words=4, max_gap=0.5):
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["s"] - cur[-1]["e"] > max_gap or cur[-1]["w"][-1:] in ".?!…"):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def draw_captions(canvas, groups, t, y=880):
    g = next((g for g in groups if g[0]["s"] - 0.05 <= t <= g[-1]["e"] + 0.15), None)
    if not g:
        return
    size = 86
    imgs = []
    for w in g:
        active = w["s"] <= t <= w["e"] + 0.05
        imgs.append((text_img(w["w"].upper(), size, YELLOW if active else WHITE, 9), w))
    gap = 26
    total = sum(i.width for i, _ in imgs) + gap * (len(imgs) - 1)
    if total > W - 120:
        k = (W - 120) / total
        imgs = [(i.resize((int(i.width * k), int(i.height * k))), w) for i, w in imgs]
        gap *= k
        total = W - 120
    x = (W - total) / 2
    for im, w in imgs:
        age = t - w["s"]
        pop = 1 + 0.18 * max(0, 1 - age / 0.12) if age >= 0 else 1
        paste_center(canvas, im, x + im.width / 2, y, scale=pop)
        x += im.width + gap


# ---------- main render ----------
def render(timeline, visuals, out, audio=None, start=0.0, end=None):
    words, blocks = timeline["words"], timeline["blocks"]
    end = end or blocks[-1]["e"] + 0.5
    groups = caption_groups(words)
    bg = Background()
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-"]
    if audio:
        cmd += ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", audio, "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int((end - start) * FPS)
    for i in range(n):
        t = start + i / FPS
        blk = next((b for b in blocks if b["s"] <= t < b["e"]), blocks[-1])
        lt, dur = t - blk["s"], blk["e"] - blk["s"]
        # punch-in zoom at each block start
        frame = bg.frame(t)
        zoom = 1 + 0.06 * max(0, 1 - lt / 0.35)
        if zoom > 1.001:
            cw, ch = int(W / zoom), int(H / zoom)
            frame = frame.crop(((W - cw) // 2, (H - ch) // 2, (W + cw) // 2, (H + ch) // 2)).resize((W, H))
        canvas = frame.convert("RGBA")
        v = visuals.get(str(blk["n"]))
        if v and v.get("type") in LAYERS:
            LAYERS[v["type"]](canvas, v, lt, dur)
        draw_captions(canvas, groups, t)
        if lt < 0.06 and blk is not blocks[0]:  # white flash cut
            canvas = Image.blend(canvas, Image.new("RGBA", (W, H), (255, 255, 255, 255)), 0.5 * (1 - lt / 0.06))
        proc.stdin.write(canvas.convert("RGB").tobytes())
        if i % (FPS * 10) == 0:
            print(f"  rendu {t:.0f}/{end:.0f} s", flush=True)
    proc.stdin.close()
    proc.wait()


if __name__ == "__main__":
    tl = json.load(open(sys.argv[1], encoding="utf-8"))
    vis = json.load(open(sys.argv[2], encoding="utf-8"))
    render(tl, vis, sys.argv[3], audio=sys.argv[4] if len(sys.argv) > 4 else None)
