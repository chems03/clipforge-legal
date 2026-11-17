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
    blocks, part = [], 0
    for chunk in re.split(r"\n(?=#{5,}\nPARTIE )", txt):
        if re.match(r"#{5,}\nPARTIE ", chunk):
            part += 1
        for n, st, t in pat.findall(chunk):
            blocks.append({"n": int(n), "part": part, "style": st.strip(), "text": t.strip()})
    return blocks


def group_parts(blocks):
    """One request per part: each block's tone becomes an inline [tag] before its text."""
    parts = {}
    for b in blocks:
        parts.setdefault(b["part"], []).append(b)
    return [{"n": p, "part": p, "style": bs[0]["style"],
             "text": " ".join(f"[{b['style']}] {b['text']}" for b in bs), "blocks": [b["n"] for b in bs]}
            for p, bs in sorted(parts.items())]


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


STRATEGIES = ["system", "say", "bracket", "none"]


def build_body(strategy, vcfg, style, text):
    gen = {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": vcfg}}
    body = {"generationConfig": gen}
    if strategy == "system":
        body["systemInstruction"] = {"parts": [{"text": f"Tu es un narrateur français. Ton de la lecture : {style}. "
                                                       "Lis uniquement le texte fourni, sans rien ajouter."}]}
        body["contents"] = [{"role": "user", "parts": [{"text": text}]}]
    elif strategy == "say":
        body["contents"] = [{"role": "user", "parts": [{"text": f"Say in French, in this tone ({style}): {text}"}]}]
    elif strategy == "bracket":
        body["contents"] = [{"role": "user", "parts": [{"text": f"[{style}] {text}"}]}]
    else:
        body["contents"] = [{"role": "user", "parts": [{"text": text}]}]
    return body


def synth(model, vcfg, style, text, strategy="system"):
    body = build_body(strategy, vcfg, style, text)
    for attempt in range(4):
        code, data = call("POST", f"{API}/models/{model}:generateContent", body)
        if code == 200:
            part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            rate = int(re.search(r"rate=(\d+)", part.get("mimeType", "")).group(1)) if "rate=" in part.get("mimeType", "") else 24000
            return base64.b64decode(part["data"]), rate, None
        msg = data.get("error", {}).get("message", "")
        if code == 429 and re.search(r"per ?day|PerDay|daily", msg, re.I):
            sys.exit(f"Quota journalier atteint : {msg}")
        if code in (429, 500, 503):
            print(f"  {code} : {msg[:300]}")
            m = re.search(r"retry in ([\d.]+)s", msg)
            wait = float(m.group(1)) + 1 if m else 15 * (attempt + 1)
            print(f"  limite atteinte ({code}), nouvelle tentative dans {wait:.0f} s")
            time.sleep(wait)
            continue
        return None, None, f"{code} : {msg}"
    return None, None, f"{code} : {msg}"


def choose_strategy(model, vcfg, blocks, out):
    """Pick the style strategy whose audio is not inflated by the instructions being read aloud."""
    probe = min(blocks, key=lambda b: len(b["text"]))
    print(f"Test des façons de donner le ton sur : « {probe['text']} » ({probe['style']})")
    durs = {}
    os.makedirs(os.path.join(out, "probe"), exist_ok=True)
    for st in STRATEGIES:
        audio, rate, err = synth(model, vcfg, probe["style"], probe["text"], st)
        if not audio:
            print(f"  {st} : échec {err}")
            continue
        durs[st] = len(audio) / 2 / rate
        write_wav(os.path.join(out, "probe", f"{st}.wav"), audio, rate)
        print(f"  {st} : {durs[st]:.1f} s")
    base = durs.get("none")
    ok = [st for st in ("system", "bracket", "say") if st in durs and (base is None or durs[st] <= base * 1.5 + 0.8)]
    choice = ok[0] if ok else "none"
    print(f"Façon retenue : {choice}")
    return choice


def pick(models, voice, style="neutre", text="Bonjour."):
    prefer = os.environ.get("GEMINI_TTS_MODEL")
    order = ([prefer] if prefer else []) + sorted(models, reverse=True)
    order = list(dict.fromkeys(order))
    for model in order:
        for vcfg in voice_configs(voice):
            audio, rate, err = synth(model, vcfg, style, text, "none")
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
    ap.add_argument("--per-block", action="store_true", help="une requête par bloc (consomme beaucoup de quota)")
    a = ap.parse_args()

    blocks = parse_blocks(a.script)
    if a.first:
        blocks = blocks[:a.first]
    if not a.per_block:
        blocks = group_parts(blocks)
    print(f"{len(blocks)} blocs à générer")
    os.makedirs(os.path.join(a.out, "blocks"), exist_ok=True)

    models = tts_models()
    chosen = pick(models, a.voice)
    if not chosen:
        print(f"La voix {a.voice} ne marche pas, essai avec {a.fallback_voice}")
        chosen = pick(models, a.fallback_voice)
    if not chosen:
        sys.exit("Aucune combinaison modèle/voix ne fonctionne.")
    model, vcfg, _, rate = chosen
    strategy = os.environ.get("TTS_STRATEGY") or ("bracket" if not a.per_block else choose_strategy(model, vcfg, blocks, a.out))
    if not a.per_block:
        strategy = "none"  # the [tone] tags are already inline in the text

    pcm_all, meta, t = b"", [], 0.0
    gap = b"\x00\x00" * int(rate * GAP)
    for i, b in enumerate(blocks):
        audio, r, err = synth(model, vcfg, b["style"], b["text"], strategy)
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
    json.dump({"model": model, "voice": vcfg, "strategy": strategy, "rate": rate, "blocks": meta},
              open(os.path.join(a.out, "blocks.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Narration : {t / 60:.1f} min")


if __name__ == "__main__":
    main()
