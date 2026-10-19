"""Render a pixel-art story video from a JSON script.

Usage:
    python3 -m pixelforge.render stories/exemple.json -o out/exemple.mp4 [--tts] [--music m.mp3]
"""
import argparse
import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

from . import sprites
from .sprites import W, H, FLOOR_Y

SCALE = 8                       # 135x240 -> 1080x1920
CHAR_W, CHAR_H = 64, 72         # character sprite box before its own upscale
OUT_W, OUT_H = W * SCALE, H * SCALE
CAP_SCALE = 4                   # captions are drawn at 270x480 then upscaled
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def load_font(size, path=None):
    for p in ([path] if path else []) + FONT_CANDIDATES:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


# --------------------------------------------------------------------------
# Timing: words -> (start, end) within each scene
# --------------------------------------------------------------------------

def split_words(text):
    """Split on spaces, gluing lone punctuation ("!", "?", "»") to the previous word."""
    out = []
    for w in text.split():
        if out and all(ch in "!?:;.,»…" for ch in w):
            out[-1] += "\u00a0" + w
        else:
            out.append(w)
    return out


def even_word_times(words, duration, lead=0.15):
    """Spread words over the scene, weighting by word length."""
    if not words:
        return []
    weights = [len(w) + 2 for w in words]
    total = sum(weights)
    span = max(0.1, duration - lead - 0.2)
    t, out = lead, []
    for w, k in zip(words, weights):
        dt = span * k / total
        out.append((t, t + dt))
        t += dt
    return out


