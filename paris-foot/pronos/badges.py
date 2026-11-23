"""Drapeaux des compétitions / sélections et écussons générés (couleurs du club + monogramme).
Les logos officiels sont des marques déposées : on utilise des écussons maison."""
from __future__ import annotations

import hashlib
import html

COMP_FLAG = {
    "E0": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "E1": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "SP1": "🇪🇸", "SP2": "🇪🇸", "I1": "🇮🇹", "I2": "🇮🇹", "D1": "🇩🇪", "D2": "🇩🇪",
    "F1": "🇫🇷", "F2": "🇫🇷", "P1": "🇵🇹", "N1": "🇳🇱", "B1": "🇧🇪", "T1": "🇹🇷", "SC0": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "G1": "🇬🇷",
    "AUT": "🇦🇹", "SWZ": "🇨🇭", "DNK": "🇩🇰", "NOR": "🇳🇴", "SWE": "🇸🇪", "POL": "🇵🇱", "ROU": "🇷🇴",
    "CL": "⭐", "EL": "🟠", "ECL": "🟢",
    "CDM": "🏆", "CONTINENTAL": "🌍", "QUALIF": "🎯", "NATIONS": "🛡️", "AMICAL": "🤝", "AUTRE": "⚽",
}

SHORT = {
    "E0": "Premier League", "SP1": "LaLiga", "I1": "Serie A", "D1": "Bundesliga", "F1": "Ligue 1",
    "CL": "Champions League", "EL": "Europa League", "ECL": "Conference League",
}

NATION_FLAG = {
    "France": "🇫🇷", "Spain": "🇪🇸", "Germany": "🇩🇪", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Italy": "🇮🇹", "Portugal": "🇵🇹",
    "Netherlands": "🇳🇱", "Belgium": "🇧🇪", "Croatia": "🇭🇷", "Switzerland": "🇨🇭", "Denmark": "🇩🇰",
    "Austria": "🇦🇹", "Norway": "🇳🇴", "Sweden": "🇸🇪", "Poland": "🇵🇱", "Czech Republic": "🇨🇿", "Serbia": "🇷🇸",
    "Turkey": "🇹🇷", "Ukraine": "🇺🇦", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Republic of Ireland": "🇮🇪",
    "Northern Ireland": "🇬🇧", "Hungary": "🇭🇺", "Romania": "🇷🇴", "Greece": "🇬🇷", "Slovakia": "🇸🇰",
    "Slovenia": "🇸🇮", "Albania": "🇦🇱", "Georgia": "🇬🇪", "Finland": "🇫🇮", "Iceland": "🇮🇸", "Bosnia and Herzegovina": "🇧🇦",
    "North Macedonia": "🇲🇰", "Montenegro": "🇲🇪", "Bulgaria": "🇧🇬", "Israel": "🇮🇱", "Kosovo": "🇽🇰",
    "Argentina": "🇦🇷", "Brazil": "🇧🇷", "Uruguay": "🇺🇾", "Colombia": "🇨🇴", "Ecuador": "🇪🇨", "Chile": "🇨🇱",
    "Peru": "🇵🇪", "Paraguay": "🇵🇾", "Venezuela": "🇻🇪", "Bolivia": "🇧🇴", "United States": "🇺🇸", "Mexico": "🇲🇽",
    "Canada": "🇨🇦", "Costa Rica": "🇨🇷", "Panama": "🇵🇦", "Jamaica": "🇯🇲", "Honduras": "🇭🇳",
    "Morocco": "🇲🇦", "Algeria": "🇩🇿", "Tunisia": "🇹🇳", "Egypt": "🇪🇬", "Senegal": "🇸🇳", "Ivory Coast": "🇨🇮",
    "Nigeria": "🇳🇬", "Cameroon": "🇨🇲", "Ghana": "🇬🇭", "Mali": "🇲🇱", "South Africa": "🇿🇦", "DR Congo": "🇨🇩",
    "Burkina Faso": "🇧🇫", "Guinea": "🇬🇳", "Cape Verde": "🇨🇻", "Gabon": "🇬🇦", "Benin": "🇧🇯", "Comoros": "🇰🇲",
    "Japan": "🇯🇵", "South Korea": "🇰🇷", "Australia": "🇦🇺", "Iran": "🇮🇷", "Saudi Arabia": "🇸🇦", "Qatar": "🇶🇦",
    "Iraq": "🇮🇶", "Jordan": "🇯🇴", "United Arab Emirates": "🇦🇪", "Uzbekistan": "🇺🇿", "China PR": "🇨🇳",
    "New Zealand": "🇳🇿", "Haiti": "🇭🇹", "Curaçao": "🇨🇼",
}

