"""Téléchargement, cache et normalisation des données de matchs.

Sources (gratuites, sans clé API) :
  * football-data.co.uk  : résultats, tirs, xG (saison en cours), cotes d'ouverture/clôture,
                           calendrier des prochains matchs avec cotes (fixtures.csv).
  * openfootball (GitHub) : résultats de Ligue des champions (relie les championnats entre eux).
"""
from __future__ import annotations

import io
import re
import time
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
CACHE.mkdir(exist_ok=True)

FD_BASE = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
FD_FIXTURES = "https://www.football-data.co.uk/fixtures.csv"
OF_CL_TXT = "https://raw.githubusercontent.com/openfootball/champions-league/master/{season}/cl.txt"

# Championnats chargés. Les 2es divisions servent à évaluer correctement les promus
# (les équipes qui montent/descendent "relient" les divisions entre elles).
LEAGUES = {
    "E0": "Premier League",
    "SP1": "LaLiga",
    "I1": "Serie A",
    "D1": "Bundesliga",
    "F1": "Ligue 1",
    "P1": "Liga Portugal",
    "N1": "Eredivisie",
    "B1": "Pro League (BEL)",
    "T1": "Süper Lig",
    "SC0": "Scottish Prem.",
    "E1": "Championship",
    "SP2": "LaLiga 2",
    "I2": "Serie B",
    "D2": "2. Bundesliga",
    "F2": "Ligue 2",
}
MAIN_LEAGUES = ["F1", "E0", "SP1", "I1", "D1"]
COMPETITIONS = {**LEAGUES, "CL": "Ligue des champions"}

# Pays (codes openfootball) -> championnats où chercher l'équipe
COUNTRY_LEAGUES = {
    "ENG": ["E0", "E1"], "ESP": ["SP1", "SP2"], "ITA": ["I1", "I2"], "GER": ["D1", "D2"],
    "FRA": ["F1", "F2"], "MCO": ["F1", "F2"], "POR": ["P1"], "NED": ["N1"], "BEL": ["B1"],
    "TUR": ["T1"], "SCO": ["SC0"],
}

# Noms openfootball -> noms football-data qui ne se devinent pas automatiquement
ALIASES = {
    "fc bayern munchen": "Bayern Munich",
    "club atletico de madrid": "Ath Madrid",
    "athletic club": "Ath Bilbao",
    "fc internazionale milano": "Inter",
    "ac milan": "Milan",
    "sport lisboa e benfica": "Benfica",
    "sporting clube de portugal": "Sp Lisbon",
    "fc porto": "Porto",
    "sporting clube de braga": "Sp Braga",
    "paris saint-germain fc": "Paris SG",
    "manchester city fc": "Man City",
    "manchester united fc": "Man United",
    "newcastle united fc": "Newcastle",
    "tottenham hotspur fc": "Tottenham",
    "nottingham forest fc": "Nott'm Forest",
    "wolverhampton wanderers fc": "Wolves",
    "bayer 04 leverkusen": "Leverkusen",
    "borussia monchengladbach": "M'gladbach",
    "eintracht frankfurt": "Ein Frankfurt",
    "vfb stuttgart": "Stuttgart",
    "rb leipzig": "RB Leipzig",
    "rasenballsport leipzig": "RB Leipzig",
    "psv": "PSV Eindhoven",
    "psv eindhoven": "PSV Eindhoven",
    "afc ajax": "Ajax",
    "feyenoord rotterdam": "Feyenoord",
    "royale union saint-gilloise": "St. Gilloise",
    "club brugge kv": "Club Brugge",
    "galatasaray sk": "Galatasaray",
    "fenerbahce sk": "Fenerbahce",
    "celtic fc": "Celtic",
    "rangers fc": "Rangers",
    "olympique de marseille": "Marseille",
    "olympique lyonnais": "Lyon",
    "as monaco fc": "Monaco",
    "lille osc": "Lille",
    "stade brestois 29": "Brest",
    "ogc nice": "Nice",
    "racing club de lens": "Lens",
    "ssc napoli": "Napoli",
    "atalanta bc": "Atalanta",
    "juventus fc": "Juventus",
    "bologna fc 1909": "Bologna",
    "as roma": "Roma",
    "ss lazio": "Lazio",
    "real madrid cf": "Real Madrid",
    "fc barcelona": "Barcelona",
    "villarreal cf": "Villarreal",
    "real sociedad de futbol": "Sociedad",
    "real betis balompie": "Betis",
    "girona fc": "Girona",
    "aston villa fc": "Aston Villa",
    "arsenal fc": "Arsenal",
    "chelsea fc": "Chelsea",
    "liverpool fc": "Liverpool",
    "borussia dortmund": "Dortmund",
    "vfl wolfsburg": "Wolfsburg",
    "sc freiburg": "Freiburg",
    "fc twente": "Twente",
    "az alkmaar": "AZ Alkmaar",
}

UA = {"User-Agent": "Mozilla/5.0 (paris-foot data client)"}


