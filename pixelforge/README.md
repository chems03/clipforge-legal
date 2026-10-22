# PixelForge — vidéos d'histoires en pixel art

Génère des vidéos verticales 1080x1920 (TikTok / Shorts / Reels) au format
« histoire racontée » : plans courts, personnages pixel art, sous-titres mot par
mot avec le mot en cours surligné, voix off optionnelle.

Tout est dessiné par le code (aucune image externe), donc tes vidéos sont 100 % originales.

## Installation

```bash
pip install pillow numpy          # obligatoire
pip install edge-tts              # optionnel : voix off automatique (internet requis)
# + ffmpeg installé sur la machine
```

## Utilisation

```bash
# aperçu rapide d'une scène (PNG)
python3 -m pixelforge.render stories/maman_telephone.json --preview 3 -o apercu.png

# vidéo muette (tu poses ta propre voix ensuite dans CapCut, etc.)
python3 -m pixelforge.render stories/maman_telephone.json -o out/video.mp4

# vidéo avec voix off auto + musique de fond
python3 -m pixelforge.render stories/maman_telephone.json -o out/video.mp4 --tts --music musique.mp3
```

Avec `--tts`, la durée de chaque scène suit la voix et les sous-titres sont calés sur chaque mot.
Tu peux aussi mettre ta propre voix par scène avec `"audio": "voix/scene1.mp3"`.

## Écrire une histoire

Un fichier JSON = une vidéo. Voir `stories/maman_telephone.json`.

```json
{
  "header": "Titre affiché en haut",
  "voice": "fr-FR-HenriNeural",
  "captions": { "size": 28, "y": 0.8, "max_words": 2, "highlight": "#ffd93b" },
  "cast": {
    "moi": { "skin": "light", "hair": "short", "hair_color": "#4a2f1f", "shirt": "#3550a8", "acc": ["hoodie"] }
  },
  "scenes": [
    {
      "text": "La phrase dite pendant ce plan.",
      "bg": { "type": "room", "wall": "#a6dccd" },
      "chars": [ { "id": "moi", "x": 67, "expr": "happy", "pose": "wave", "anim": "bounce", "hold": "phone" } ],
      "props": [ { "type": "heart", "x": 67, "y": 70, "scale": 3, "at_word": 2 } ],
      "fx": ["flash", "zoom"]
    }
  ]
}
```

Les coordonnées sont sur une grille de 135 x 240 (centre = 67). Le sol est à y=172.

| Champ | Valeurs |
|---|---|
| `bg.type` | `intro` (carte titre : `"text": "LIGNE 1|LIGNE 2"`), `room`, `split` (gauche/droite pour les « X vs Y »), `burst` (rayons qui tournent), `plain`, `street`, `classroom`, `night` |
| `skin` | `light`, `medium`, `tan`, `dark` ou une couleur `#hex` |
| `hair` | `short`, `spiky`, `curly`, `afro`, `bun`, `long`, `ponytail`, `mohawk`, `bald` |
| `acc` | `hoodie`, `labcoat` (blouse, cartoon), `dress`, `glasses`, `mustache`, `beard`, `earrings`, `crown`, `cap`, `beanie`, `headphones`, `police` |
| `size` | `1` adulte/ado, `0.8` enfant |
| `expr` | `neutral`, `happy`, `laugh`, `sad`, `angry`, `shocked`, `worried`, `smirk`, `love` |
| `pose` | `stand`, `wave`, `arms_up` |
| `anim` (perso) | `idle`, `bounce`, `jump`, `shake`, `walk_in`, `walk_in_right`, `none` |
| `hold` / `bubble` | n'importe quel accessoire ci-dessous (dans la main / au-dessus de la tête) |
| `props.type` | `battery_full`, `battery_mid`, `battery_low`, `thermometer`, `eye_blue`, `eye_brown`, `eye_honey`, `photo`, `cake`, `paper`, `phone`, `gift`, `tv`, `lock`, `heart`, `x`, `check`, `question`, `exclam`, `controller`, `money`, `book`, `pizza`, `clock`, `star`, `zzz`, `bulb`, `trophy`, `sweat`, `anger` |
| `props.anim` | `float`, `blink` ; `at_word: n` le fait apparaître sur le n-ième mot |
| `fx` | `flash`, `zoom` (zoom lent), `shake` (secousse) |
| `ghost` (perso) | `true` = perso à moitié transparent |
| `props` avec texte | `{"type": "label", "text": "12/20", "color": "#e8414f"}` (étiquette), `report` (bulletin + note), `door` (porte + panneau), `brain`, `brain_alarm` — style cartoon |
| `title` (scène) | grand texte en haut de l'écran, ex. `"PREUVE N°1"` ; `title_color` pour sa couleur |

## Style « bonhommes ronds » et série

Ajoute `"style": "cartoon"` dans le JSON pour le style dessin animé (bonhommes
ronds, contours épais, rendu lisse). Sans ce champ, c'est le pixel art.

Les personnages récurrents de la série sont dans `stories/famille/personnages.json`
(avec leur bio). Un épisode y fait référence avec `"cast_file": "personnages.json"`
et utilise les ids `wassim`, `lina`, `yacine`, `papa`, `maman`, `nora`, `kader`, `zohra`.

Décors en plus pour le style cartoon : `kitchen`, `bedroom`, `salon`.

## Conseils pour que ça marche

- Plans courts : une phrase = une scène (2 à 4 s), on change de fond souvent.
- Une accroche forte dans la 1ʳᵉ seconde (scène `split` « X vs Y » + `flash`).
- Les persos réagissent en exagérant (`shocked`, `angry` + `shake`).
- Garde une distribution de personnages récurrents (`cast`) pour créer une série.
