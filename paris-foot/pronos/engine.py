"""Logique partagée CLI / appli : chargement, prédiction combinée modèle + marché, value bets."""
from __future__ import annotations

import json
import pickle
from datetime import date, datetime
from difflib import get_close_matches

import numpy as np
import pandas as pd

from . import backtest as bt_mod
from .data import CACHE, MAIN_LEAGUES, load_all, load_fixtures
from .markets import all_markets, blend_lambdas, devig, implied_lambdas, kelly
from .model import Config, Model, fit

# Poids du modèle quand des cotes sont disponibles (le reste = consensus du marché).
# Backtest 2025-26 : le consensus des bookmakers reste plus précis que tout modèle statistique
# public ; le modèle sert à corriger légèrement le marché et à couvrir les marchés exotiques.
ALPHA_MODEL = 0.2
MIN_EDGE = 0.05
BACKTEST_JSON = CACHE / "backtest.json"


def get_model(force: bool = False, n_seasons: int = 4) -> tuple[Model, pd.DataFrame]:
    key = CACHE / f"model_{date.today():%Y%m%d}.pkl"
    if key.exists() and not force:
        with open(key, "rb") as f:
            return pickle.load(f)
    df, info = load_all(n_seasons, force=force)
    m = fit(df, config=Config())
    m.info = info  # type: ignore[attr-defined]
    for old in CACHE.glob("model_*.pkl"):
        old.unlink()
    with open(key, "wb") as f:
        pickle.dump((m, df), f)
    return m, df


def get_national_model(force: bool = False):
    """Modèle des sélections nationales + historique des buteurs."""
    from .data import load_internationals
    from .nationals import fit_national
    key = CACHE / f"natmodel_{date.today():%Y%m%d}.pkl"
    if key.exists() and not force:
        with open(key, "rb") as f:
            return pickle.load(f)
    df, goals = load_internationals(force=force)
    m = fit_national(df)
    for old in CACHE.glob("natmodel_*.pkl"):
        old.unlink()
    with open(key, "wb") as f:
        pickle.dump((m, df, goals), f)
    return m, df, goals


def resolve_team(m: Model, name: str) -> str:
    if name in m.att:
        return name
    low = {t.lower(): t for t in m.teams}
    if name.lower() in low:
        return low[name.lower()]
    sub = [t for t in m.teams if name.lower() in t.lower()]
    if len(sub) == 1:
        return sub[0]
    c = get_close_matches(name, m.teams, n=1, cutoff=0.5)
    if c:
        return c[0]
    raise KeyError(f"Équipe introuvable : {name}. Exemples : {', '.join(m.teams[:10])}…")


def _market_from_odds(odds: dict | None):
    if not odds:
        return None, None
    p = devig([odds.get("h"), odds.get("d"), odds.get("a")]) if all(
        odds.get(k) for k in ("h", "d", "a")) else None
    po = None
    if odds.get("o25") and odds.get("u25"):
        po = devig([odds["o25"], odds["u25"]])[0]
    elif odds.get("o25"):
        po = min(0.97, 1 / odds["o25"] / 1.04)  # marge approximative si une seule cote
    return p, po


def predict(m: Model, home: str, away: str, comp: str, neutral: bool = False, odds: dict | None = None,
            adj: dict | None = None, alpha: float = ALPHA_MODEL, value_odds: dict | None = None,
            allow_unknown: bool = False) -> dict:
    """odds       : cotes de référence (consensus) {h,d,a,o25,u25} pour caler le modèle sur le marché
       value_odds : cotes auxquelles tu peux réellement jouer (par défaut = odds)
       adj        : ajustements manuels en % {att_h, def_h, att_a, def_a} (blessures, rotation…)"""
    lm = m.lambdas(home, away, comp, neutral, allow_unknown=allow_unknown)
    adj = adj or {}
    lm = (lm[0] * (1 + adj.get("att_h", 0)) * (1 - adj.get("def_a", 0)),
          lm[1] * (1 + adj.get("att_a", 0)) * (1 - adj.get("def_h", 0)))
    p1x2, pov = _market_from_odds(odds)
    lmk = None
    lam = lm
    if p1x2 is not None:
        lmk = implied_lambdas(p1x2[0], p1x2[2], m.rho, pov, guess=lm)
        lam = blend_lambdas(lm, lmk, alpha)
    mk = all_markets(lam[0], lam[1], m.rho)
    mk_model = all_markets(lm[0], lm[1], m.rho)
    value = []
    vo = value_odds or odds or {}
    checks = [("1", mk["1X2"]["1"], vo.get("h")), ("N", mk["1X2"]["N"], vo.get("d")),
              ("2", mk["1X2"]["2"], vo.get("a")), ("+2.5", mk["Plus/Moins buts"]["+2.5"], vo.get("o25")),
              ("-2.5", 1 - mk["Plus/Moins buts"]["+2.5"], vo.get("u25"))]
    for name, p, o in checks:
        if o and np.isfinite(o) and o > 1:
            v = p * o - 1
            value.append(dict(pari=name, proba=p, cote=o, value=v, kelly=kelly(p, o), jouable=v >= MIN_EDGE))
    return dict(home=home, away=away, comp=comp, neutral=neutral, lambda_model=lm, lambda_market=lmk,
                lambda_=lam, **{"lambda": lam}, markets=mk, markets_model=mk_model,
                value=[v for v in value if v["jouable"]], all_value=value, p_market=p1x2)