# --------------------------------------------------------------------------- utilitaires
def season_codes(n: int, today: date | None = None) -> list[str]:
    """Les n dernières saisons au format football-data ('2526', '2627', ...)."""
    today = today or date.today()
    start = today.year if today.month >= 7 else today.year - 1
    out = []
    for y in range(start - n + 1, start + 1):
        out.append(f"{y % 100:02d}{(y + 1) % 100:02d}")
    return out


def _get(url: str, cache_name: str, max_age_h: float, force: bool = False) -> bytes | None:
    path = CACHE / cache_name
    if path.exists() and not force and (time.time() - path.stat().st_mtime) < max_age_h * 3600:
        return path.read_bytes()
    try:
        r = requests.get(url, headers=UA, timeout=40)
        if r.status_code == 200 and len(r.content) > 50:
            path.write_bytes(r.content)
            return r.content
    except requests.RequestException:
        pass
    return path.read_bytes() if path.exists() else None


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _parse_dates(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    d2 = pd.to_datetime(s, format="%d/%m/%y", errors="coerce")
    return d.fillna(d2)


ODDS_COLS = {
    # cotes de clôture moyennes du marché (meilleure référence de "vraie" proba)
    "oc_h": "AvgCH", "oc_d": "AvgCD", "oc_a": "AvgCA",
    "oc_o25": "AvgC>2.5", "oc_u25": "AvgC<2.5",
    # cotes d'avant-match (moyenne marché)
    "o_h": "AvgH", "o_d": "AvgD", "o_a": "AvgA",
    "o_o25": "Avg>2.5", "o_u25": "Avg<2.5",
    # meilleures cotes disponibles
    "max_h": "MaxH", "max_d": "MaxD", "max_a": "MaxA",
    "max_o25": "Max>2.5", "max_u25": "Max<2.5",
}


def _normalize_fd(raw: pd.DataFrame, comp: str) -> pd.DataFrame:
    df = pd.DataFrame()
    df["date"] = _parse_dates(raw["Date"])
    df["comp"] = comp
    df["home"] = raw["HomeTeam"].astype(str).str.strip()
    df["away"] = raw["AwayTeam"].astype(str).str.strip()
    for new, old in [("hg", "FTHG"), ("ag", "FTAG"), ("hthg", "HTHG"), ("htag", "HTAG"),
                     ("hs", "HS"), ("as_", "AS"), ("hst", "HST"), ("ast", "AST"),
                     ("hxg", "HxG"), ("axg", "AxG"), ("hc", "HC"), ("ac", "AC")]:
        df[new] = _num(raw[old]) if old in raw else np.nan
    for new, old in ODDS_COLS.items():
        df[new] = _num(raw[old]) if old in raw else np.nan
    df["neutral"] = False
    return df


# --------------------------------------------------------------------------- football-data
def load_league_history(n_seasons: int = 4, leagues=None, force: bool = False) -> pd.DataFrame:
    leagues = leagues or list(LEAGUES)
    seasons = season_codes(n_seasons)
    frames = []
    for s in seasons:
        current = s == seasons[-1]
        for code in leagues:
            content = _get(FD_BASE.format(season=s, code=code), f"fd_{s}_{code}.csv",
                           max_age_h=6 if current else 24 * 365, force=force and current)
            if not content:
                continue
            raw = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig", on_bad_lines="skip",
                              encoding_errors="replace")
            if "HomeTeam" not in raw or raw.empty:
                continue
            df = _normalize_fd(raw, code)
            df["season"] = s
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["date", "hg", "ag"])
    df = df[(df.home != "nan") & (df.away != "nan")]
    return df.sort_values("date").reset_index(drop=True)


def load_fixtures(force: bool = False) -> pd.DataFrame:
    content = _get(FD_FIXTURES, "fixtures.csv", max_age_h=3, force=force)
    if not content:
        return pd.DataFrame()
    raw = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig", on_bad_lines="skip",
                      encoding_errors="replace")
    raw = raw[raw["Div"].isin(LEAGUES)]
    frames = [_normalize_fd(g, div) for div, g in raw.groupby("Div")]
    if not frames:
        return pd.DataFrame()
    fx = pd.concat(frames, ignore_index=True)
    fx["time"] = raw["Time"].values if "Time" in raw else ""
    return fx.sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- Ligue des champions
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_DATE_RE = re.compile(r"^\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
_MATCH_RE = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}\s+)?(?P<t1>.+?)\s+\((?P<c1>[A-Z]{3})\)\s+v\s+(?P<t2>.+?)\s+\((?P<c2>[A-Z]{3})\)\s+(?P<rest>.*)$")


