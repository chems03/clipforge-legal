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

from . import cartoon, sprites
from .sprites import W, H, U

# Frames (scene + captions) are composed at 270x480 and upscaled by ffmpeg
# with nearest-neighbour: x8 = 2160x3840 (4K), x4 = 1080x1920.
SCALE = 8
PIXEL = True
RESAMPLE = Image.NEAREST


def use_style(name):
    """Switch drawing module: "pixel" (sprites) or "cartoon" (round people)."""
    global sprites, W, H, U, PIXEL, RESAMPLE
    from . import sprites as pixel_mod
    sprites = cartoon if name == "cartoon" else pixel_mod
    W, H, U = sprites.W, sprites.H, sprites.U
    PIXEL = name != "cartoon"
    RESAMPLE = Image.NEAREST if PIXEL else Image.BILINEAR
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
        if sc.get("word_times") and len(sc["word_times"]) == len(words):
            wt = [tuple(x) for x in sc["word_times"]]
        elif marks and len(marks) == len(words):
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
        return 0, -int(10 * U * math.sin(ph * math.pi))
    if anim == "bounce":
        return 0, -abs(int(3 * U * math.sin(lt * 9 + seed)))
    if anim == "shake":
        return int(2 * U * math.sin(lt * 50 + seed)), 0
    if anim == "walk_in":
        p = min(1.0, lt / 0.6)
        return int((1 - p) * -90 * U), -(int(lt * 8) % 2) * U
    if anim == "walk_in_right":
        p = min(1.0, lt / 0.6)
        return int((1 - p) * 90 * U), -(int(lt * 8) % 2) * U
    if anim == "none":
        return 0, 0
    return 0, -bob * U


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


def active_scene(item, lt):
    """Scene dict at local time lt, applying "cuts" (visual changes on a given word).

    A cut overrides bg/chars/props/title of the scene from its `at_word` on, and
    gets its own fx. Returns (scene, start time of the active cut)."""
    sc, ts = item["scene"], 0.0
    wt = item["word_times"]
    for cut in sc.get("cuts", []):
        at = cut.get("at_word", 0)
        if at < len(wt) and lt >= wt[at][0]:
            merged = {k: v for k, v in item["scene"].items() if k not in ("cuts", "fx")}
            merged.update(cut)
            sc, ts = merged, wt[at][0]
    return sc, ts


def render_scene_frame(item, lt, cast):
    """Scene image at canvas size. Story coordinates are in 135x240 units."""
    sc, ts = active_scene(item, lt)
    at = lt          # props appear on words: absolute scene time
    lt = lt - ts     # animations and fx restart on each cut
    img = sprites.background(sc.get("bg", {}), lt)

    for p in sc.get("props", []):
        if p.get("layer") == "back":
            _draw_prop_inst(img, p, lt, item["word_times"], at)

    chars = []
    for n, c in enumerate(sc.get("chars", [])):
        dx, dy = char_offset(c.get("anim", "idle"), lt, n + 1)
        x = int(c.get("x", 67) * U) + dx
        feet = int((c.get("y", 196) + c.get("row", 0) * 10) * U)
        chars.append((n, c, x, feet, dy))
    for n, c, x, feet, dy in chars:
        if not c.get("ghost"):
            img = sprites.ground_shadow(img, x, feet, 36 * U)
    for n, c, x, feet, dy in chars:
        spec = dict(cast.get(c.get("id"), {}))
        spec.update(c.get("spec", {}))
        blink = ((lt + n * 1.3) % 3.2) < 0.12
        sprite, top = sprites.draw_character(spec, c.get("expr", "neutral"), c.get("pose", "stand"),
                                             blink, c.get("flip", False), c.get("hold"), lt)
        if c.get("ghost"):  # half-transparent: the forgotten one
            sprite.putalpha(sprite.getchannel("A").point(lambda v: v * 45 // 100))
        ox, oy = x - sprites.SCX, feet + dy - sprites.SFEET
        img.paste(sprite, (ox, oy), sprite)
        if c.get("bubble"):
            bob = int(math.sin(lt * 5) * 3)
            side = -1 if c.get("flip") else 1
            sprites.draw_prop(img, c["bubble"], x + side * 15 * U, oy + top - 15 * U + bob, size=20 * U, t=lt)

    for p in sc.get("props", []):
        if p.get("layer") != "back":
            _draw_prop_inst(img, p, lt, item["word_times"], at)

    img = img.convert("RGB")
    fx = sc.get("fx", [])
    if "zoom" in fx:
        z = 1 + min(0.18, lt * 0.12)
        cw, ch = int(W / z), int(H / z)
        x0, y0 = (W - cw) // 2, int((H - ch) * 0.55)
        img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), RESAMPLE)
    if "shake" in fx and lt < 0.5:
        off = int(3 * U * math.sin(lt * 70))
        shifted = Image.new("RGB", (W, H))
        shifted.paste(img, (off, 0))
        img = shifted
    if "flash" in fx and lt < 0.15:
        img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 1 - lt / 0.15)
    return img