def upcoming_table(m: Model, leagues=MAIN_LEAGUES, fixtures: pd.DataFrame | None = None,
                   cups: bool = True) -> pd.DataFrame:
    fx = load_fixtures() if fixtures is None else fixtures
    if cups:
        from .data import load_cup_calendar
        _, up = load_cup_calendar(set(m.teams))
        if not up.empty:
            up = up[up.date.between(pd.Timestamp(date.today()), pd.Timestamp(date.today()) + pd.Timedelta(days=10))]
            fx = pd.concat([fx, up], ignore_index=True)
            for c in ["o_h", "o_d", "o_a", "o_o25", "o_u25", "max_h", "max_d", "max_a", "max_o25", "max_u25"]:
                if c not in fx:
                    fx[c] = np.nan
            leagues = list(leagues) + ["CL", "EL", "ECL"]
    if fx.empty:
        return fx
    fx = fx[fx.comp.isin(leagues) & (fx.date >= pd.Timestamp(date.today()))].sort_values(["date", "time"])
    rows = []
    for r in fx.itertuples():
        try:
            odds = dict(h=r.o_h, d=r.o_d, a=r.o_a, o25=r.o_o25, u25=r.o_u25)
            odds = {k: (v if np.isfinite(v) else None) for k, v in odds.items()}
            best = dict(h=r.max_h, d=r.max_d, a=r.max_a, o25=r.max_o25, u25=r.max_u25)
            best = {k: (v if np.isfinite(v) else None) for k, v in best.items()}
            approx = r.home not in m.att or r.away not in m.att
            res = predict(m, r.home, r.away, r.comp, odds=odds if odds["h"] else None,
                          value_odds=best if best["h"] else None, allow_unknown=approx and r.comp in ("CL", "EL", "ECL"))
        except KeyError:
            continue
        k = res["markets"]
        top = next(iter(k["Score exact"].items()))
        rows.append(dict(
            date=r.date.date(), heure=getattr(r, "time", ""), comp=r.comp, home=r.home, away=r.away,
            xg_dom=res["lambda"][0], xg_ext=res["lambda"][1],
            P1=k["1X2"]["1"], PN=k["1X2"]["N"], P2=k["1X2"]["2"],
            score_probable=f"{top[0]} ({top[1]:.0%})", **{"P+2.5": k["Plus/Moins buts"]["+2.5"]},
            BTTS=k["BTTS"]["Oui"], cote1=r.max_h, coteN=r.max_d, cote2=r.max_a,
            value=", ".join(f"{v['pari']} @{v['cote']:.2f} ({v['value']:+.0%})" for v in res["value"]),
            cale_marche=res["lambda_market"] is not None, approx=approx,
            o_h=odds["h"], o_d=odds["d"], o_a=odds["a"], o_o25=odds["o25"], o_u25=odds["u25"]))
    return pd.DataFrame(rows)


def run_backtest(start=None, verbose: bool = False) -> dict:
    m, df = get_model()
    if start is None:
        last = df.date.max()
        start = pd.Timestamp(year=last.year - 1 if last.month >= 7 else last.year - 2, month=8, day=1)
    bt = bt_mod.walk_forward(df, start, step_days=21, verbose=verbose)
    ev = bt_mod.evaluate(bt, alphas=(0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0))
    strategies = {}
    for a in (0.0, ALPHA_MODEL, 0.4, 1.0):
        for e in (0.03, MIN_EDGE, 0.10):
            strategies[f"alpha={a} edge>={e:.0%}"] = bt_mod.simulate_value_bets(bt, a, e)
    # calibration : proba prédite vs fréquence observée (victoire domicile, modèle seul)
    Pm = bt[["pm_h", "pm_d", "pm_a"]].to_numpy().ravel()
    Y = np.eye(3)[bt.outcome.to_numpy()].ravel()
    bins = np.linspace(0, 1, 11)
    idx = np.digitize(Pm, bins) - 1
    calib = [dict(prevu=float(Pm[idx == b].mean()), observe=float(Y[idx == b].mean()), n=int((idx == b).sum()))
             for b in range(10) if (idx == b).sum() > 20]
    res = dict(date=datetime.now().isoformat(timespec="minutes"), debut=str(pd.Timestamp(start).date()),
               evaluation=ev, strategies=strategies, calibration=calib)
    BACKTEST_JSON.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=float))
    return res


def load_backtest() -> dict | None:
    if BACKTEST_JSON.exists():
        return json.loads(BACKTEST_JSON.read_text())
    return None
