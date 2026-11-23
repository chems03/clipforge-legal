"""Marchés de paris dérivés de la matrice de scores + outils cotes (marge, value, Kelly)."""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import poisson

from .model import MAX_GOALS, score_matrix

HT_SHARE = 0.445  # part des buts marqués en 1re mi-temps (≈ moyenne des grands championnats)


# --------------------------------------------------------------------------- cotes
def devig(odds: list[float], method: str = "power") -> np.ndarray | None:
    """Retire la marge du bookmaker -> probabilités "vraies" implicites.
    Méthode 'power' : corrige le biais favori/outsider mieux que la simple normalisation."""
    o = np.asarray(odds, float)
    if o.size == 0 or not np.all(np.isfinite(o)) or np.any(o <= 1):
        return None
    q = 1 / o
    if method == "proportional":
        return q / q.sum()
    lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        s = np.sum(q ** k)
        lo, hi = (k, hi) if s > 1 else (lo, k)
    p = q ** ((lo + hi) / 2)
    return p / p.sum()


def margin(odds) -> float:
    return float(np.sum(1 / np.asarray(odds, float)) - 1)


def kelly(p: float, odds: float, fraction: float = 0.25) -> float:
    """Mise Kelly fractionnée (en % de bankroll). 0 si pas de value."""
    b = odds - 1
    if b <= 0:
        return 0.0
    f = (p * b - (1 - p)) / b
    return max(0.0, f * fraction)


def fair_odds(p: float) -> float:
    return float("inf") if p <= 0 else 1 / p


# --------------------------------------------------------------------------- marché -> λ
def implied_lambdas(p_home: float, p_away: float, rho: float, p_over25: float | None = None,
                    guess=(1.4, 1.1)) -> tuple[float, float]:
    """Trouve (λdom, λext) qui reproduisent les probabilités du marché (1X2 et +/-2.5)."""
    def res(x):
        lh, la = np.exp(x)
        M = score_matrix(lh, la, rho)
        r = [np.tril(M, -1).sum() - p_home, np.triu(M, 1).sum() - p_away]
        if p_over25 is not None:
            g = np.add.outer(np.arange(M.shape[0]), np.arange(M.shape[1]))
            r.append(0.7 * (M[g >= 3].sum() - p_over25))
        return r
    sol = least_squares(res, np.log(guess), bounds=([-3, -3], [2, 2]))
    return tuple(float(v) for v in np.exp(sol.x))


def blend_lambdas(model_l, market_l, alpha: float):
    """Pool log-linéaire : alpha = poids du modèle, 1-alpha = poids du marché."""
    return tuple(float(np.exp(alpha * np.log(a) + (1 - alpha) * np.log(b)))
                 for a, b in zip(model_l, market_l))