def _draw_prop_inst(img, p, lt, word_times, at=None):
    vis, k = prop_visible(p, lt if at is None else at, word_times)
    if not vis:
        return
    x, y = p.get("x", 67) * U, p.get("y", 80) * U
    if p.get("anim") == "float":
        y += int(2 * U * math.sin(lt * 4 + x))
    if p.get("anim") == "blink" and int(lt * 3) % 2:
        return
    size = 16 * U * p.get("scale", 2)
    if k < 1:
        size *= 0.7  # smaller "pop" frame right before it lands
    kind = p["type"]
    if "text" in p:  # e.g. {"type": "label", "text": "12/20", "color": "#ff5a5a"}
        kind += "|" + p["text"] + ("|" + p["color"] if "color" in p else "")
    sprites.draw_prop(img, kind, x, y, size=size, t=lt)


class Captioner:
    def __init__(self, style):
        self.cw, self.ch = W, H
        self.k = W / 270  # story sizes are given for a 270 px wide canvas
        self.size = int(style.get("size", 28) * self.k)
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

    @staticmethod
    def state(words, word_times, lt):
        """Index of the word being said, or None when no caption is shown."""
        cur = None
        for i, (s, e) in enumerate(word_times):
            if s <= lt:
                cur = i
        if cur is None or not words or lt > word_times[-1][1] + 0.6:
            return None
        return cur

    def draw(self, img, words, cur, header=None, title=None, title_color=None):
        d = ImageDraw.Draw(img)
        if PIXEL:
            d.fontmode = "1"  # no antialiasing -> pixel font look
        k = self.k
        if header:
            self._line(d, header.upper(), [], -1, int(34 * k), self.size - int(6 * k), (255, 255, 255))
        if title:  # big title card text, e.g. "PREUVE N°1"
            col = sprites.hexc(title_color) if title_color else self.hl
            self._line(d, title.upper(), [], -1, int(self.ch * 0.17), self.size + int(16 * k), col)
        if cur is not None:
            chunk = next(c for c in self.chunks(words) if cur in c)
            self._line(d, " ".join(words[j] for j in chunk), chunk, cur,
                       int(self.ch * self.y), self.size, self.color, words)

    def _line(self, d, text, chunk, cur, y, size, color, words=None):
        f = self.font(size)
        while d.textlength(text, font=f) > self.cw - 16 * self.k and size > 10:
            size -= 2
            f = self.font(size)
        total = d.textlength(text, font=f)
        x = (self.cw - total) / 2
        if not chunk:
            d.text((x, y), text, font=f, fill=color, stroke_width=int(2 * self.k), stroke_fill=(0, 0, 0))
            return
        space = d.textlength(" ", font=f)
        for j in chunk:
            w = words[j]
            col = self.hl if j == cur else color
            d.text((x, y), w, font=f, fill=col, stroke_width=int(2 * self.k), stroke_fill=(0, 0, 0))
            x += d.textlength(w, font=f) + space


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def build_audio(plan, total, music, out_wav, tmp, voiceover=None):
    inputs, filters, labels = [], [], []
    for item in plan:
        if item["audio"]:
            idx = len(inputs)
            inputs += ["-i", item["audio"]]
            ms = int(item["start"] * 1000)
            filters.append(f"[{idx}:a]adelay={ms}|{ms},aformat=channel_layouts=stereo[a{idx}]")
            labels.append(f"[a{idx}]")
    if voiceover:
        idx = len(inputs)
        inputs += ["-i", voiceover]
        filters.append(f"[{idx}:a]aformat=channel_layouts=stereo[a{idx}]")
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
                   f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100,apad,"
                   f"atrim=0:{total:.3f}[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
                    ";".join(filters), "-map", "[out]", out_wav], check=True)
    return out_wav


