"""Build a long-form video from a script.json: voice, slides, edit, thumbnail.

Usage: python pipeline/make_video.py videos/kodak/script.json out/
Writes out/video.mp4, out/thumbnail.png, out/subtitles.srt, out/description.txt
"""
import asyncio
import json
import os
import subprocess
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
PAD = 1.06  # slides are rendered slightly larger so the camera can drift
BG, FG, MUTED, ACCENT = (14, 14, 16), (240, 240, 240), (150, 150, 158), (245, 183, 0)
FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def font(size, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=fnt) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def centered(draw, lines, fnt, y, fill, gap=1.25):
    lh = int(fnt.size * gap)
    for i, line in enumerate(lines):
        x = (W - draw.textlength(line, font=fnt)) / 2
        draw.text((x, y + i * lh), line, font=fnt, fill=fill)
    return y + len(lines) * lh


def block_height(lines, fnt, gap=1.25):
    return len(lines) * int(fnt.size * gap)


def slide(visual, path):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    t = visual["type"]
    maxw = W - 320
    if t == "title":
        k, f = font(40, False), font(104)
        lines = wrap(d, visual["text"], f, maxw)
        total = 70 + block_height(lines, f)
        y = (H - total) / 2
        centered(d, [visual.get("kicker", "").upper()], k, y, ACCENT)
        y = centered(d, lines, f, y + 70, FG)
        d.rectangle([(W / 2 - 60, y + 30), (W / 2 + 60, y + 38)], fill=ACCENT)
    elif t == "stat":
        fv, fl, fs = font(190), font(52, False), font(32, False)
        ll = wrap(d, visual["label"], fl, maxw)
        sl = wrap(d, visual.get("source", ""), fs, maxw) if visual.get("source") else []
        total = 230 + block_height(ll, fl) + (40 + block_height(sl, fs) if sl else 0)
        y = (H - total) / 2
        centered(d, [visual["value"]], fv, y, ACCENT)
        y = centered(d, ll, fl, y + 230, FG)
        if sl:
            centered(d, sl, fs, y + 40, MUTED)
    elif t == "quote":
        fq, fa = font(68), font(36, False)
        ql = wrap(d, f"« {visual['text']} »", fq, maxw)
        total = block_height(ql, fq) + 60 + 40
        y = (H - total) / 2
        y = centered(d, ql, fq, y, FG)
        centered(d, [f"— {visual['author']}"], fa, y + 40, MUTED)
    elif t == "text":
        fh, fl = font(44, False), font(72)
        lines = []
        for line in visual["lines"]:
            lines += wrap(d, line, fl, maxw)
        total = 90 + block_height(lines, fl, 1.4)
        y = (H - total) / 2
        centered(d, [visual["heading"].upper()], fh, y, ACCENT)
        centered(d, lines, fl, y + 90, FG, 1.4)
    else:
        raise ValueError(f"type de visuel inconnu : {t}")
    img.resize((int(W * PAD), int(H * PAD)), Image.LANCZOS).save(path)


def thumbnail(cfg, path):
    img = Image.new("RGB", (1280, 720), BG)
    d = ImageDraw.Draw(img)
    big, small = font(150), font(56)
    text = cfg.get("text", "ILS L'AVAIENT")
    x = (1280 - d.textlength(text, font=big)) / 2
    d.text((x, 200), text, font=big, fill=ACCENT)
    sub = cfg.get("subtitle", "")
    x = (1280 - d.textlength(sub, font=small)) / 2
    d.text((x, 420), sub, font=small, fill=FG)
    d.rectangle([(0, 690), (1280, 720)], fill=ACCENT)
    img.save(path)


async def tts(text, voice, mp3):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate="+4%")
    cues = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                cues.append((chunk["offset"] / 1e7, (chunk["offset"] + chunk["duration"]) / 1e7, chunk["text"]))
    return cues


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", path])
    return float(out)


def ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def chapter_ts(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02}"


def main(script_path, out_dir):
    cfg = json.load(open(script_path, encoding="utf-8"))
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)
    tail = 0.6  # silence after each scene
    clips, srt, chapters, t0 = [], [], [], 0.0
    for i, sc in enumerate(cfg["scenes"]):
        png, mp3, mp4 = (os.path.join(work, f"{i:03}.{e}") for e in ("png", "mp3", "mp4"))
        slide(sc["visual"], png)
        cues = asyncio.run(tts(sc["narration"], cfg.get("voice", "fr-FR-HenriNeural"), mp3))
        dur = duration(mp3) + tail
        if i == 0 or sc["visual"]["type"] == "title" and sc["visual"].get("kicker", "").startswith("Partie"):
            chapters.append(f"{chapter_ts(t0)} {sc['visual']['text']}")
        for a, b, txt in cues:
            srt.append((t0 + a, t0 + b, txt))
        dx, dy = int(W * (PAD - 1)), int(H * (PAD - 1))
        direction = 1 if i % 2 == 0 else -1
        x_expr = f"{dx}*t/{dur:.3f}" if direction == 1 else f"{dx}*(1-t/{dur:.3f})"
        vf = (f"crop={W}:{H}:x='{x_expr}':y='{dy // 2}',"
              f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur - 0.4:.3f}:d=0.4,format=yuv420p")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", png,
                        "-i", mp3, "-af", f"apad=pad_dur={tail}", "-vf", vf, "-t", f"{dur:.3f}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", mp4], check=True)
        clips.append(mp4)
        t0 += dur
        print(f"Scène {i + 1}/{len(cfg['scenes'])} : {dur:.1f} s")

    lst = os.path.join(work, "list.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(c)}'\n" for c in clips)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", "-movflags", "+faststart", os.path.join(out_dir, "video.mp4")], check=True)

    with open(os.path.join(out_dir, "subtitles.srt"), "w", encoding="utf-8") as f:
        for n, (a, b, txt) in enumerate(srt, 1):
            f.write(f"{n}\n{ts(a)} --> {ts(b)}\n{textwrap.fill(txt, 42)}\n\n")
    desc = cfg["description"].replace("{CHAPTERS}", "\n".join(chapters))
    with open(os.path.join(out_dir, "description.txt"), "w", encoding="utf-8") as f:
        f.write(desc)
    thumbnail(cfg.get("thumbnail", {}), os.path.join(out_dir, "thumbnail.png"))
    print(f"Vidéo terminée : {t0 / 60:.1f} min")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
