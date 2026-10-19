"""Cale les scènes d'une histoire sur une voix off unique (ex. MP3 ElevenLabs).

Sans transcription : on détecte les silences, puis on choisit ceux qui
séparent les scènes de façon à ce que la durée de chaque scène colle au
mieux à la longueur de son texte (programmation dynamique).

    python3 -m pixelforge.sync_voice stories/x.json voix.mp3 -o stories/x_voix.json
"""
import argparse
import json
import math
import re
import subprocess

from .render import audio_duration, split_words


def detect_silences(path, noise_db=-38, min_len=0.2):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                          f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", out)]
    return list(zip(starts, ends))


def weight(text):
    """Rough spoken length: vowels groups ~ syllables, plus punctuation pauses."""
    t = text.lower()
    syl = len(re.findall(r"[aeiouyàâéèêëîïôöùûüœ]+", t))
    return syl + 1.5 * len(re.findall(r"[.!?…]", t)) + 0.7 * t.count(",")


def align(texts, sil, total):
    """Pick len(texts)-1 silences as scene boundaries. Returns scene (start, end) list."""
    n, m = len(texts), len(sil)
    if m < n - 1:
        raise SystemExit(f"{m} pauses trouvées pour {n} scènes : il faut plus de pauses dans la voix.")
    speech_start = sil[0][1] if sil and sil[0][0] < 0.05 else 0.0
    w = [weight(t) for t in texts]
    rate = (total - speech_start) / sum(w)
    # candidate boundaries: middle of each silence
    cand = [(s + e) / 2 for s, e in sil if s > speech_start + 0.3 and e < total - 0.1]
    gap = {(s + e) / 2: e - s for s, e in sil}
    pts = [speech_start] + cand
    m = len(cand)
    INF = float("inf")
    # dp[i][j]: best cost with scene i ending at candidate j (pts index j)
    dp = [[INF] * (m + 1) for _ in range(n)]
    back = [[-1] * (m + 1) for _ in range(n)]

    def cost(i, a, b):
        d = b - a
        if d <= 0.3:
            return INF
        return math.log(d / (w[i] * rate)) ** 2

    for j in range(1, m + 1):
        dp[0][j] = cost(0, pts[0], pts[j]) - 0.6 * gap[pts[j]]
    for i in range(1, n - 1):
        for j in range(i + 1, m + 1):
            for k in range(i, j):
                c = dp[i - 1][k] + cost(i, pts[k], pts[j]) - 0.6 * gap[pts[j]]
                if c < dp[i][j]:
                    dp[i][j], back[i][j] = c, k
    best, bj = INF, -1
    for j in range(n - 1, m + 1):
        c = dp[n - 2][j] + cost(n - 1, pts[j], total)
        if c < best:
            best, bj = c, j
    idx = [bj]
    for i in range(n - 2, 0, -1):
        idx.append(back[i][idx[-1]])
    bounds = [pts[j] for j in reversed(idx)]
    edges = [0.0] + bounds + [total]
    return [(edges[i], edges[i + 1]) for i in range(n)]


def word_times(words, start, end, sil):
    """Spread words over the speech chunks of a scene (skipping inner pauses)."""
    chunks, t = [], start
    for s, e in sil:
        if start < s and e < end:
            chunks.append((t, s))
            t = e
    chunks.append((t, end))
    chunks = [(a, b) for a, b in chunks if b - a > 0.05]
    lens = [len(x) + 1 for x in words]
    tot_speech = sum(b - a for a, b in chunks)
    tot_len = sum(lens)
    out, ci, pos = [], 0, chunks[0][0]
    for L in lens:
        dur = tot_speech * L / tot_len
        while ci < len(chunks) - 1 and pos + 0.02 >= chunks[ci][1]:
            ci += 1
            pos = max(pos, chunks[ci][0])
        out.append([round(pos - start, 3), round(pos - start + dur, 3)])
        pos += dur
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story")
    ap.add_argument("voice")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--tail", type=float, default=0.8, help="secondes ajoutées à la fin")
    ap.add_argument("--fix", nargs="*", default=[], metavar="N=T",
                    help="corrige à la main le début de la scène N (à partir de 0) à T secondes, ex. 5=15.24")
    a = ap.parse_args()
    story = json.load(open(a.story, encoding="utf-8"))
    total = audio_duration(a.voice)
    sil = detect_silences(a.voice)
    texts = [sc.get("text", "") for sc in story["scenes"]]
    spans = align(texts, sil, total)
    if a.fix:
        edges = [s for s, _ in spans] + [total]
        for f in a.fix:
            k, v = f.split("=")
            edges[int(k)] = float(v)
        spans = list(zip(edges[:-1], edges[1:]))
    for sc, (s, e) in zip(story["scenes"], spans):
        if sc is story["scenes"][-1]:
            e += a.tail
        sc["duration"] = round(e - s, 3)
        sc["word_times"] = word_times(split_words(sc["text"]), s, min(e, total), sil)
        print(f"{s:6.2f} -> {e:6.2f}  {sc['text']}")
    story["voiceover"] = a.voice
    json.dump(story, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("OK ->", a.out)


if __name__ == "__main__":
    main()