def render(story, out, tts=False, music=None, preview=None, scale=SCALE):
    use_style(story.get("style", "pixel"))
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
            frame.resize((1080, 1920), RESAMPLE).save(out)
            return

        silent = os.path.join(tmp, "video.mp4")
        proc = subprocess.Popen([
            "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
            "-vf", f"scale={270 * scale}:{480 * scale}:flags={'neighbor' if PIXEL else 'lanczos'}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-tune", "animation",
            "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
        nframes = int(math.ceil(total * fps))
        k = 0
        for f in range(nframes):
            t = f / fps
            while k < len(plan) - 1 and t >= plan[k]["end"]:
                k += 1
            item = plan[k]
            frame = compose(item, t - item["start"], cast, cap, story.get("header"))
            proc.stdin.write(frame.tobytes() if not isinstance(frame, bytes) else frame)
            if f % (fps * 5) == 0:
                print(f"  {t:5.1f}s / {total:.1f}s", file=sys.stderr)
        proc.stdin.close()
        proc.wait()

        wav = build_audio(plan, total, music or story.get("music"), os.path.join(tmp, "a.wav"), tmp,
                          story.get("voiceover"))
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        if wav:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", silent, "-i", wav,
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                            "-movflags", "+faststart", out],
                           check=True)
        else:
            shutil.copy(silent, out)
        print(f"OK -> {out}", file=sys.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_last = {}


def compose(item, lt, cast, cap, header):
    """Final frame (canvas size). The scene layer animates at 12 fps; frames are cached."""
    q = int(lt * 12) / 12
    key = (id(item), q)
    if _last.get("key") != key:
        _last.update(key=key, base=render_scene_frame(item, q, cast), cap=None)
    cur = cap.state(item["words"], item["word_times"], lt)
    if _last.get("cap") != (cur,) or "frame" not in _last:
        frame = _last["base"].copy()
        sc, _ = active_scene(item, lt)
        if sc.get("bg", {}).get("type") == "intro":
            header = None  # the intro card is the header
        cap.draw(frame, item["words"], cur, header, sc.get("title"), sc.get("title_color"))
        _last.update(cap=(cur,), frame=frame)
    return _last["frame"]


def main():
    ap = argparse.ArgumentParser(description="Génère une vidéo pixel art à partir d'un script JSON.")
    ap.add_argument("story")
    ap.add_argument("-o", "--out", default="out/video.mp4")
    ap.add_argument("--tts", action="store_true", help="voix off auto avec edge-tts (internet requis)")
    ap.add_argument("--music", help="musique de fond (mp3/wav), en boucle, volume bas")
    ap.add_argument("--preview", type=int, help="n° de scène: sort juste une image PNG")
    ap.add_argument("--res", choices=["4k", "1080"], default="4k", help="résolution de sortie")
    a = ap.parse_args()
    with open(a.story, encoding="utf-8") as f:
        story = json.load(f)
    if story.get("cast_file"):  # shared recurring characters
        with open(os.path.join(os.path.dirname(a.story), story["cast_file"]), encoding="utf-8") as f:
            story["cast"] = {**json.load(f)["cast"], **story.get("cast", {})}
    render(story, a.out, tts=a.tts, music=a.music, preview=a.preview,
           scale=8 if a.res == "4k" else 4)


if __name__ == "__main__":
    main()