async def _tts_scene(text, voice, rate, mp3_path):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    marks = []
    with open(mp3_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                marks.append((chunk["text"], s, s + chunk["duration"] / 1e7))
    return marks


def audio_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def plan_timeline(story, tts, tmp):
    """Return list of scenes with absolute start/end and word timings."""
    wps = story.get("words_per_second", 2.6)
    voice = story.get("voice", "fr-FR-HenriNeural")
    rate = story.get("voice_rate", "+8%")
    t = 0.0
    plan = []
    for i, sc in enumerate(story["scenes"]):
        text = sc.get("text", "")
        words = split_words(text)
        audio = sc.get("audio")
        marks = None
        if tts and text and not audio:
            audio = os.path.join(tmp, f"scene{i:03d}.mp3")
            try:
                marks = asyncio.run(_tts_scene(text, sc.get("voice", voice), rate, audio))
            except Exception as e:  # network down, edge-tts missing...
                print(f"[tts] scène {i}: {e} -> sans voix", file=sys.stderr)
                audio, marks = None, None
        if audio:
            dur = sc.get("duration") or audio_duration(audio) + 0.25
        else:
            dur = sc.get("duration") or max(1.2, len(words) / wps + 0.4)
        if marks and len(marks) == len(words):
            wt = [(s + 0.05, e + 0.05) for _, s, e in marks]
        else:
            wt = even_word_times(words, dur, lead=0.05 if audio else 0.15)
        plan.append({"scene": sc, "start": t, "end": t + dur, "words": words,
                     "word_times": wt, "audio": audio})
        t += dur
    return plan, t


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def char_offset(anim, lt, seed):
    """(dx, dy) for a character animation at local time lt."""
    bob = 1 if int((lt + seed * 0.37) * 2.5) % 2 else 0
    if anim == "jump":
        ph = (lt * 2.2 + seed * 0.3) % 1.0
        return 0, -int(10 * math.sin(ph * math.pi))
    if anim == "bounce":
        return 0, -abs(int(3 * math.sin(lt * 9 + seed)))
    if anim == "shake":
        return int(2 * math.sin(lt * 50 + seed)), 0
    if anim == "walk_in":
        p = min(1.0, lt / 0.6)
        return int((1 - p) * -90), -(int(lt * 8) % 2)
    if anim == "walk_in_right":
        p = min(1.0, lt / 0.6)
        return int((1 - p) * 90), -(int(lt * 8) % 2)
    if anim == "none":
        return 0, 0
    return 0, -bob


def prop_visible(p, lt, word_times):
    at = p.get("at_word")
    if at is None:
        return True, 1.0
    if at >= len(word_times):
        return True, 1.0
    t0 = word_times[at][0]
    if lt < t0:
        return False, 0
    return True, min(1.0, (lt - t0) / 0.12)


def render_scene_frame(item, lt, cast):
    sc = item["scene"]
    img = Image.new("RGB", (W, H))
    sprites.draw_background(img, sc.get("bg", {}), lt)

    for p in sc.get("props", []):
        if p.get("layer") != "back":
            continue
        _draw_prop_inst(img, p, lt, item["word_times"])

    for n, c in enumerate(sc.get("chars", [])):
        spec = dict(cast.get(c.get("id"), {}))
        spec.update(c.get("spec", {}))
        dx, dy = char_offset(c.get("anim", "idle"), lt, n + 1)
        blink = ((lt + n * 1.3) % 3.2) < 0.12
        x = int(c.get("x", W // 2)) + dx
        feet = int(c.get("y", FLOOR_Y + 24 + c.get("row", 0) * 10)) + dy
        cs = int(c.get("scale", 2))
        sprite = Image.new("RGBA", (CHAR_W, CHAR_H), (0, 0, 0, 0))
        top = sprites.draw_character(sprite, CHAR_W // 2, CHAR_H - 1, spec,
                                     c.get("expr", "neutral"), c.get("pose", "stand"),
                                     blink, c.get("flip", False), c.get("hold"), lt)
        if cs > 1:
            sprite = sprite.resize((CHAR_W * cs, CHAR_H * cs), Image.NEAREST)
        img.paste(sprite, (x - CHAR_W // 2 * cs, feet - (CHAR_H - 1) * cs), sprite)
        if c.get("bubble"):
            bob = int(math.sin(lt * 5) * 1.5)
            by = feet - (CHAR_H - 1 - top) * cs
            sprites.draw_prop(img, c["bubble"], x + 7 * cs, by - 6 * cs + bob, scale=cs)

    for p in sc.get("props", []):
        if p.get("layer") == "back":
            continue
        _draw_prop_inst(img, p, lt, item["word_times"])

    fx = sc.get("fx", [])
    if "zoom" in fx:
        z = 1 + min(0.18, lt * 0.12)
        cw, ch = int(W / z), int(H / z)
        x0, y0 = (W - cw) // 2, int((H - ch) * 0.55)
        img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.NEAREST)
    if "shake" in fx and lt < 0.5:
        off = int(3 * math.sin(lt * 70))
        shifted = Image.new("RGB", (W, H))
        shifted.paste(img, (off, 0))
        img = shifted
    if "flash" in fx and lt < 0.15:
        img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 1 - lt / 0.15)
    return img


def _draw_prop_inst(img, p, lt, word_times):
    vis, k = prop_visible(p, lt, word_times)
    if not vis:
        return
    x, y = p.get("x", W // 2), p.get("y", 80)
    if p.get("anim") == "float":
        y += int(2 * math.sin(lt * 4 + x))
    if p.get("anim") == "blink" and int(lt * 3) % 2:
        return
    scale = p.get("scale", 2)
    if k < 1 and scale > 1:
        scale -= 1  # smaller "pop" frame right before it lands
    sprites.draw_prop(img, p["type"], x, y, scale=scale, t=lt)


class Captioner:
    def __init__(self, style):
        self.cw, self.ch = OUT_W // CAP_SCALE, OUT_H // CAP_SCALE
        self.size = style.get("size", 28)
        self.font_path = style.get("font")
        self.fonts = {}
        self.y = style.get("y", 0.8)
        self.max_words = style.get("max_words", 3)
        self.color = sprites.hexc(style.get("color", "#ffffff"))
        self.hl = sprites.hexc(style.get("highlight", "#ffd93b"))

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = load_font(size, self.font_path)
        return self.fonts[size]

    def chunks(self, words):
        n = self.max_words
        return [list(range(i, min(i + n, len(words)))) for i in range(0, len(words), n)]

    def layer(self, words, word_times, lt, header=None):
        lay = Image.new("RGBA", (self.cw, self.ch), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.fontmode = "1"  # no antialiasing -> pixel font look
        if header:
            self._line(d, header.upper(), [], -1, 34, self.size - 6, (255, 255, 255))
        cur = None
        for i, (s, e) in enumerate(word_times):
            if s <= lt:
                cur = i
        if cur is not None and words:
            if lt > word_times[-1][1] + 0.6:
                return lay
            chunk = next(c for c in self.chunks(words) if cur in c)
            self._line(d, " ".join(words[j] for j in chunk), chunk, cur,
                       int(self.ch * self.y), self.size, self.color, words)
        return lay

    def _line(self, d, text, chunk, cur, y, size, color, words=None):
        f = self.font(size)
        while d.textlength(text, font=f) > self.cw - 16 and size > 10:
            size -= 2
            f = self.font(size)
        total = d.textlength(text, font=f)
        x = (self.cw - total) / 2
        if not chunk:
            d.text((x, y), text, font=f, fill=color, stroke_width=2, stroke_fill=(0, 0, 0))
            return
        space = d.textlength(" ", font=f)
        for j in chunk:
            w = words[j]
            col = self.hl if j == cur else color
            d.text((x, y), w, font=f, fill=col, stroke_width=2, stroke_fill=(0, 0, 0))
            x += d.textlength(w, font=f) + space


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def build_audio(plan, total, music, out_wav, tmp):
    inputs, filters, labels = [], [], []
    for item in plan:
        if item["audio"]:
            idx = len(inputs)
            inputs += ["-i", item["audio"]]
            ms = int(item["start"] * 1000)
            filters.append(f"[{idx}:a]adelay={ms}|{ms},aformat=channel_layouts=stereo[a{idx}]")
            labels.append(f"[a{idx}]")
    if music:
        idx = len(inputs)
        inputs += ["-stream_loop", "-1", "-i", music]
        vol = 0.12 if labels else 0.5
        filters.append(f"[{idx}:a]volume={vol},aformat=channel_layouts=stereo[a{idx}]")
        labels.append(f"[a{idx}]")
    if not labels:
        return None
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,"
                   f"atrim=0:{total:.3f}[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
                    ";".join(filters), "-map", "[out]", out_wav], check=True)
    return out_wav


def render(story, out, tts=False, music=None, preview=None):
    fps = story.get("fps", 30)
    cast = story.get("cast", {})
    cap = Captioner(story.get("captions", {}))
    tmp = tempfile.mkdtemp(prefix="pixelforge_")
    try:
        plan, total = plan_timeline(story, tts, tmp)
        print(f"{len(plan)} scènes, {total:.1f}s", file=sys.stderr)
        if preview is not None:
            item = plan[preview]
            lt = (item["end"] - item["start"]) * 0.6
            frame = compose(item, lt, cast, cap, story.get("header"))
            frame.save(out)
            return

        silent = os.path.join(tmp, "video.mp4")
        proc = subprocess.Popen([
            "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{OUT_W}x{OUT_H}", "-r", str(fps), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
        nframes = int(math.ceil(total * fps))
        k = 0
        for f in range(nframes):
            t = f / fps
            while k < len(plan) - 1 and t >= plan[k]["end"]:
                k += 1
            item = plan[k]
            frame = compose(item, t - item["start"], cast, cap, story.get("header"))
            proc.stdin.write(frame.tobytes())
            if f % (fps * 5) == 0:
                print(f"  {t:5.1f}s / {total:.1f}s", file=sys.stderr)
        proc.stdin.close()
        proc.wait()

        wav = build_audio(plan, total, music or story.get("music"), os.path.join(tmp, "a.wav"), tmp)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        if wav:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", silent, "-i", wav,
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out],
                           check=True)
        else:
            shutil.copy(silent, out)
        print(f"OK -> {out}", file=sys.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_last = {}


def compose(item, lt, cast, cap, header):
    # pixel layer animates at 12 fps for a retro feel; cache identical frames
    q = int(lt * 12) / 12
    key = (id(item), q)
    if _last.get("key") != key:
        base = render_scene_frame(item, q, cast).resize((OUT_W, OUT_H), Image.NEAREST)
        _last.update(key=key, base=base)
    frame = _last["base"].copy()
    lay = cap.layer(item["words"], item["word_times"], lt, header)
    lay = lay.resize((OUT_W, OUT_H), Image.NEAREST)
    frame.paste(lay, (0, 0), lay)
    return frame


def main():
    ap = argparse.ArgumentParser(description="Génère une vidéo pixel art à partir d'un script JSON.")
    ap.add_argument("story")
    ap.add_argument("-o", "--out", default="out/video.mp4")
    ap.add_argument("--tts", action="store_true", help="voix off auto avec edge-tts (internet requis)")
    ap.add_argument("--music", help="musique de fond (mp3/wav), en boucle, volume bas")
    ap.add_argument("--preview", type=int, help="n° de scène: sort juste une image PNG")
    a = ap.parse_args()
    with open(a.story, encoding="utf-8") as f:
        story = json.load(f)
    render(story, a.out, tts=a.tts, music=a.music, preview=a.preview)


if __name__ == "__main__":
    main()
