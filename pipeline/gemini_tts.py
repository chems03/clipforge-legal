"""Generate narration with Gemini TTS from a block-by-block script.

Script format (videos/<name>/voix_gemini_expressif.txt):
  [Bloc N] TON : <style>
  TEXTE :
  <text with optional <short pause> / <long pause> tags>

Usage: python pipeline/gemini_tts.py SCRIPT OUT_DIR [--first N] [--voice Riko]
Needs GEMINI_API_KEY. Writes OUT_DIR/blocks/NNN.wav, OUT_DIR/narration.wav,
OUT_DIR/blocks.json (text, style, start, end of each block).
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import wave

API = "https://generativelanguage.googleapis.com/v1beta"
GAP = 0.25  # seconds of silence between blocks


def parse_blocks(path):
    txt = open(path, encoding="utf-8").read()
    pat = re.compile(r"\[Bloc (\d+)\] TON : (.+?)\nTEXTE :\n(.+?)(?=\n\s*\n|\Z)", re.S)
    return [{"n": int(n), "style": s.strip(), "text": t.strip()} for n, s, t in pat.findall(txt)]


def call(method, url, body=None):
    key = os.environ["GEMINI_API_KEY"].strip()
    req = urllib.request.Request(url, method=method, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return 200, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def tts_models():
    code, data = call("GET", f"{API}/models?pageSize=1000")
    if code != 200:
        sys.exit(f"Impossible de lister les modèles ({code}) : {data.get('error', {}).get('message')}")
    names = [m["name"].split("/", 1)[1] for m in data.get("models", []) if "tts" in m["name"].lower()]
    print("Modèles TTS disponibles :", ", ".join(names) or "aucun")
    return names


def voice_configs(voice):
    return [{"voice": voice}, {"prebuiltVoiceConfig": {"voiceName": voice}}]


def synth(model, vcfg, style, text):
    prompt = f"Lis ce texte en français, avec ce ton : {style}.\n\n{text}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": vcfg}},
    }
    for attempt in range(6):
        code, data = call("POST", f"{API}/models/{model}:generateContent", body)
        if code == 200:
            part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            rate = int(re.search(r"rate=(\d+)", part.get("mimeType", "")).group(1)) if "rate=" in part.get("mimeType", "") else 24000
            return base64.b64decode(part["data"]), rate, None
        msg = data.get("error", {}).get("message", "")
        if code in (429, 500, 503):
            m = re.search(r"retry in ([\d.]+)s", msg)
            wait = float(m.group(1)) + 1 if m else 15 * (attempt + 1)
            print(f"  limite atteinte ({code}), nouvelle tentative dans {wait:.0f} s")
            time.sleep(wait)
            continue
        return None, None, f"{code} : {msg}"
    return None, None, f"{code} : {msg}"


def pick(models, voice, style, text):
    prefer = os.environ.get("GEMINI_TTS_MODEL")
    order = ([prefer] if prefer else []) + sorted(models, reverse=True)
    for model in order:
        for vcfg in voice_configs(voice):
            audio, rate, err = synth(model, vcfg, style, text)
            if audio:
                print(f"OK : modèle {model}, voix {vcfg}")
                return model, vcfg, audio, rate
            print(f"Échec {model} {vcfg} → {err}")
    return None


def write_wav(path, pcm, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--voice", default="Riko")
    ap.add_argument("--fallback-voice", default="Charon")
    a = ap.parse_args()

    blocks = parse_blocks(a.script)
    if a.first:
        blocks = blocks[:a.first]
    print(f"{len(blocks)} blocs à générer")
    os.makedirs(os.path.join(a.out, "blocks"), exist_ok=True)

    models = tts_models()
    chosen = pick(models, a.voice, blocks[0]["style"], blocks[0]["text"])
    if not chosen:
        print(f"La voix {a.voice} ne marche pas, essai avec {a.fallback_voice}")
        chosen = pick(models, a.fallback_voice, blocks[0]["style"], blocks[0]["text"])
    if not chosen:
        sys.exit("Aucune combinaison modèle/voix ne fonctionne.")
    model, vcfg, audio, rate = chosen

    pcm_all, meta, t = b"", [], 0.0
    gap = b"\x00\x00" * int(rate * GAP)
    for i, b in enumerate(blocks):
        if i > 0:
            audio, r, err = synth(model, vcfg, b["style"], b["text"])
            if not audio:
                sys.exit(f"Bloc {b['n']} : échec {err}")
            rate = r
        write_wav(os.path.join(a.out, "blocks", f"{b['n']:03}.wav"), audio, rate)
        dur = len(audio) / 2 / rate
        meta.append({**b, "start": round(t, 3), "end": round(t + dur, 3)})
        pcm_all += audio + gap
        t += dur + GAP
        print(f"Bloc {b['n']} : {dur:.1f} s")
    write_wav(os.path.join(a.out, "narration.wav"), pcm_all, rate)
    json.dump({"model": model, "voice": vcfg, "rate": rate, "blocks": meta},
              open(os.path.join(a.out, "blocks.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Narration : {t / 60:.1f} min")


if __name__ == "__main__":
    main()
