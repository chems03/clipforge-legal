"""Sélections nationales : modèle dédié (même moteur Dixon-Coles, une seule "poule" mondiale)
et probabilités buteurs calculées automatiquement à partir de l'historique des buteurs."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .model import Config, Model, fit

# Réglages validés par backtest walk-forward sur les matchs internationaux 2024-2026
# (log-loss 1X2 : 0,837 sur 2 213 matchs depuis nov. 2024)
NAT_CONFIG = Config(xi=0.0006, w_goals=1.0, sigma_team=1.5, sigma_league=0.12, cl_weight=1.0, stretch=1.1)
NAT_COMP_WEIGHTS: dict = {}


def fit_national(df: pd.DataFrame, ref_date=None, config: Config | None = None) -> Model:
    return fit(df, ref_date=ref_date, config=config or NAT_CONFIG, single_pool="NAT",
               comp_weights=NAT_COMP_WEIGHTS)


def active_teams(df: pd.DataFrame, years: float = 3) -> list[str]:
    r = df[df.date >= df.date.max() - pd.Timedelta(days=int(365 * years))]
    n = pd.concat([r.home, r.away]).value_counts()
    return sorted(n[n >= 5].index)


def national_scorers(goals: pd.DataFrame, team: str, lam_team: float, lam_total: float,
                     ref_date=None, absents=()) -> pd.DataFrame:
    """Part des buts de la sélection marqués par chaque joueur (pondérée vers le récent)."""
    if goals.empty:
        return pd.DataFrame()
    ref = pd.Timestamp(ref_date) if ref_date is not None else goals.date.max() + pd.Timedelta(days=1)
    g = goals[(goals.team == team) & (goals.date < ref) & (goals.date >= ref - pd.Timedelta(days=4 * 365))]
    g = g[~g.own_goal.astype(str).str.upper().eq("TRUE")]
    if g.empty:
        return pd.DataFrame()
    age = (ref - g.date).dt.days.to_numpy()
    w = 0.5 ** (age / 365)                                   # demi-vie 1 an
    pen = g.penalty.astype(str).str.upper().eq("TRUE").to_numpy()
    agg = pd.DataFrame({"joueur": g.scorer.values, "w": w, "pen": pen * w, "np": (~pen) * w,
                        "buts": 1, "dernier": g.date.values})
    p = agg.groupby("joueur").agg(np_w=("np", "sum"), pen_w=("pen", "sum"), buts_4ans=("buts", "sum"),
                                  dernier_but=("dernier", "max")).reset_index()
    p = p[p.dernier_but >= ref - pd.Timedelta(days=int(1.5 * 365))]   # joueurs encore actifs
    p = p[~p.joueur.isin(absents)]
    if p.empty:
        return p
    team_np = agg["np"].sum()
    share = p.np_w / (team_np + 2.0)                         # +2 : rétrécissement petits échantillons
    pen_rate = 0.07 * lam_team / 1.35                        # buts sur penalty attendus
    taker = p.pen_w.idxmax() if p.pen_w.max() > 0 else None
    lam_np = max(lam_team - pen_rate, 0.05)
    mu = lam_np * share * 0.9                                # ~90 % du temps de jeu pour un titulaire
    if taker is not None:
        mu.loc[taker] += pen_rate * 0.9
    p["buts_attendus"] = mu
    p["P_buteur"] = 1 - np.exp(-mu)
    p["P_doublé"] = 1 - np.exp(-mu) * (1 + mu)
    p["P_1er_buteur"] = mu / lam_total * (1 - math.exp(-lam_total))
    p["cote_juste_buteur"] = 1 / p["P_buteur"]
    p["tireur_penalty"] = p.index == taker
    p["dernier_but"] = p.dernier_but.dt.date
    return p.sort_values("P_buteur", ascending=False).head(15)[
        ["joueur", "buts_4ans", "dernier_but", "tireur_penalty", "buts_attendus", "P_buteur", "P_doublé",
         "P_1er_buteur", "cote_juste_buteur"]]
