"""Backtest "walk-forward" : on ré-entraîne le modèle avec uniquement le passé,
puis on prédit les matchs suivants — exactement comme en conditions réelles."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import MAIN_LEAGUES
from .markets import devig, implied_lambdas, blend_lambdas
from .model import Config, fit, score_matrix


def _probs(lh, la, rho):
    M = score_matrix(lh, la, rho)
    g = np.add.outer(np.arange(M.shape[0]), np.arange(M.shape[1]))
    return np.array([np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()]), M[g >= 3].sum()


def walk_forward(df: pd.DataFrame, start, end=None, step_days: int = 14, config: Config | None = None,
                 leagues=MAIN_LEAGUES, verbose: bool = False) -> pd.DataFrame:
    start = pd.Timestamp(start)
    end = pd.Timestamp(end) if end is not None else df["date"].max() + pd.Timedelta(days=1)
    rows = []
    t = start
    while t < end:
        t2 = min(t + pd.Timedelta(days=step_days), end)
        test = df[(df.date >= t) & (df.date < t2) & df.comp.isin(leagues)]
        if len(test):
            m = fit(df, ref_date=t, config=config)
            for r in test.itertuples():
                try:
                    lh, la = m.lambdas(r.home, r.away, r.comp)
                except KeyError:
                    continue
                p, pov = _probs(lh, la, m.rho)
                outcome = 0 if r.hg > r.ag else (1 if r.hg == r.ag else 2)
                rows.append(dict(date=r.date, comp=r.comp, home=r.home, away=r.away, outcome=outcome,
                                 over=int(r.hg + r.ag > 2), lh=lh, la=la, rho=m.rho,
                                 pm_h=p[0], pm_d=p[1], pm_a=p[2], pm_o=pov,
                                 oc_h=r.oc_h, oc_d=r.oc_d, oc_a=r.oc_a, o_h=r.o_h, o_d=r.o_d, o_a=r.o_a,
                                 max_h=r.max_h, max_d=r.max_d, max_a=r.max_a,
                                 oc_o25=r.oc_o25, oc_u25=r.oc_u25, o_o25=r.o_o25, o_u25=r.o_u25))
            if verbose:
                print(t.date(), len(test), flush=True)
        t = t2
    return pd.DataFrame(rows)


def _ll(P, y):
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], 1e-12, None))))


def _rps(P, y):
    O = np.zeros_like(P)
    O[np.arange(len(y)), y] = 1
    return float(np.mean(np.sum((np.cumsum(P, 1)[:, :2] - np.cumsum(O, 1)[:, :2]) ** 2, 1) / 2))


def market_probs(bt: pd.DataFrame, prefix: str = "o") -> np.ndarray:
    out = []
    for r in bt[[f"{prefix}_h", f"{prefix}_d", f"{prefix}_a"]].itertuples(index=False):
        p = devig(list(r))
        out.append(p if p is not None else [np.nan] * 3)
    return np.array(out)


def evaluate(bt: pd.DataFrame, alphas=(0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0)) -> dict:
    """Compare modèle / marché d'ouverture / marché de clôture et cherche le meilleur mélange."""
    y = bt["outcome"].to_numpy()
    Pm = bt[["pm_h", "pm_d", "pm_a"]].to_numpy()
    Po = market_probs(bt, "o")
    Pc = market_probs(bt, "oc")
    ok = np.isfinite(Po).all(1) & np.isfinite(Pc).all(1)
    y, Pm, Po, Pc = y[ok], Pm[ok], Po[ok], Pc[ok]
    res = {"n": int(ok.sum()),
           "modele": dict(logloss=_ll(Pm, y), rps=_rps(Pm, y)),
           "marche_ouverture": dict(logloss=_ll(Po, y), rps=_rps(Po, y)),
           "marche_cloture": dict(logloss=_ll(Pc, y), rps=_rps(Pc, y))}
    blends = {}
    for a in alphas:
        P = np.exp(a * np.log(Pm) + (1 - a) * np.log(Po))
        P /= P.sum(1, keepdims=True)
        blends[a] = dict(logloss=_ll(P, y), rps=_rps(P, y))
    res["melange_modele_ouverture"] = blends
    res["alpha_optimal"] = min(blends, key=lambda a: blends[a]["logloss"])
    return res


def simulate_value_bets(bt: pd.DataFrame, alpha: float, min_edge: float = 0.03,
                        kelly_frac: float = 0.25, odds_prefix: str = "max") -> dict:
    """Simulation de paris 1X2 : on parie quand (proba mélangée × meilleure cote − 1) > min_edge."""
    y = bt["outcome"].to_numpy()
    Pm = bt[["pm_h", "pm_d", "pm_a"]].to_numpy()
    Po = market_probs(bt, "o")
    odds = bt[[f"{odds_prefix}_h", f"{odds_prefix}_d", f"{odds_prefix}_a"]].to_numpy(float)
    ok = np.isfinite(Po).all(1) & np.isfinite(odds).all(1)
    P = np.exp(alpha * np.log(Pm[ok]) + (1 - alpha) * np.log(Po[ok]))
    P /= P.sum(1, keepdims=True)
    O, Y = odds[ok], y[ok]
    n_bets, staked, profit, flat_profit, clv = 0, 0.0, 0.0, 0.0, []
    for p, o, yy in zip(P, O, Y):
        for k in range(3):
            edge = p[k] * o[k] - 1
            if edge > min_edge and o[k] < 8:
                f = max(0.0, (p[k] * (o[k] - 1) - (1 - p[k])) / (o[k] - 1)) * kelly_frac
                n_bets += 1
                staked += f
                win = (yy == k)
                profit += f * (o[k] - 1) if win else -f
                flat_profit += (o[k] - 1) if win else -1
    return dict(paris=n_bets, roi_mise_fixe=flat_profit / max(1, n_bets),
                roi_kelly=profit / staked if staked else 0.0)
