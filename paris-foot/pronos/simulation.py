"""Simulateur avec argent fictif : portefeuille de paris virtuels (réglés automatiquement avec les vrais
résultats) et test de stratégies sur les matchs déjà joués (avec les vraies cotes d'avant-match)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

import numpy as np
import pandas as pd

from .data import CACHE

PORTFOLIO = CACHE / "simulation.json"
START_BANKROLL = 1000.0
MARKETS = ["1X2", "Double chance", "Plus/Moins buts", "BTTS", "Score exact"]


# --------------------------------------------------------------------------- règles de gain
def wins(market: str, selection: str, hg: int, ag: int) -> bool | None:
    """True / False selon le score final ; None si la sélection n'est pas reconnue."""
    tot = hg + ag
    res = "1" if hg > ag else ("N" if hg == ag else "2")
    if market == "1X2":
        return selection == res
    if market == "Double chance":
        return res in selection
    if market == "Plus/Moins buts":
        line = float(selection[1:])
        return tot > line if selection.startswith("+") else tot < line
    if market == "BTTS":
        both = hg > 0 and ag > 0
        return both if selection == "Oui" else not both
    if market == "Score exact":
        return selection == f"{hg}-{ag}"
    return None


# --------------------------------------------------------------------------- portefeuille
def new_portfolio(start: float = START_BANKROLL) -> dict:
    return {"start": start, "created": datetime.now().isoformat(timespec="seconds"), "bets": []}