# --------------------------------------------------------------------------- marchés
def all_markets(lh: float, la: float, rho: float) -> dict:
    M = score_matrix(lh, la, rho)
    n = M.shape[0]
    i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    tot, diff = i + j, i - j
    P = lambda mask: float(M[mask].sum())  # noqa: E731

    pH, pD, pA = P(diff > 0), P(diff == 0), P(diff < 0)
    out: dict = {"lambda": (lh, la), "matrix": M}
    out["1X2"] = {"1": pH, "N": pD, "2": pA}
    out["Double chance"] = {"1N": pH + pD, "N2": pD + pA, "12": pH + pA}
    out["Remboursé si nul"] = {"1": pH / (pH + pA), "2": pA / (pH + pA)}
    out["Plus/Moins buts"] = {f"+{k}.5": P(tot > k) for k in range(0, 6)}
    out["BTTS"] = {"Oui": P((i > 0) & (j > 0)), "Non": P((i == 0) | (j == 0))}
    out["Buts domicile"] = {f"+{k}.5": P(i > k) for k in range(0, 4)}
    out["Buts extérieur"] = {f"+{k}.5": P(j > k) for k in range(0, 4)}
    out["Clean sheet"] = {"Domicile": P(j == 0), "Extérieur": P(i == 0)}
    out["Gagne sans encaisser"] = {"Domicile": P((diff > 0) & (j == 0)), "Extérieur": P((diff < 0) & (i == 0))}
    out["Nombre exact de buts"] = {**{str(k): P(tot == k) for k in range(5)}, "5+": P(tot >= 5)}
    out["Écart"] = {
        "Dom +3": P(diff >= 3), "Dom +2": P(diff == 2), "Dom +1": P(diff == 1), "Nul": pD,
        "Ext +1": P(diff == -1), "Ext +2": P(diff == -2), "Ext +3": P(diff <= -3)}
    out["Pair/Impair"] = {"Pair": P(tot % 2 == 0), "Impair": P(tot % 2 == 1)}
    out["Résultat + BTTS"] = {
        f"{r} & {b}": P(m & bm) for r, m in (("1", diff > 0), ("N", diff == 0), ("2", diff < 0))
        for b, bm in (("BTTS oui", (i > 0) & (j > 0)), ("BTTS non", (i == 0) | (j == 0)))}
    out["Résultat + 2.5"] = {
        f"{r} & {b}": P(m & bm) for r, m in (("1", diff > 0), ("N", diff == 0), ("2", diff < 0))
        for b, bm in (("+2.5", tot > 2), ("-2.5", tot <= 2))}
    # Handicap asiatique (lignes entières et demi-lignes) : proba gagnée / remboursée
    ah = {}
    for line in [-2.5, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 2.5]:
        adj = diff + line
        ah[f"Dom {line:+g}"] = (P(adj > 0), P(adj == 0))
    out["Handicap asiatique"] = ah
    scores = sorted(((float(M[a, b]), f"{a}-{b}") for a in range(7) for b in range(7)), reverse=True)
    out["Score exact"] = {s: p for p, s in scores[:15]}
    out["Score exact (autre)"] = 1 - sum(p for p, _ in scores[:15])

    # Mi-temps et MT/FT (deux mi-temps Poisson indépendantes)
    h1, a1 = lh * HT_SHARE, la * HT_SHARE
    h2, a2 = lh - h1, la - a1
    k = np.arange(n)
    M1 = np.outer(poisson.pmf(k, h1), poisson.pmf(k, a1))
    M2 = np.outer(poisson.pmf(k, h2), poisson.pmf(k, a2))
    d1 = np.subtract.outer(k, k)
    # distribution de l'écart en 1re et 2e mi-temps
    def diff_dist(Mx):
        dd = {}
        for a in range(n):
            for b in range(n):
                dd[a - b] = dd.get(a - b, 0) + Mx[a, b]
        return dd
    D1, D2 = diff_dist(M1), diff_dist(M2)
    sgn = lambda x: "1" if x > 0 else ("N" if x == 0 else "2")  # noqa: E731
    htft = {}
    for x, px in D1.items():
        for y, py in D2.items():
            key = f"{sgn(x)}/{sgn(x + y)}"
            htft[key] = htft.get(key, 0) + px * py
    out["Mi-temps 1X2"] = {"1": float(M1[d1 > 0].sum()), "N": float(M1[d1 == 0].sum()),
                           "2": float(M1[d1 < 0].sum())}
    order = [f"{a}/{b}" for a in "1N2" for b in "1N2"]
    out["Mi-temps / Fin de match"] = {kk: float(htft.get(kk, 0)) for kk in order}
    g1 = np.add.outer(k, k)
    out["Buts 1re mi-temps"] = {f"+{q}.5": float(M1[g1 > q].sum()) for q in range(3)}
    return out


def rps(p: np.ndarray, outcome: int) -> float:
    """Ranked Probability Score sur (1, N, 2)."""
    o = np.zeros(3)
    o[outcome] = 1
    return float(np.sum((np.cumsum(p)[:2] - np.cumsum(o)[:2]) ** 2) / 2)
