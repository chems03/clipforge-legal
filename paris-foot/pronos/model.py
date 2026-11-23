"""Modèle de force des équipes : Dixon-Coles hiérarchique multi-championnats.

log λ_dom = G[comp] + H[comp]·(1-neutre) + S[ligue_dom] + att[dom] − S[ligue_ext] − def[ext]
log λ_ext = G[comp]                      + S[ligue_ext] + att[ext] − S[ligue_dom] − def[dom]

* G[comp]  : niveau de buts de la compétition (la Bundesliga marque plus que la Serie A, etc.)
* H[comp]  : avantage du terrain propre à chaque compétition
* S[ligue] : niveau du championnat — identifié par la C1 et par les montées/descentes
* att/def  : écarts propres à chaque équipe, rétrécis vers la moyenne de leur ligue (ridge)

Cible : mélange buts réels / xG (xG réels si dispo, sinon xG reconstitués à partir des tirs),
pondération temporelle exponentielle, puis correction Dixon-Coles (ρ) des petits scores.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

# A priori sur le niveau relatif des championnats (≈ coefficients UEFA, en log-buts).
# Volontairement peu contraignant : la C1 et les promus/relégués corrigent ces valeurs.
LEAGUE_PRIOR = {
    "E0": 0.0, "SP1": -0.06, "I1": -0.08, "D1": -0.09, "F1": -0.13, "P1": -0.20, "N1": -0.24,
    "B1": -0.28, "T1": -0.30, "SC0": -0.38, "E1": -0.34, "SP2": -0.42, "I2": -0.44,
    "D2": -0.40, "F2": -0.47,
}
MAX_GOALS = 10


@dataclass
class Config:
    xi: float = 0.0025          # décroissance temporelle par jour (demi-vie ≈ 277 j)
    w_goals: float = 0.65       # poids des buts réels vs xG dans la cible (réglé par backtest)
    sigma_team: float = 0.8     # écart-type a priori des écarts équipe (réglé par backtest)
    sigma_league: float = 0.12  # écart-type a priori du niveau de ligue autour du prior
    cl_weight: float = 1.3      # poids des matchs de C1 (rares mais très informatifs)
    stretch: float = 1.1        # recalibrage : le modèle brut sous-estime les favoris (backtest)


@dataclass
class Model:
    teams: list[str]
    team_league: dict[str, str]
    comps: list[str]
    leagues: list[str]
    G: dict[str, float]
    H: dict[str, float]
    S: dict[str, float]
    att: dict[str, float]
    dfn: dict[str, float]
    rho: float
    ref_date: pd.Timestamp
    config: Config
    xg_coef: tuple[float, float] = (0.0, 0.0)
    n_matches: int = 0
    games_recent: dict[str, float] = field(default_factory=dict)

    # ---------------------------------------------------------------- prédiction
    def lambdas(self, home: str, away: str, comp: str, neutral: bool = False) -> tuple[float, float]:
        for t in (home, away):
            if t not in self.att:
                raise KeyError(f"Équipe inconnue : {t}")
        if comp not in self.G:
            comp = self.team_league[home]
        lh, la = self.team_league[home], self.team_league[away]
        g, h = self.G[comp], 0.0 if neutral else self.H[comp]
        log_h = g + h + self.S[lh] + self.att[home] - self.S[la] - self.dfn[away]
        log_a = g + self.S[la] + self.att[away] - self.S[lh] - self.dfn[home]
        k = getattr(self.config, "stretch", 1.0)
        mid, half = (log_h + log_a) / 2, k * (log_h - log_a) / 2
        return float(np.exp(mid + half)), float(np.exp(mid - half))

    def ratings(self) -> pd.DataFrame:
        """Buts marqués/encaissés attendus contre une équipe moyenne de Premier League, terrain neutre."""
        g = self.G["E0"]
        rows = []
        for t in self.teams:
            L = self.team_league[t]
            gf = np.exp(g + self.S[L] + self.att[t] - self.S["E0"])
            ga = np.exp(g + self.S["E0"] - self.S[L] - self.dfn[t])
            rows.append(dict(equipe=t, ligue=L, buts_pour=gf, buts_contre=ga, diff=gf - ga,
                             matchs_recents=self.games_recent.get(t, 0)))
        return pd.DataFrame(rows).sort_values("diff", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------------ outils
def dc_tau(x, y, lh, la, rho):
    t = np.ones(np.broadcast(x, y, lh, la).shape)
    t = np.where((x == 0) & (y == 0), 1 - lh * la * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lh * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + la * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


def score_matrix(lh: float, la: float, rho: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def fit_xg_from_shots(df: pd.DataFrame) -> tuple[float, float]:
    """xG ≈ b1·tirs non cadrés + b2·tirs cadrés (moindres carrés), appris là où les xG existent."""
    rows = []
    for s, st, xg in [("hs", "hst", "hxg"), ("as_", "ast", "axg")]:
        sub = df[[s, st, xg]].dropna()
        rows.append(np.c_[sub[s] - sub[st], sub[st], sub[xg]])
    X = np.vstack(rows)
    if len(X) < 200:
        return 0.035, 0.30  # valeurs typiques
    coef, *_ = np.linalg.lstsq(X[:, :2], X[:, 2], rcond=None)
    return float(coef[0]), float(coef[1])


def _target(df: pd.DataFrame, side: str, w_goals: float, xg_coef) -> np.ndarray:
    g = df["hg" if side == "h" else "ag"].to_numpy(float)
    xg = df["hxg" if side == "h" else "axg"].to_numpy(float)
    s = df["hs" if side == "h" else "as_"].to_numpy(float)
    st = df["hst" if side == "h" else "ast"].to_numpy(float)
    pseudo = xg_coef[0] * (s - st) + xg_coef[1] * st
    xg_est = np.where(np.isfinite(xg), xg, np.where(np.isfinite(pseudo), pseudo, g))
    return w_goals * g + (1 - w_goals) * xg_est


# ------------------------------------------------------------------------ ajustement
def fit(df: pd.DataFrame, ref_date=None, config: Config | None = None,
        min_weight: float = 0.02) -> Model:
    cfg = config or Config()
    ref_date = pd.Timestamp(ref_date) if ref_date is not None else df["date"].max() + pd.Timedelta(days=1)
    d = df[(df["date"] < ref_date)].copy()
    age = (ref_date - d["date"]).dt.days.to_numpy(float)
    w = np.exp(-cfg.xi * age)
    w = np.where(d["comp"].to_numpy() == "CL", w * cfg.cl_weight, w)
    keep = w >= min_weight
    d, w = d[keep].reset_index(drop=True), w[keep]

    xg_coef = fit_xg_from_shots(d)
    yh = _target(d, "h", cfg.w_goals, xg_coef)
    ya = _target(d, "a", cfg.w_goals, xg_coef)

    # ligue "actuelle" de chaque équipe = championnat de son dernier match domestique
    dom = d[d["comp"] != "CL"]
    last = pd.concat([dom[["date", "home", "comp"]].rename(columns={"home": "t"}),
                      dom[["date", "away", "comp"]].rename(columns={"away": "t"})])
    last = last.sort_values("date").groupby("t")["comp"].last()
    teams = sorted(last.index)
    d = d[d["home"].isin(last.index) & d["away"].isin(last.index)]
    w, yh, ya = w[d.index], yh[d.index], ya[d.index]
    d = d.reset_index(drop=True)

    comps = sorted(d["comp"].unique())
    leagues = sorted(set(last.values))
    ti = {t: i for i, t in enumerate(teams)}
    ci = {c: i for i, c in enumerate(comps)}
    li = {l: i for i, l in enumerate(leagues)}
    team_league_idx = np.array([li[last[t]] for t in teams])

    hi = d["home"].map(ti).to_numpy()
    ai = d["away"].map(ti).to_numpy()
    cc = d["comp"].map(ci).to_numpy()
    nh = 1.0 - d["neutral"].fillna(False).astype(bool).to_numpy(float)
    hl, al = team_league_idx[hi], team_league_idx[ai]

    nT, nC, nL = len(teams), len(comps), len(leagues)
    o_G, o_H, o_S, o_a, o_d = 0, nC, 2 * nC, 2 * nC + nL, 2 * nC + nL + nT
    n_par = o_d + nT
    prior_S = np.array([LEAGUE_PRIOR.get(l, -0.4) for l in leagues])
    k_t, k_l = 1 / cfg.sigma_team ** 2, 1 / cfg.sigma_league ** 2

    def unpack(p):
        return p[o_G:o_H], p[o_H:o_S], p[o_S:o_a], p[o_a:o_d], p[o_d:]

    def f(p):
        G, H, S, A, D = unpack(p)
        eh = G[cc] + H[cc] * nh + S[hl] + A[hi] - S[al] - D[ai]
        ea = G[cc] + S[al] + A[ai] - S[hl] - D[hi]
        lh, la = np.exp(eh), np.exp(ea)
        nll = np.sum(w * (lh - yh * eh + la - ya * ea))
        pen = 0.5 * k_t * (A @ A + D @ D) + 0.5 * k_l * np.sum((S - prior_S) ** 2) + 0.5 * np.sum(H ** 2)
        rh, ra = w * (lh - yh), w * (la - ya)
        gG = np.bincount(cc, rh + ra, nC)
        gH = np.bincount(cc, rh * nh, nC) + H
        gS = (np.bincount(hl, rh - ra, nL) + np.bincount(al, ra - rh, nL)) + k_l * (S - prior_S)
        gA = np.bincount(hi, rh, nT) + np.bincount(ai, ra, nT) + k_t * A
        gD = -np.bincount(ai, rh, nT) - np.bincount(hi, ra, nT) + k_t * D
        return nll + pen, np.concatenate([gG, gH, gS, gA, gD])

    p0 = np.zeros(n_par)
    p0[o_G:o_H] = np.log(1.35)
    p0[o_H:o_S] = 0.2
    p0[o_S:o_a] = prior_S
    res = minimize(f, p0, jac=True, method="L-BFGS-B", options=dict(maxiter=3000))
    G, H, S, A, D = unpack(res.x)

    # ρ de Dixon-Coles sur les scores réels
    eh = G[cc] + H[cc] * nh + S[hl] + A[hi] - S[al] - D[ai]
    ea = G[cc] + S[al] + A[ai] - S[hl] - D[hi]
    lh, la = np.exp(eh), np.exp(ea)
    x, y = d["hg"].to_numpy(int), d["ag"].to_numpy(int)
    low = (x <= 1) & (y <= 1)

    def nll_rho(r):
        t = dc_tau(x[low], y[low], lh[low], la[low], r)
        return -np.sum(w[low] * np.log(np.clip(t, 1e-9, None)))

    rho = float(minimize_scalar(nll_rho, bounds=(-0.25, 0.25), method="bounded").x)

    recent = d[d["date"] >= ref_date - pd.Timedelta(days=120)]
    games = pd.concat([recent.home, recent.away]).value_counts().to_dict()
    return Model(
        teams=teams, team_league={t: last[t] for t in teams}, comps=comps, leagues=leagues,
        G=dict(zip(comps, G)), H=dict(zip(comps, H)), S=dict(zip(leagues, S)),
        att=dict(zip(teams, A)), dfn=dict(zip(teams, D)), rho=rho, ref_date=ref_date,
        config=cfg, xg_coef=xg_coef, n_matches=len(d), games_recent=games,
    )