# couleurs principales (fond, texte) et monogramme des clubs les plus suivis
CLUB = {
    "Paris SG": ("#004170", "#da291c", "PSG"), "Marseille": ("#2faee0", "#ffffff", "OM"),
    "Lyon": ("#ffffff", "#1d3e8a", "OL"), "Monaco": ("#e2001a", "#ffffff", "ASM"), "Lille": ("#e01e13", "#1f2a5a", "LOSC"),
    "Lens": ("#ffd100", "#e2001a", "RCL"), "Nice": ("#c8102e", "#111111", "OGCN"), "Rennes": ("#e13327", "#111111", "SRFC"),
    "Strasbourg": ("#0057a8", "#ffffff", "RCSA"), "Nantes": ("#fcd405", "#0b7a3b", "FCN"), "Toulouse": ("#5b2c83", "#ffffff", "TFC"),
    "Brest": ("#e30613", "#ffffff", "SB29"), "Paris FC": ("#1b2a4a", "#9ec5e8", "PFC"),
    "Real Madrid": ("#ffffff", "#c9a227", "RMA"), "Barcelona": ("#a50044", "#004d98", "FCB"),
    "Ath Madrid": ("#cb3524", "#ffffff", "ATM"), "Sevilla": ("#ffffff", "#d81e05", "SFC"), "Betis": ("#00954c", "#ffffff", "RBB"),
    "Villarreal": ("#ffe667", "#005187", "VIL"), "Sociedad": ("#0067b1", "#ffffff", "RSO"), "Ath Bilbao": ("#ee2523", "#ffffff", "ATH"),
    "Man City": ("#6cabdd", "#1c2c5b", "MCI"), "Man United": ("#da291c", "#fbe122", "MUN"), "Liverpool": ("#c8102e", "#f6eb61", "LIV"),
    "Arsenal": ("#ef0107", "#ffffff", "ARS"), "Chelsea": ("#034694", "#ffffff", "CHE"), "Tottenham": ("#ffffff", "#132257", "TOT"),
    "Newcastle": ("#241f20", "#ffffff", "NEW"), "Aston Villa": ("#670e36", "#95bfe5", "AVL"), "Brighton": ("#0057b8", "#ffffff", "BHA"),
    "West Ham": ("#7a263a", "#1bb1e7", "WHU"), "Everton": ("#003399", "#ffffff", "EVE"),
    "Bayern Munich": ("#dc052d", "#ffffff", "FCB"), "Dortmund": ("#fde100", "#000000", "BVB"), "Leverkusen": ("#e32221", "#000000", "B04"),
    "RB Leipzig": ("#ffffff", "#dd0741", "RBL"), "Stuttgart": ("#ffffff", "#e32219", "VFB"), "Ein Frankfurt": ("#000000", "#e1000f", "SGE"),
    "Inter": ("#010e80", "#000000", "INT"), "Milan": ("#fb090b", "#000000", "ACM"), "Juventus": ("#ffffff", "#000000", "JUV"),
    "Napoli": ("#12a0d7", "#ffffff", "NAP"), "Roma": ("#8e1f2f", "#f0bc42", "ROM"), "Lazio": ("#87d8f7", "#ffffff", "LAZ"),
    "Atalanta": ("#1e71b8", "#000000", "ATA"), "Fiorentina": ("#482e92", "#ffffff", "FIO"), "Bologna": ("#1a2f48", "#a21c26", "BOL"),
    "Benfica": ("#e83030", "#ffffff", "SLB"), "Porto": ("#00428c", "#ffffff", "FCP"), "Sp Lisbon": ("#008057", "#ffffff", "SCP"),
    "Ajax": ("#ffffff", "#d2122e", "AJA"), "PSV Eindhoven": ("#ed1c24", "#ffffff", "PSV"), "Feyenoord": ("#e30613", "#ffffff", "FEY"),
    "Celtic": ("#018749", "#ffffff", "CEL"), "Rangers": ("#1b458f", "#ffffff", "RAN"), "Galatasaray": ("#a90432", "#fdb912", "GS"),
    "Fenerbahce": ("#163962", "#ffed00", "FB"), "Besiktas": ("#000000", "#ffffff", "BJK"), "Club Brugge": ("#0074c8", "#000000", "CLB"),
}


def comp_label(code: str, names: dict) -> str:
    return f"{COMP_FLAG.get(code, '⚽')} {SHORT.get(code, names.get(code, code))}"


def team_text(team: str, national: bool = False) -> str:
    """Pour les listes déroulantes (texte brut)."""
    return f"{NATION_FLAG.get(team, '🏳️')} {team}" if national else team


def _auto(team: str):
    h = hashlib.md5(team.encode()).digest()
    hue = h[0] * 360 // 256
    words = [w for w in team.replace("'", " ").split() if w.lower() not in ("fc", "cf", "sc", "ac")]
    if len(words) >= 2:
        mono = (words[0][0] + words[1][:2]).upper()
    else:
        mono = (words[0] if words else team)[:3].upper()
    return f"hsl({hue},55%,38%)", "#ffffff", mono


def crest(team: str, national: bool = False, size: int = 34) -> str:
    """Écusson HTML (cercle aux couleurs du club, ou drapeau pour une sélection)."""
    e = html.escape
    if national:
        return (f'<span class="pf-crest flag" style="width:{size}px;height:{size}px;font-size:{int(size*0.72)}px">'
                f'{NATION_FLAG.get(team, "🏳️")}</span>')
    bg, fg, mono = CLUB.get(team, _auto(team))
    fs = int(size * (0.30 if len(mono) <= 3 else 0.24))
    return (f'<span class="pf-crest" style="width:{size}px;height:{size}px;font-size:{fs}px;'
            f'background:linear-gradient(145deg,{bg} 0%,{bg} 74%,{fg} 74%,{fg} 100%);color:{fg if bg != "#ffffff" else fg};'
            f'--pf-txt:{"#0b1220" if bg in ("#ffffff", "#fde100", "#ffe667", "#ffd100", "#fcd405", "#87d8f7", "#6cabdd") else "#ffffff"}">'
            f'<b>{e(mono)}</b></span>')
