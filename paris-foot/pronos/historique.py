"""Historique des pronos : pour chaque match passé, ce que l'appli aurait conseillé AVANT le match
(modèle ré-entraîné chaque semaine avec uniquement les matchs précédents + cotes d'avant-match),
puis comparaison avec le vrai résultat -> réussite / échec."""
from __future__ import annotations

import pickle
from typing import Callable

import numpy as np
import pandas as pd

from .data import ROOT
from .engine import predict
from .model import Config, fit

# Les semaines terminées sont sauvegardées ici (versionnées dans le dépôt -> chargement rapide en ligne)
HIST_DIR = ROOT / "data" / "historique"
HIST_DIR.mkdir(parents=True, exist_ok=True)
VERSION = "v2"
EURO = ["CL", "EL", "ECL"]
SCOPES = {
    # nom : (filtre des matchs, pas en jours, début par défaut)
    "clubs": (lambda d: ~d.comp.isin(EURO), 7, None),
    "euro": (lambda d: d.comp.isin(EURO), 28, "2024-07-01"),
    "nat": (lambda d: d.comp.notna(), 14, "2024-09-01"),
}


def _clean(v):
    return float(v) if v is not None and np.isfinite(v) and v > 1 else None


def _predict_window(df: pd.DataFrame, t: pd.Timestamp, t2: pd.Timestamp, scope: str) -> list[dict]:
    flt = SCOPES[scope][0]
    test = df[(df.date >= t) & (df.date < t2)]
    test = test[flt(test)]
    if test.empty:
        return []
    if scope == "nat":
        from .nationals import fit_national
        m = fit_national(df, ref_date=t)
    else:
        m = fit(df, ref_date=t, config=Config())
    rows = []
    for r in test.itertuples():
        odds = {k: _clean(getattr(r, c)) for k, c in
                dict(h="o_h", d="o_d", a="o_a", o25="o_o25", u25="o_u25").items()}
        best = {k: _clean(getattr(r, c)) for k, c in
                dict(h="max_h", d="max_d", a="max_a", o25="max_o25", u25="max_u25").items()}
        try:
            res = predict(m, r.home, r.away, r.comp, neutral=(r.neutral is True or r.neutral == 1),
                          odds=odds if odds["h"] else None,
                          value_odds=best if best["h"] else None)
        except KeyError:
            continue
        k = res["markets"]
        hg, ag = int(r.hg), int(r.ag)
        real = "1" if hg > ag else ("N" if hg == ag else "2")
        p1x2 = k["1X2"]
        pick = max(p1x2, key=p1x2.get)
        p_over = k["Plus/Moins buts"]["+2.5"]
        p_btts = k["BTTS"]["Oui"]
        top_score, p_top = next(iter(k["Score exact"].items()))
        dc = k["Double chance"]
        dc_pick = max(dc, key=dc.get)
        value = []
        for v in res["value"]:
            won = {"1": real == "1", "N": real == "N", "2": real == "2",
                   "+2.5": hg + ag > 2, "-2.5": hg + ag <= 2}[v["pari"]]
            value.append(dict(pari=v["pari"], cote=v["cote"], proba=v["proba"], gagne=won,
                              profit=v["cote"] - 1 if won else -1.0))
        rows.append(dict(
            date=r.date, comp=r.comp, home=r.home, away=r.away, hg=hg, ag=ag,
            score=f"{hg}-{ag}", mt=(f"{int(r.hthg)}-{int(r.htag)}" if np.isfinite(r.hthg) else ""),
            hxg=r.hxg, axg=r.axg, real=real, p1=p1x2["1"], pn=p1x2["N"], p2=p1x2["2"],
            prono_1x2=pick, p_prono_1x2=p1x2[pick], ok_1x2=pick == real,
            prono_dc=dc_pick, p_prono_dc=dc[dc_pick], ok_dc=real in dc_pick,
            prono_buts="+2.5" if p_over >= 0.5 else "-2.5", p_prono_buts=max(p_over, 1 - p_over),
            ok_buts=(hg + ag > 2) == (p_over >= 0.5),
            prono_btts="Oui" if p_btts >= 0.5 else "Non", p_prono_btts=max(p_btts, 1 - p_btts),
            ok_btts=(hg > 0 and ag > 0) == (p_btts >= 0.5),
            prono_score=top_score, p_prono_score=p_top, ok_score=top_score == f"{hg}-{ag}",
            value=value, avec_cotes=res["lambda_market"] is not None))
    return rows