def parse_openfootball_txt(text: str, season_start_year: int) -> pd.DataFrame:
    rows, cur = [], None
    is_final = False
    for line in text.splitlines():
        if line.startswith("▪"):
            is_final = line.strip().endswith(", Final")  # finale = terrain neutre
            continue
        m = _DATE_RE.match(line)
        if m:
            mon, day, yr = _MONTHS[m.group(2)], int(m.group(3)), m.group(4)
            year = int(yr) if yr else (season_start_year if mon >= 7 else season_start_year + 1)
            cur = date(year, mon, day)
            continue
        m = _MATCH_RE.match(line)
        if not m or cur is None:
            continue
        rest = m.group("rest")
        scores = re.findall(r"(\d+)-(\d+)", rest)
        if not scores:
            continue
        if "a.e.t" in rest:
            par = re.search(r"\((\d+)-(\d+)", rest)
            if not par:
                continue
            hg, ag = int(par.group(1)), int(par.group(2))
        elif "pen." in rest:  # tirs au but sans prolongation mentionnée
            hg, ag = map(int, scores[1]) if len(scores) > 1 else map(int, scores[0])
        else:
            hg, ag = map(int, scores[0])
        rows.append(dict(date=pd.Timestamp(cur), t1=m.group("t1").strip(), c1=m.group("c1"),
                         t2=m.group("t2").strip(), c2=m.group("c2"), hg=hg, ag=ag, neutral=is_final))
    return pd.DataFrame(rows)


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("'", "").replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


_NOISE = {"fc", "cf", "ac", "sc", "afc", "ssc", "as", "sl", "cd", "rc", "sk", "kv", "bc", "club",
          "de", "del", "1901", "1909", "1913", "1907", "04", "05", "fk", "sv", "vfl", "vfb", "tsg",
          "1", "bv", "ud", "rcd", "ogc", "osc", "us", "ss", "acf", "calcio", "futbol", "balompie",
          "football", "the", "e", "y", "of"}


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[\s\-/]+", _norm(name)) if t and t not in _NOISE}


def match_team(of_name: str, country: str, teams_by_league: dict[str, set[str]]) -> str | None:
    key = _norm(of_name)
    if key in ALIASES:
        return ALIASES[key]
    cands = set()
    for lg in COUNTRY_LEAGUES.get(country, []):
        cands |= teams_by_league.get(lg, set())
    if not cands:
        return None
    tk = _tokens(of_name)
    best, best_score = None, 0.0
    for c in cands:
        ct = _tokens(c)
        overlap = len(tk & ct) / max(1, len(ct))
        ratio = SequenceMatcher(None, " ".join(sorted(tk)), " ".join(sorted(ct))).ratio()
        score = 0.65 * overlap + 0.35 * ratio
        if score > best_score:
            best, best_score = c, score
    return best if best_score >= 0.55 else None


def load_champions_league(teams_by_league: dict[str, set[str]], n_seasons: int = 3,
                          force: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """Matchs de C1 entre équipes couvertes par les championnats chargés."""
    frames, unmatched = [], set()
    for s in season_codes(n_seasons):
        y0 = 2000 + int(s[:2])
        tag = f"{y0}-{(y0 + 1) % 100:02d}"
        current = s == season_codes(1)[0]
        content = _get(OF_CL_TXT.format(season=tag), f"cl_{tag}.txt",
                       max_age_h=12 if current else 24 * 365, force=force and current)
        if not content:
            continue
        df = parse_openfootball_txt(content.decode("utf-8", "replace"), y0)
        if df.empty:
            continue
        df["home"] = [match_team(t, c, teams_by_league) for t, c in zip(df.t1, df.c1)]
        df["away"] = [match_team(t, c, teams_by_league) for t, c in zip(df.t2, df.c2)]
        unmatched |= {f"{t} ({c})" for t, c, h in zip(df.t1, df.c1, df.home)
                      if h is None and c in COUNTRY_LEAGUES}
        unmatched |= {f"{t} ({c})" for t, c, h in zip(df.t2, df.c2, df.away)
                      if h is None and c in COUNTRY_LEAGUES}
        df = df.dropna(subset=["home", "away"])
        df["comp"] = "CL"
        df["season"] = s
        frames.append(df[["date", "comp", "home", "away", "hg", "ag", "neutral", "season"]])
    if not frames:
        return pd.DataFrame(), sorted(unmatched)
    return pd.concat(frames, ignore_index=True), sorted(unmatched)


def load_manual_results() -> pd.DataFrame:
    """Résultats saisis à la main (ex. C1 2026-27 pas encore publiée par openfootball)."""
    p = ROOT / "data" / "resultats_manuels.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, comment="#")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["neutral"] = df.get("neutral", False)
    df["neutral"] = df["neutral"].fillna(False).astype(bool)
    return df


def load_all(n_seasons: int = 4, force: bool = False) -> tuple[pd.DataFrame, dict]:
    dom = load_league_history(n_seasons, force=force)
    teams_by_league = {lg: set(g.home) | set(g.away) for lg, g in dom.groupby("comp")}
    cl, unmatched = load_champions_league(teams_by_league, n_seasons=min(n_seasons, 3), force=force)
    man = load_manual_results()
    df = pd.concat([d for d in (dom, cl, man) if not d.empty], ignore_index=True)
    df = df.sort_values("date").reset_index(drop=True)
    info = dict(n_matches=len(df), n_cl=len(cl), last_date=df.date.max(), cl_unmatched=unmatched,
                loaded_at=datetime.now())
    return df, info
