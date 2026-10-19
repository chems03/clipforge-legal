"""Ajoute une voix off et/ou une musique à une vidéo.

    python3 ajouter_son.py video.mp4 --voix ma_voix.mp3 --musique musique.mp3 -o finale.mp4

- --voix     : ton enregistrement (mp3, wav, m4a...), joué au début de la vidéo
- --musique  : musique de fond, jouée en boucle ; son volume baisse tout seul quand tu parles
- --volume-musique : 0.0 à 1.0 (défaut 0.25)
Il faut ffmpeg installé (https://ffmpeg.org).
"""
import argparse
import subprocess


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--voix")
    ap.add_argument("--musique")
    ap.add_argument("--volume-musique", type=float, default=0.25)
    ap.add_argument("-o", "--out", default="video_avec_son.mp4")
    a = ap.parse_args()
    if not a.voix and not a.musique:
        ap.error("donne au moins --voix ou --musique")

    cmd = ["ffmpeg", "-y", "-i", a.video]
    if a.voix:
        cmd += ["-i", a.voix]
    if a.musique:
        cmd += ["-stream_loop", "-1", "-i", a.musique]

    if a.voix and a.musique:
        # la musique baisse automatiquement quand la voix parle (sidechain)
        filt = (f"[1:a]aformat=channel_layouts=stereo,apad,asplit=2[v][sc];"
                f"[2:a]aformat=channel_layouts=stereo,volume={a.volume_musique}[m];"
                f"[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[md];"
                f"[v][md]amix=inputs=2:normalize=0[a]")
        cmd += ["-filter_complex", filt, "-map", "0:v", "-map", "[a]"]
    elif a.musique:
        cmd += ["-filter_complex", f"[1:a]volume={a.volume_musique}[a]", "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", "[1:a]apad[a]", "-map", "0:v", "-map", "[a]"]

    # la vidéo garde toujours sa durée (le son est complété/coupé pour coller)
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", a.out]
    subprocess.run(cmd, check=True)
    print("OK ->", a.out)


if __name__ == "__main__":
    main()