def build_history(df: pd.DataFrame, scope: str = "clubs", start=None,
                  progress: Callable[[float], None] | None = None) -> pd.DataFrame:
    """clubs : championnats, saison en cours · euro : C1/C3/C4 · nat : sélections nationales.
    Les périodes terminées sont mises en cache (calcul incrémental)."""
    _, step, default_start = SCOPES[scope]
    start = start or default_start
    if start is None:
        dom = df[~df.comp.isin(EURO)]
        cur = dom["season"].dropna().max()
        start = dom[dom.season == cur].date.min()
    start = pd.Timestamp(start).normalize()
    start -= pd.Timedelta(days=start.weekday())          # semaines du lundi au lundi
    last = df.date.max()
    weeks = []
    t = start
    while t <= last:
        weeks.append(t)
        t += pd.Timedelta(days=step)
    rows = []
    for i, t in enumerate(weeks):
        t2 = t + pd.Timedelta(days=step)
        f = HIST_DIR / f"{scope}_{VERSION}_{t:%Y%m%d}.pkl"
        complete = t2 <= last  # semaine entièrement jouée -> cachable
        if complete and f.exists():
            part = pickle.loads(f.read_bytes())
        else:
            part = _predict_window(df, t, t2, scope)
            if complete:
                f.write_bytes(pickle.dumps(part))
        rows += part
        if progress:
            progress((i + 1) / len(weeks))
    return pd.DataFrame(rows).sort_values("date", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()


MARKETS = [
    ("1X2 (résultat)", "prono_1x2", "p_prono_1x2", "ok_1x2"),
    ("Double chance", "prono_dc", "p_prono_dc", "ok_dc"),
    ("Plus/Moins 2.5 buts", "prono_buts", "p_prono_buts", "ok_buts"),
    ("Les deux marquent", "prono_btts", "p_prono_btts", "ok_btts"),
    ("Score exact", "prono_score", "p_prono_score", "ok_score"),
]


def summary(h: pd.DataFrame) -> pd.DataFrame:
    out = []
    for name, _, p, ok in MARKETS:
        n = len(h)
        w = int(h[ok].sum())
        out.append({"Pari": name, "Pronos": n, "✅ Réussis": w, "❌ Ratés": n - w,
                    "% réussite": w / n if n else 0.0, "% attendu": float(h[p].mean()) if n else 0.0})
    return pd.DataFrame(out)


def value_bets(h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in h.itertuples():
        for v in r.value:
            rows.append(dict(date=r.date, comp=r.comp, match=f"{r.home} – {r.away}", score=r.score, **v))
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True) if rows else pd.DataFrame()


def by_confidence(h: pd.DataFrame, ok: str = "ok_1x2", p: str = "p_prono_1x2") -> pd.DataFrame:
    bins = [0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]
    labels = ["< 40 %", "40-50 %", "50-60 %", "60-70 %", "70-80 %", "≥ 80 %"]
    c = pd.cut(h[p], bins=bins, labels=labels, right=False)
    g = h.groupby(c, observed=True)[ok].agg(["count", "sum", "mean"])
    g.columns = ["Pronos", "✅ Réussis", "% réussite"]
    g["❌ Ratés"] = g["Pronos"] - g["✅ Réussis"]
    return g.reset_index(names="Confiance")[["Confiance", "Pronos", "✅ Réussis", "❌ Ratés", "% réussite"]]