def load_portfolio() -> dict:
    if PORTFOLIO.exists():
        try:
            return json.loads(PORTFOLIO.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return new_portfolio()


def save_portfolio(p: dict) -> None:
    PORTFOLIO.write_text(json.dumps(p, ensure_ascii=False, indent=1))


def balance(p: dict) -> dict:
    bets = p["bets"]
    staked_open = sum(b["stake"] for b in bets if b["status"] == "en cours")
    settled = [b for b in bets if b["status"] in ("gagné", "perdu")]
    profit = sum(b["payout"] - b["stake"] for b in settled)
    staked_settled = sum(b["stake"] for b in settled)
    won = sum(1 for b in settled if b["status"] == "gagné")
    return dict(solde=p["start"] + profit - staked_open, en_jeu=staked_open, profit=profit,
                roi=profit / staked_settled if staked_settled else 0.0, gagnes=won,
                perdus=len(settled) - won, en_cours=sum(1 for b in bets if b["status"] == "en cours"))


def place_bet(p: dict, *, home: str, away: str, comp: str, market: str, selection: str, odds: float,
              stake: float, proba: float | None = None, match_date=None, kind: str = "clubs") -> str | None:
    """Ajoute un pari. Renvoie un message d'erreur ou None."""
    if stake <= 0:
        return "La mise doit être positive."
    if odds <= 1:
        return "La cote doit être supérieure à 1."
    if stake > balance(p)["solde"] + 1e-9:
        return "Solde fictif insuffisant."
    p["bets"].append(dict(
        id=uuid.uuid4().hex[:8], cree=datetime.now().isoformat(timespec="minutes"),
        date=str(pd.Timestamp(match_date).date()) if match_date is not None else None,
        comp=comp, home=home, away=away, market=market, selection=selection, odds=float(odds),
        stake=float(stake), proba=None if proba is None else float(proba), kind=kind,
        status="en cours", payout=0.0, score=None))
    return None


def settle_manual(p: dict, bet_id: str, status: str) -> None:
    for b in p["bets"]:
        if b["id"] == bet_id and b["status"] == "en cours":
            b["status"] = status
            b["payout"] = b["stake"] * b["odds"] if status == "gagné" else (b["stake"] if status == "annulé" else 0.0)


def auto_settle(p: dict, results: pd.DataFrame, nat_results: pd.DataFrame | None = None) -> int:
    """Règle les paris dont le match est terminé (même affiche, joué après la prise du pari)."""
    n = 0
    for b in p["bets"]:
        if b["status"] != "en cours":
            continue
        src = nat_results if b.get("kind") == "nat" and nat_results is not None else results
        since = pd.Timestamp(b["date"]) - pd.Timedelta(days=1) if b.get("date") else \
            pd.Timestamp(b["cree"]).normalize() - pd.Timedelta(days=1)
        r = src[(src.home == b["home"]) & (src.away == b["away"]) & (src.date >= since)].sort_values("date")
        if r.empty:
            continue
        hg, ag = int(r.iloc[0].hg), int(r.iloc[0].ag)
        w = wins(b["market"], b["selection"], hg, ag)
        if w is None:
            continue
        b["score"] = f"{hg}-{ag}"
        b["status"] = "gagné" if w else "perdu"
        b["payout"] = b["stake"] * b["odds"] if w else 0.0
        n += 1
    return n


def bets_frame(p: dict) -> pd.DataFrame:
    if not p["bets"]:
        return pd.DataFrame()
    return pd.DataFrame(p["bets"])


def bankroll_curve(p: dict) -> pd.DataFrame:
    settled = [b for b in p["bets"] if b["status"] in ("gagné", "perdu", "annulé")]
    if not settled:
        return pd.DataFrame()
    df = pd.DataFrame(settled)
    df["t"] = pd.to_datetime(df["date"].fillna(df["cree"].str[:10]))
    df = df.sort_values("t")
    df["Bankroll (€)"] = p["start"] + (df.payout - df.stake).cumsum()
    df["n"] = range(1, len(df) + 1)
    return df[["n", "t", "Bankroll (€)"]]


# --------------------------------------------------------------------------- test de stratégie
STRATEGIES = {
    "fav": "Favori de l'appli (1X2) si proba ≥ seuil",
    "value": "Value bets 1X2 et ±2.5 (proba × cote − 1 ≥ seuil)",
    "over": "Plus de 2.5 buts si proba ≥ seuil",
    "under": "Moins de 2.5 buts si proba ≥ seuil",
    "draw": "Match nul si proba ≥ seuil",
    "outsider": "Outsider (cote ≥ 3) si proba ≥ seuil",
}


def run_strategy(hist: pd.DataFrame, results: pd.DataFrame, strategy: str, threshold: float,
                 stake_mode: str = "fixe", stake: float = 10.0, start: float = START_BANKROLL,
                 best_odds: bool = False, min_odds: float = 1.01, max_odds: float = 50.0) -> pd.DataFrame:
    """Rejoue les pronos d'avant-match de l'historique avec les vraies cotes du marché.
    stake_mode : 'fixe' (€), 'pct' (% de la bankroll), 'kelly' (Kelly/4)."""
    pre = "max" if best_odds else "o"
    cols = [f"{pre}_h", f"{pre}_d", f"{pre}_a", f"{pre}_o25", f"{pre}_u25"]
    odds = results[["date", "home", "away", *cols]].rename(
        columns=dict(zip(cols, ["c1", "cN", "c2", "co", "cu"])))
    h = hist.merge(odds, on=["date", "home", "away"], how="inner").sort_values("date")
    bank, rows = start, []
    for r in h.itertuples():
        cands = []  # (marché, sélection, proba, cote, gagné)
        tot = r.hg + r.ag
        one_x_two = [("1", r.p1, r.c1), ("N", r.pn, r.cN), ("2", r.p2, r.c2)]
        p_over = r.p_prono_buts if r.prono_buts == "+2.5" else 1 - r.p_prono_buts
        ou = [("+2.5", p_over, r.co, tot > 2), ("-2.5", 1 - p_over, r.cu, tot <= 2)]
        if strategy == "fav":
            sel, p, c = max(one_x_two, key=lambda x: x[1])
            if p >= threshold:
                cands.append(("1X2", sel, p, c, sel == r.real))
        elif strategy == "value":
            for sel, p, c in one_x_two:
                if c == c and p * c - 1 >= threshold:
                    cands.append(("1X2", sel, p, c, sel == r.real))
            for sel, p, c, w in ou:
                if c == c and p * c - 1 >= threshold:
                    cands.append(("Plus/Moins buts", sel, p, c, w))
        elif strategy in ("over", "under"):
            sel, p, c, w = ou[0] if strategy == "over" else ou[1]
            if p >= threshold:
                cands.append(("Plus/Moins buts", sel, p, c, w))
        elif strategy == "draw":
            if r.pn >= threshold:
                cands.append(("1X2", "N", r.pn, r.cN, r.real == "N"))
        elif strategy == "outsider":
            for sel, p, c in one_x_two:
                if sel != "N" and c == c and c >= 3 and p >= threshold:
                    cands.append(("1X2", sel, p, c, sel == r.real))
        for market, sel, p, c, w in cands:
            if not (c == c and min_odds <= c <= max_odds) or bank <= 0:
                continue
            if stake_mode == "fixe":
                s = stake
            elif stake_mode == "pct":
                s = bank * stake / 100
            else:
                s = bank * max(0.0, (p * (c - 1) - (1 - p)) / (c - 1)) / 4
            s = round(min(s, bank), 2)
            if s <= 0:
                continue
            gain = s * (c - 1) if w else -s
            bank += gain
            rows.append(dict(date=r.date, comp=r.comp, match=f"{r.home} – {r.away}", score=r.score,
                             marche=market, pari=sel, proba=p, cote=c, mise=s, gagne=bool(w),
                             gain=gain, bankroll=bank))
    return pd.DataFrame(rows)
