# ⚽ Pronos Foot

Application de pronostics football : 1X2, score exact, buts, BTTS, handicaps, mi-temps/fin de match,
buteurs, détection de value bets et ticket combiné, pour la **Ligue 1, la Premier League, la Liga, la
Serie A, la Bundesliga, la Ligue des champions** (et Portugal, Pays-Bas, Belgique, Turquie, Écosse,
2es divisions).

## Installation

```bash
cd paris-foot
pip install -r requirements.txt
streamlit run app.py        # interface web → http://localhost:8501
```

Ligne de commande :

```bash
python cli.py match "Paris SG" "Marseille" --comp F1
python cli.py match Arsenal "Paris SG" --comp CL --cotes 2.10 3.50 3.60 --cote-o25 1.85 2.00
python cli.py prochains --ligues F1 E0
python cli.py classement --ligue F1
python cli.py backtest
```

Le premier lancement télécharge environ 18 000 matchs (environ 30 s). Les données se mettent à jour toutes seules
(cache de 6 h), ou avec le bouton « Mettre à jour ».

## Données (gratuites, sans clé)

| Source | Contenu |
|---|---|
| football-data.co.uk | Résultats de 15 championnats sur 4 saisons : tirs, tirs cadrés, **xG** (saison en cours), cotes d'ouverture, de clôture et meilleures cotes, calendrier à venir avec cotes |
| openfootball (GitHub) | Résultats de Ligue des champions : c'est ce qui permet de comparer les championnats entre eux |
| `data/joueurs.csv` | Stats des buteurs, **à remplir toi-même** (aucune source ouverte fiable) |
| `data/resultats_manuels.csv` | Résultats à ajouter à la main (ex. C1 2026-27 tant qu'elle n'est pas publiée) |

## Le modèle

1. **Dixon-Coles hiérarchique multi-championnats.** Chaque équipe a une attaque et une défense.
   Chaque championnat a un niveau, estimé grâce aux matchs de C1 et aux montées et descentes, ainsi
   que son propre avantage du terrain et son propre niveau de buts.
2. **Cible = 65 % buts réels + 35 % xG.** Les xG sont reconstitués à partir des tirs quand ils
   manquent. Ça lisse la chance (poteaux, penaltys).
3. **Pondération temporelle** avec une demi-vie d'environ 9 mois : la forme récente compte davantage.
4. **Correction Dixon-Coles** des petits scores (0-0, 1-0, 0-1, 1-1), puis un **recalibrage** appris
   par backtest.
5. **Mélange avec le marché.** Quand des cotes sont connues, on retrouve les buts attendus implicites
   du marché, puis on retient 20 % modèle + 80 % marché. Tous les marchés (score exact, MT/FT…)
   restent cohérents entre eux.
6. **Buteurs.** La part des buts de l'équipe produite par le joueur (buts + xG, rétrécie sur petits
   échantillons) est multipliée par les buts attendus de l'équipe et par les minutes prévues, et
   les penaltys sont ajoutés pour le tireur désigné.

## Ce que dit le backtest (honnêtement)

Le backtest porte sur 2 297 matchs des 5 grands championnats depuis août 2025. Le modèle est
ré-entraîné toutes les 3 semaines avec uniquement le passé.

| | Log-loss 1X2 |
|---|---|
| Modèle seul | 0,985 |
| Cotes des bookmakers (ouverture) | 0,970 |
| Cotes des bookmakers (clôture) | 0,969 |

* Le **marché reste plus précis** que le modèle : c'est le cas de tous les modèles publics.
  **Parier uniquement sur le modèle perd environ 6 à 9 %** en simulation.
* L'intérêt de l'appli :
  1. obtenir des probabilités cohérentes sur **tous** les marchés, là où les bookmakers prennent
     des marges énormes (score exact, buteur, MT/FT) ;
  2. repérer les écarts entre une cote proposée et la probabilité juste (**value**) ;
  3. **comparer les bookmakers** et toujours prendre la meilleure cote.
* La stratégie 20 % modèle / 80 % marché avec une value d'au moins 5 % sur la meilleure cote a été
  positive sur le backtest, mais sur **136 paris seulement**. C'est statistiquement très incertain.
* La calibration est bonne : quand le modèle annonce X %, l'événement arrive environ X % du temps
  (voir l'onglet « Fiabilité »).

Les paris restent un jeu d'argent : mise de faibles montants (Kelly/4 maximum) et uniquement ce que
tu peux perdre. Aide : Joueurs Info Service, 09 74 75 13 13.
