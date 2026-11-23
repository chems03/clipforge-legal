"""Probabilités buteur (à tout moment, premier buteur, doublé) à partir des stats joueurs.

Aucune source gratuite et ouverte ne fournit les stats individuelles à jour : tu les saisis
(ou colles depuis FBref / Sofascore / L'Équipe) dans data/joueurs.csv ou dans l'appli.

Modèle :
  part_i   = part des buts (hors penalty) de l'équipe produite par le joueur quand il joue,
             estimée sur buts + xG (si fournis) et rétrécie vers une valeur moyenne (petits échantillons)
  μ_i      = λ_équipe_hors_penalty × part_i × minutes_prévues/90  (+ μ_penalty si tireur)
  P(≥1 but)  = 1 − e^(−μ_i)         P(≥2 buts) = 1 − e^(−μ)(1+μ)
  P(1er buteur) = μ_i / (λ_dom+λ_ext) × (1 − e^(−(λ_dom+λ_ext)))
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

PLAYERS_CSV = Path(__file__).resolve().parent.parent / "data" / "joueurs.csv"
COLUMNS = ["equipe", "joueur", "matchs", "minutes", "buts", "penaltys", "xg", "tireur_penalty",
           "minutes_prevues"]
PEN_GOALS_PER_MATCH = 0.085   # ≈ 0.11 penalty sifflé/équipe/match × 78 % de réussite
PRIOR_SHARE = 0.07            # part moyenne d'un joueur offensif "inconnu"
PRIOR_MATCHES = 4.0           # poids de l'a priori (en matchs complets)


def load_players() -> pd.DataFrame:
    if not PLAYERS_CSV.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(PLAYERS_CSV, comment="#")
    for c in COLUMNS:
        if c not in df:
            df[c] = np.nan
    return df[COLUMNS]


def save_players(df: pd.DataFrame) -> None:
    PLAYERS_CSV.parent.mkdir(exist_ok=True)
    df[COLUMNS].to_csv(PLAYERS_CSV, index=False)


def team_season_goals(results: pd.DataFrame, team: str, season: str | None = None) -> tuple[float, int]:
    """Buts et matchs de l'équipe en championnat sur la saison en cours."""
    r = results[results.comp != "CL"]
    if season is None and len(r):
        season = r["season"].dropna().max()
    r = r[r["season"] == season]
    h, a = r[r.home == team], r[r.away == team]
    return float(h.hg.sum() + a.ag.sum()), int(len(h) + len(a))


def scorer_probs(players: pd.DataFrame, team: str, lam_team: float, lam_total: float,
                 results: pd.DataFrame) -> pd.DataFrame:
    p = players[players.equipe == team].copy()
    if p.empty:
        return p
    for c in ["matchs", "minutes", "buts", "penaltys", "xg", "tireur_penalty", "minutes_prevues"]:
        p[c] = pd.to_numeric(p[c], errors="coerce")
    p["penaltys"] = p["penaltys"].fillna(0)
    p["buts"] = p["buts"].fillna(0)
    goals, n_matches = team_season_goals(results, team)
    team_pens = p["penaltys"].sum()
    team_np = max(goals - team_pens, 1.0)
    if n_matches == 0:  # équipe sans données de championnat : on se rabat sur les joueurs saisis
        team_np = max(p["buts"].sum() - team_pens, 1.0)
        n_matches = int(np.nanmax(p["matchs"])) if p["matchs"].notna().any() else 10
    team_np_rate = team_np / max(n_matches, 1)            # buts hors penalty / match

    np_goals = p["buts"] - p["penaltys"]
    np_xg = p["xg"] - 0.76 * p["penaltys"]                # xG fournis souvent penaltys inclus
    metric = np.where(p["xg"].notna(), 0.6 * np_xg.clip(lower=0) + 0.4 * np_goals, np_goals)
    mins = p["minutes"].fillna(p["matchs"].fillna(0) * 75)
    full = (mins / 90).clip(lower=0)
    # part "quand il est sur le terrain", rétrécie vers PRIOR_SHARE
    share = (metric + PRIOR_SHARE * team_np_rate * PRIOR_MATCHES) / (team_np_rate * (full + PRIOR_MATCHES))
    exp_min = p["minutes_prevues"].fillna((mins / p["matchs"].replace(0, np.nan)).clip(upper=90)).fillna(70)

    lam_np = max(lam_team - PEN_GOALS_PER_MATCH * lam_team / 1.35, 0.05)
    mu = lam_np * share * exp_min / 90
    mu += np.where(p["tireur_penalty"].fillna(0) > 0, PEN_GOALS_PER_MATCH * lam_team / 1.35 * exp_min / 90, 0)
    p["buts_attendus"] = mu
    p["P_buteur"] = 1 - np.exp(-mu)
    p["P_doublé"] = 1 - np.exp(-mu) * (1 + mu)
    p["P_1er_buteur"] = mu / lam_total * (1 - math.exp(-lam_total))
    p["cote_juste_buteur"] = 1 / p["P_buteur"]
    return p.sort_values("P_buteur", ascending=False)[
        ["joueur", "buts", "xg", "minutes", "minutes_prevues", "buts_attendus", "P_buteur", "P_doublé",
         "P_1er_buteur", "cote_juste_buteur"]]
