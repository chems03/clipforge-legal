"""API-Football (api-sports.io) : blessés/suspendus, compos officielles, cotes réelles, meilleurs buteurs.

Clé : variable d'environnement API_FOOTBALL_KEY (sur Streamlit Cloud : Settings → Secrets).
Offre gratuite = 100 requêtes/jour : tout est mis en cache et un compteur bloque à MAX_PER_DAY.
Sans clé, l'appli fonctionne comme avant (tout ce module renvoie des résultats vides).
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

import numpy as np
import pandas as pd
import requests

from .data import CACHE, _norm, _tokens

BASE = "https://v3.football.api-sports.io"
MAX_PER_DAY = 90
USAGE = CACHE / "apifootball_usage.json"
ACACHE = CACHE / "apifootball"
ACACHE.mkdir(exist_ok=True)

# identifiants API-Football des compétitions -> nos codes
API_LEAGUES = {
    61: "F1", 39: "E0", 140: "SP1", 135: "I1", 78: "D1", 94: "P1", 88: "N1", 144: "B1", 203: "T1", 179: "SC0",
    197: "G1", 218: "AUT", 207: "SWZ", 119: "DNK", 103: "NOR", 113: "SWE", 106: "POL", 283: "ROU",
    40: "E1", 141: "SP2", 136: "I2", 79: "D2", 62: "F2", 2: "CL", 3: "EL", 848: "ECL",
}
CUP_IDS = {2: "CL", 3: "EL", 848: "ECL"}
SCORER_LEAGUES = [61, 39, 140, 135, 78, 94, 88]   # meilleurs buteurs récupérés (1 requête chacun / jour)

ALIASES = {
    "paris saint germain": "Paris SG", "manchester city": "Man City", "manchester united": "Man United",
    "bayern munchen": "Bayern Munich", "bayern munich": "Bayern Munich", "atletico madrid": "Ath Madrid",
    "athletic club": "Ath Bilbao", "real betis": "Betis", "real sociedad": "Sociedad", "inter": "Inter",
    "ac milan": "Milan", "as roma": "Roma", "borussia dortmund": "Dortmund", "bayer leverkusen": "Leverkusen",
    "borussia monchengladbach": "M'gladbach", "eintracht frankfurt": "Ein Frankfurt", "rb leipzig": "RB Leipzig",
    "sporting cp": "Sp Lisbon", "sporting lisbon": "Sp Lisbon", "sc braga": "Sp Braga", "psv eindhoven": "PSV Eindhoven",
    "nottingham forest": "Nott'm Forest", "wolverhampton wanderers": "Wolves", "newcastle": "Newcastle",
    "tottenham": "Tottenham", "olympiakos piraeus": "Olympiakos", "fc copenhagen": "FC Copenhagen",
    "union st gilloise": "St. Gilloise", "red bull salzburg": "Salzburg", "stade brestois 29": "Brest",
    "paris fc": "Paris FC", "fenerbahce": "Fenerbahce", "galatasaray": "Galatasaray", "besiktas": "Besiktas",
}


class APIError(RuntimeError):
    pass


def api_key() -> str | None:
    k = os.environ.get("API_FOOTBALL_KEY", "").strip()
    return k or None


def enabled() -> bool:
    return api_key() is not None


def usage_today() -> int:
    try:
        u = json.loads(USAGE.read_text())
        return int(u.get(str(date.today()), 0))
    except (OSError, ValueError):
        return 0


def _count():
    try:
        u = json.loads(USAGE.read_text())
    except (OSError, ValueError):
        u = {}
    u = {str(date.today()): int(u.get(str(date.today()), 0)) + 1}
    USAGE.write_text(json.dumps(u))


def call(endpoint: str, params: dict, ttl_h: float) -> list:
    """Appel mis en cache. Renvoie la liste 'response' (toutes pages) ; [] si indisponible."""
    if not enabled():
        return []
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", endpoint + "_" + "_".join(f"{k}-{v}" for k, v in sorted(params.items())))
    f = ACACHE / f"{key}.json"
    if f.exists() and time.time() - f.stat().st_mtime < ttl_h * 3600:
        return json.loads(f.read_text())
    out, page = [], 1
    while True:
        if usage_today() >= MAX_PER_DAY:
            break
        q = dict(params, **({"page": page} if page > 1 else {}))
        try:
            r = requests.get(f"{BASE}/{endpoint}", params=q, timeout=25,
                             headers={"x-apisports-key": api_key()})
            _count()
            data = r.json()
        except (requests.RequestException, ValueError):
            break
        errs = data.get("errors")
        if errs and (isinstance(errs, dict) and errs or isinstance(errs, list) and errs):
            if f.exists():
                return json.loads(f.read_text())
            raise APIError(str(errs))
        out += data.get("response", [])
        paging = data.get("paging") or {}
        if page >= int(paging.get("total", 1) or 1) or page >= 5:
            break
        page += 1
    f.write_text(json.dumps(out))
    return out


def season_year(d: date | None = None) -> int:
    d = d or date.today()
    return d.year if d.month >= 7 else d.year - 1


# --------------------------------------------------------------------------- correspondance des noms
def map_team(name: str, candidates) -> str | None:
    n = _norm(name)
    if n in ALIASES and ALIASES[n] in candidates:
        return ALIASES[n]
    by_norm = {_norm(c): c for c in candidates}
    if n in by_norm:
        return by_norm[n]
    tk = _tokens(name)
    best, score = None, 0.0
    for c in candidates:
        ct = _tokens(c)
        ov = len(tk & ct) / max(1, min(len(tk), len(ct)))
        rt = SequenceMatcher(None, n, _norm(c)).ratio()
        s = 0.6 * ov + 0.4 * rt
        if s > score:
            best, score = c, s
    return best if score >= 0.72 else None


# --------------------------------------------------------------------------- matchs, blessés, compos, cotes
def fixtures(days: int = 3) -> pd.DataFrame:
    rows = []
    for i in range(days):
        d = date.today() + timedelta(days=i)
        for f in call("fixtures", {"date": str(d), "timezone": "Europe/Paris"}, ttl_h=3 if i == 0 else 8):
            lid = f["league"]["id"]
            if lid not in API_LEAGUES:
                continue
            rows.append(dict(id=f["fixture"]["id"], date=pd.Timestamp(f["fixture"]["date"][:10]),
                             time=f["fixture"]["date"][11:16], comp=API_LEAGUES[lid],
                             home_api=f["teams"]["home"]["name"], away_api=f["teams"]["away"]["name"],
                             home_id=f["teams"]["home"]["id"], away_id=f["teams"]["away"]["id"],
                             status=f["fixture"]["status"]["short"]))
    return pd.DataFrame(rows)


def injuries(days: int = 3) -> pd.DataFrame:
    rows = []
    for i in range(days):
        d = date.today() + timedelta(days=i)
        for it in call("injuries", {"date": str(d), "timezone": "Europe/Paris"}, ttl_h=6):
            rows.append(dict(fixture=it["fixture"]["id"], team_api=it["team"]["name"], team_id=it["team"]["id"],
                             player=it["player"]["name"], player_id=it["player"]["id"],
                             type=it["player"].get("type") or "", reason=it["player"].get("reason") or ""))
    return pd.DataFrame(rows).drop_duplicates(["fixture", "player_id"]) if rows else pd.DataFrame()


def lineups(fixture_id: int) -> list[dict]:
    """Compos officielles (publiées ~1 h avant le coup d'envoi)."""
    res = call("fixtures/lineups", {"fixture": fixture_id}, ttl_h=0.25)
    return [dict(team=x["team"]["name"], formation=x.get("formation"), coach=(x.get("coach") or {}).get("name"),
                 xi=[p["player"]["name"] for p in x.get("startXI", [])],
                 subs=[p["player"]["name"] for p in x.get("substitutes", [])]) for x in res]


def cup_odds(days: int = 3) -> pd.DataFrame:
    """Vraies cotes (Bet365 si dispo) des matchs de C1/C3/C4 des prochains jours."""
    rows = []
    yr = season_year()
    for i in range(days):
        d = date.today() + timedelta(days=i)
        for lid in CUP_IDS:
            for o in call("odds", {"league": lid, "season": yr, "date": str(d), "bookmaker": 8}, ttl_h=4):
                vals = {}
                for bk in o.get("bookmakers", [])[:1]:
                    for bet in bk.get("bets", []):
                        for v in bet.get("values", []):
                            vals[(bet["id"], str(v["value"]))] = float(v["odd"])
                rows.append(dict(id=o["fixture"]["id"], o_h=vals.get((1, "Home")), o_d=vals.get((1, "Draw")),
                                 o_a=vals.get((1, "Away")), o_o25=vals.get((5, "Over 2.5")),
                                 o_u25=vals.get((5, "Under 2.5"))))
    return pd.DataFrame(rows)


def top_scorers() -> pd.DataFrame:
    """Meilleurs buteurs des grands championnats (buts, minutes, penaltys) -> format data/joueurs.csv."""
    rows = []
    yr = season_year()
    for lid in SCORER_LEAGUES:
        for it in call("players/topscorers", {"league": lid, "season": yr}, ttl_h=24):
            stt = (it.get("statistics") or [{}])[0]
            g = stt.get("goals") or {}
            rows.append(dict(team_api=(stt.get("team") or {}).get("name"), comp=API_LEAGUES[lid],
                             joueur=it["player"]["name"], matchs=(stt.get("games") or {}).get("appearences"),
                             minutes=(stt.get("games") or {}).get("minutes"), buts=g.get("total") or 0,
                             penaltys=(stt.get("penalty") or {}).get("scored") or 0))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- assemblage pour l'appli
def enrich(model_teams, team_league: dict) -> dict:
    """Tout ce qu'il faut à l'appli, en noms d'équipes du modèle.
    Renvoie {fixtures, injuries, odds, scorers, ok, error}."""
    out = dict(fixtures=pd.DataFrame(), injuries=pd.DataFrame(), odds=pd.DataFrame(), scorers=pd.DataFrame(),
               ok=False, error=None)
    if not enabled():
        return out
    try:
        fx = fixtures()
        teams = set(model_teams)
        if not fx.empty:
            fx["home"] = [map_team(n, teams) for n in fx.home_api]
            fx["away"] = [map_team(n, teams) for n in fx.away_api]
        inj = injuries()
        if not inj.empty and not fx.empty:
            idmap = {**dict(zip(fx.home_id, fx.home)), **dict(zip(fx.away_id, fx.away))}
            inj["team"] = inj.team_id.map(idmap)
        od = cup_odds()
        if not od.empty and not fx.empty:
            od = od.merge(fx[["id", "date", "home", "away"]], on="id", how="inner")
        sc = top_scorers()
        if not sc.empty:
            sc["equipe"] = [map_team(n, [t for t in teams if team_league.get(t) == c]) if n else None
                            for n, c in zip(sc.team_api, sc.comp)]
        out.update(fixtures=fx, injuries=inj, odds=od, scorers=sc, ok=True)
    except APIError as e:
        out["error"] = str(e)
    return out


def injury_adjustment(team: str, absent: list[str], scorers: pd.DataFrame, results: pd.DataFrame) -> tuple[float, float]:
    """Impact estimé des absents : (variation attaque, variation défense) en fraction.
    Attaque : part des buts de l'équipe marqués par les absents × 0,6 (le remplaçant compense en partie).
    Défense : −1,5 % par autre absent, plafonné à −8 %."""
    if not absent:
        return 0.0, 0.0
    from .scorers import team_season_goals
    goals, _ = team_season_goals(results, team)
    sc = scorers[scorers.equipe == team] if not scorers.empty and "equipe" in scorers else pd.DataFrame()
    abs_norm = {_norm(a) for a in absent}
    lost = 0.0
    others = 0
    for a in absent:
        hit = sc[[_norm(j) == _norm(a) or _norm(j).split()[-1] == _norm(a).split()[-1] for j in sc.joueur]] \
            if not sc.empty else pd.DataFrame()
        if not hit.empty and goals > 0:
            lost += float(hit.iloc[0].buts) / goals
        else:
            others += 1
    att = -min(0.25, 0.6 * lost)
    dfn = -min(0.08, 0.015 * others)
    _ = abs_norm
    return att, dfn
