"""Habillage visuel : thème, cartes de match, barre de probabilités (pensé d'abord pour le téléphone)."""
from __future__ import annotations

import html

import streamlit as st

GREEN, GREY, BLUE = "#22c55e", "#64748b", "#3b82f6"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea, select {
  font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}
/* masque les éléments Streamlit : appli "propre" */
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], .stDeployButton,
[data-testid="stAppDeployButton"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent; height: 0; }
.block-container { padding-top: 1.2rem !important; padding-bottom: 4rem !important; max-width: 1100px; }
@media (max-width: 640px) { .block-container { padding-left: .8rem !important; padding-right: .8rem !important; } }
h1, h2, h3 { letter-spacing: -0.02em; font-weight: 800 !important; }
h2 { font-size: 1.45rem !important; }

/* barre de marque */
.pf-brand { display:flex; align-items:center; gap:.6rem; margin:.2rem 0 .8rem 0; }
.pf-logo { width:40px; height:40px; border-radius:12px; display:grid; place-items:center; font-size:22px;
  background: linear-gradient(135deg,#16a34a,#22c55e); box-shadow:0 6px 18px rgba(34,197,94,.35); }
.pf-title { font-weight:800; font-size:1.25rem; line-height:1.1; }
.pf-sub { font-size:.75rem; color:#94a3b8; }

/* cartes */
.pf-card { background:#111827; border:1px solid #1f2937; border-radius:16px; padding:14px 16px; margin:0 0 10px 0; }
.pf-card:hover { border-color:#334155; }
.pf-meta { display:flex; justify-content:space-between; font-size:.72rem; color:#94a3b8; text-transform:uppercase;
  letter-spacing:.04em; margin-bottom:8px; }
.pf-teams { display:grid; grid-template-columns: 1fr auto 1fr; align-items:center; gap:8px; }
.pf-team { font-weight:700; font-size:.95rem; display:flex; flex-direction:column; align-items:center;
  text-align:center; gap:6px; line-height:1.15; }
.pf-team.r { text-align:center; }
.pf-crest { display:inline-grid; place-items:center; border-radius:50%; flex:none;
  border:2px solid rgba(255,255,255,.18); box-shadow:0 4px 14px rgba(0,0,0,.45); }
.pf-crest b { color:var(--pf-txt,#fff); font-weight:800; letter-spacing:-.03em; text-shadow:0 1px 2px rgba(0,0,0,.25); }
.pf-crest.flag { background:#0b1220; border-color:#1f2937; }
/* pastilles (menu, championnats, compétitions) */
[data-testid="stPills"] button, [data-testid="stButtonGroup"] button { border-radius:99px !important;
  border:1px solid #1f2937 !important; background:#111827 !important; font-weight:600 !important; }
[data-testid="stPills"] button[aria-checked="true"], [data-testid="stPills"] button[kind$="Active"],
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[kind$="Active"] {
  background:rgba(34,197,94,.16) !important; border-color:#22c55e !important; color:#4ade80 !important; }
.pf-score { background:#0b1220; border:1px solid #1f2937; border-radius:10px; padding:4px 10px; font-weight:800;
  font-variant-numeric: tabular-nums; text-align:center; min-width:56px; }
.pf-score small { display:block; font-size:.6rem; color:#94a3b8; font-weight:500; }
.pf-bar { display:flex; height:8px; border-radius:99px; overflow:hidden; margin:12px 0 6px 0; background:#1f2937; }
.pf-bar div { height:100%; }
.pf-probs { display:flex; justify-content:space-between; font-size:.8rem; font-variant-numeric: tabular-nums; }
.pf-probs b { font-weight:700; }
.pf-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
.pf-chip { font-size:.72rem; padding:3px 9px; border-radius:99px; background:#0b1220; border:1px solid #1f2937; color:#cbd5e1; }
.pf-chip.v { background:rgba(34,197,94,.12); border-color:rgba(34,197,94,.45); color:#4ade80; font-weight:700; }

/* grand tableau d'affichage (analyse) */
.pf-hero { background: radial-gradient(120% 140% at 50% 0%, #14532d 0%, #0f172a 55%); border:1px solid #1f2937;
  border-radius:20px; padding:18px; margin:6px 0 14px 0; }
.pf-hero .pf-team { font-size:1.15rem; }
.pf-hero .pf-score { font-size:1.4rem; padding:6px 14px; }
.pf-kpis { display:grid; grid-template-columns: repeat(3, 1fr); gap:8px; margin-top:12px; }
.pf-kpi { background:rgba(11,18,32,.75); border:1px solid #1f2937; border-radius:12px; padding:8px; text-align:center; }
.pf-kpi .l { font-size:.68rem; color:#94a3b8; text-transform:uppercase; letter-spacing:.04em; }
.pf-kpi .v { font-size:1.25rem; font-weight:800; font-variant-numeric: tabular-nums; }
.pf-kpi .o { font-size:.7rem; color:#94a3b8; }
@media (max-width: 640px) { .pf-kpis { grid-template-columns: repeat(3, 1fr); } .pf-kpi .v { font-size:1.05rem; } }

/* éléments Streamlit plus "app" */
[data-testid="stMetric"] { background:#111827; border:1px solid #1f2937; border-radius:14px; padding:10px 12px; }
[data-testid="stExpander"] details { border-radius:14px !important; border-color:#1f2937 !important; background:#0f172a; }
.stTabs [data-baseweb="tab-list"] { gap:4px; overflow-x:auto; }
.stTabs [data-baseweb="tab"] { background:#111827; border-radius:99px; padding:6px 14px; border:1px solid #1f2937; }
.stTabs [aria-selected="true"] { background:rgba(34,197,94,.15) !important; border-color:#22c55e !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }
.stButton button { border-radius:12px; font-weight:600; }
[data-testid="stDataFrame"] { border-radius:12px; overflow:hidden; }
.pf-day { font-weight:800; font-size:.85rem; color:#94a3b8; margin:16px 0 8px 2px; text-transform:capitalize; }
.pf-foot { font-size:.7rem; color:#64748b; text-align:center; margin-top:28px; }

/* titres de page */
.pf-page { margin:.6rem 0 1rem 0; }
.pf-page h1 { font-size:1.55rem !important; margin:0 !important; padding:0 !important; font-weight:800 !important; }
.pf-page p { margin:.25rem 0 0 0; color:#94a3b8; font-size:.88rem; line-height:1.35; }
.pf-section { font-size:.78rem; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:.06em;
  margin:18px 0 8px 2px; }

/* chiffres clés */
.pf-kgrid { display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:8px; margin:4px 0 12px 0; }
.pf-k { background:#111827; border:1px solid #1f2937; border-radius:14px; padding:12px 14px; }
.pf-k .l { font-size:.7rem; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em; }
.pf-k .v { font-size:1.45rem; font-weight:800; font-variant-numeric:tabular-nums; margin-top:2px; }
.pf-k .s { font-size:.75rem; color:#94a3b8; margin-top:2px; }
.pf-k.good .v { color:#4ade80; } .pf-k.bad .v { color:#f87171; }

/* listes de marchés */
.pf-list { background:#111827; border:1px solid #1f2937; border-radius:14px; padding:6px 12px; margin:0 0 10px 0; }
.pf-list .t { font-size:.72rem; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em;
  padding:6px 0 4px 0; }
.pf-row { display:grid; grid-template-columns: minmax(70px, 1.2fr) 2fr 52px 52px; align-items:center; gap:10px;
  padding:7px 0; border-top:1px solid #1a2333; font-size:.85rem; font-variant-numeric:tabular-nums; }
.pf-row:first-of-type { border-top:none; }
.pf-row .n { font-weight:600; color:#e5e7eb; }
.pf-row .b { height:6px; border-radius:99px; background:#1f2937; overflow:hidden; }
.pf-row .b i { display:block; height:100%; background:linear-gradient(90deg,#16a34a,#22c55e); border-radius:99px; }
.pf-row .p { text-align:right; font-weight:700; }
.pf-row .o { text-align:right; color:#94a3b8; font-size:.78rem; }

/* lignes de paris (simulateur / value) */
.pf-bet { display:flex; justify-content:space-between; gap:10px; align-items:center; background:#111827;
  border:1px solid #1f2937; border-radius:14px; padding:10px 14px; margin:0 0 8px 0; }
.pf-bet .m { font-weight:700; font-size:.92rem; }
.pf-bet .d { color:#94a3b8; font-size:.8rem; margin-top:2px; }
.pf-bet .r { text-align:right; font-weight:800; font-variant-numeric:tabular-nums; white-space:nowrap; }
.pf-bet .r small { display:block; color:#94a3b8; font-weight:500; font-size:.72rem; }
.pf-tag { display:inline-block; font-size:.68rem; font-weight:700; padding:2px 8px; border-radius:99px; margin-right:6px; }
.pf-tag.g { background:rgba(34,197,94,.15); color:#4ade80; } .pf-tag.r { background:rgba(248,113,113,.15); color:#f87171; }
.pf-tag.w { background:rgba(148,163,184,.15); color:#cbd5e1; } .pf-tag.y { background:rgba(250,204,21,.15); color:#facc15; }
/* ---------- affiches déroulantes ---------- */
details.pf-acc { background:linear-gradient(180deg,rgba(17,24,39,.92),rgba(13,19,33,.92)); border:1px solid #1f2937;
  border-radius:18px; margin:0 0 10px 0; overflow:hidden; transition:border-color .2s, box-shadow .2s; }
details.pf-acc[open] { border-color:rgba(34,197,94,.55); box-shadow:0 10px 30px rgba(0,0,0,.35), 0 0 0 1px rgba(34,197,94,.15) inset; }
details.pf-acc summary { list-style:none; cursor:pointer; padding:12px 14px; -webkit-tap-highlight-color:transparent; }
details.pf-acc summary::-webkit-details-marker { display:none; }
.pf-sum { display:grid; grid-template-columns: 44px 1fr auto; gap:10px; align-items:center; }
.pf-time { font-weight:800; font-size:.85rem; color:#e5e7eb; text-align:center; line-height:1.1; }
.pf-time small { display:block; font-size:.62rem; color:#64748b; font-weight:600; margin-top:2px; }
.pf-tm { display:flex; align-items:center; gap:8px; font-weight:700; font-size:.92rem; line-height:1.25; }
.pf-tm + .pf-tm { margin-top:6px; }
.pf-tm .pf-crest { width:24px !important; height:24px !important; font-size:8px !important; border-width:1px; box-shadow:none; }
.pf-pp { display:flex; flex-direction:column; gap:6px; align-items:flex-end; font-variant-numeric:tabular-nums; }
.pf-pp span { font-size:.8rem; font-weight:800; min-width:38px; text-align:center; padding:2px 6px; border-radius:8px;
  background:#0b1220; border:1px solid #1f2937; }
.pf-pp span.hi { background:rgba(34,197,94,.14); border-color:rgba(34,197,94,.45); color:#4ade80; }
.pf-chev { color:#64748b; font-size:.75rem; text-align:center; margin-top:6px; transition:transform .25s; }
details.pf-acc[open] .pf-chev { transform:rotate(180deg); }
.pf-body { padding:4px 14px 14px 14px; animation:pfIn .28s ease-out; }
@keyframes pfIn { from { opacity:0; transform:translateY(-6px); } to { opacity:1; transform:none; } }
.pf-mini { display:grid; grid-template-columns: repeat(3, 1fr); gap:6px; margin-top:10px; }
.pf-mini div { background:#0b1220; border:1px solid #1f2937; border-radius:12px; padding:8px; text-align:center; }
.pf-mini b { display:block; font-size:1rem; font-variant-numeric:tabular-nums; }
.pf-mini small { color:#94a3b8; font-size:.66rem; text-transform:uppercase; letter-spacing:.04em; }
.pf-scores { display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }
.pf-scores span { font-size:.78rem; padding:4px 9px; border-radius:10px; background:#0b1220; border:1px solid #1f2937; }
.pf-scores span b { margin-right:4px; }

.pf-link { display:block; text-align:center; margin-top:12px; padding:10px; border-radius:12px; font-weight:700;
  font-size:.86rem; color:#0b1220 !important; text-decoration:none !important;
  background:linear-gradient(90deg,#22c55e,#4ade80); }

/* ---------- match à la une ---------- */
.pf-feat { position:relative; border-radius:22px; padding:16px; margin:4px 0 14px 0; overflow:hidden;
  background: radial-gradient(130% 120% at 0% 0%, rgba(34,197,94,.35) 0%, rgba(15,23,42,0) 55%),
              radial-gradient(120% 120% at 100% 100%, rgba(59,130,246,.30) 0%, rgba(15,23,42,0) 55%), #0f172a;
  border:1px solid rgba(255,255,255,.08); box-shadow:0 18px 40px rgba(0,0,0,.45); }
.pf-feat .lbl { font-size:.66rem; font-weight:800; letter-spacing:.12em; color:#4ade80; text-transform:uppercase; }

/* ---------- tickets combinés ---------- */
.pf-ticket { position:relative; border-radius:20px; margin:0 0 14px 0; overflow:hidden;
  background:linear-gradient(160deg,#111827 0%,#0b1220 100%); border:1px solid #1f2937; }
.pf-ticket .hd { display:flex; justify-content:space-between; align-items:center; padding:14px 16px;
  background:linear-gradient(90deg, var(--c1), var(--c2)); }
.pf-ticket .hd b { font-size:1.02rem; font-weight:800; color:#fff; }
.pf-ticket .hd span { font-size:.72rem; color:rgba(255,255,255,.85); }
.pf-ticket .lg { display:flex; justify-content:space-between; gap:10px; padding:10px 16px; border-top:1px dashed #263244; }
.pf-ticket .lg .m { font-weight:700; font-size:.88rem; }
.pf-ticket .lg .d { color:#94a3b8; font-size:.76rem; margin-top:2px; }
.pf-ticket .lg .o { font-weight:800; font-variant-numeric:tabular-nums; text-align:right; }
.pf-ticket .lg .o small { display:block; color:#94a3b8; font-weight:500; font-size:.7rem; }
.pf-ticket .ft { display:grid; grid-template-columns:repeat(3,1fr); border-top:1px solid #1f2937; }
.pf-ticket .ft div { padding:10px; text-align:center; }
.pf-ticket .ft div + div { border-left:1px solid #1f2937; }
.pf-ticket .ft b { display:block; font-size:1.15rem; font-weight:800; font-variant-numeric:tabular-nums; }
.pf-ticket .ft small { color:#94a3b8; font-size:.66rem; text-transform:uppercase; letter-spacing:.05em; }
.pf-ticket::before, .pf-ticket::after { content:""; position:absolute; width:18px; height:18px; border-radius:50%;
  background:#0b1220; top:58px; } .pf-ticket::before { left:-9px; } .pf-ticket::after { right:-9px; }

/* bouton discret sous les cartes */
.stButton button[kind="tertiary"] { color:#4ade80 !important; font-size:.85rem; padding:0 !important; min-height:1.6rem; }
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def brand(subtitle: str):
    st.markdown(f"""<div class="pf-brand"><div class="pf-logo">⚽</div><div>
        <div class="pf-title">Pronos Foot</div><div class="pf-sub">{html.escape(subtitle)}</div></div></div>""",
                unsafe_allow_html=True)


def _bar_only(p1, pn, p2):
    return (f'<div class="pf-bar" style="margin:10px 0 0 0"><div style="width:{p1*100:.1f}%;background:{GREEN}"></div>'
            f'<div style="width:{pn*100:.1f}%;background:{GREY}"></div>'
            f'<div style="width:{p2*100:.1f}%;background:{BLUE}"></div></div>')


def _bar(p1, pn, p2):
    return (f'<div class="pf-bar"><div style="width:{p1*100:.1f}%;background:{GREEN}"></div>'
            f'<div style="width:{pn*100:.1f}%;background:{GREY}"></div>'
            f'<div style="width:{p2*100:.1f}%;background:{BLUE}"></div></div>'
            f'<div class="pf-probs"><span><b style="color:{GREEN}">1</b> {p1:.0%}</span>'
            f'<span><b style="color:#94a3b8">N</b> {pn:.0%}</span><span><b style="color:{BLUE}">2</b> {p2:.0%}</span></div>')


def match_card(comp: str, when: str, home: str, away: str, p1: float, pn: float, p2: float,
               score: str, chips: list[tuple[str, bool]], national: bool = False):
    from .badges import crest
    e = html.escape
    chips_html = "".join(f'<span class="pf-chip{" v" if v else ""}">{e(c)}</span>' for c, v in chips)
    st.markdown(f"""<div class="pf-card">
      <div class="pf-meta"><span style="text-transform:none">{e(comp)}</span><span>{e(when)}</span></div>
      <div class="pf-teams"><div class="pf-team">{crest(home, national, 40)}{e(home)}</div>
        <div class="pf-score">{e(score)}<small>score probable</small></div>
        <div class="pf-team r">{crest(away, national, 40)}{e(away)}</div></div>
      {_bar(p1, pn, p2)}
      <div class="pf-chips">{chips_html}</div></div>""", unsafe_allow_html=True)


def hero(comp: str, home: str, away: str, lh: float, la: float, k: dict, note: str,
         crest_h: str = "", crest_a: str = ""):
    e = html.escape
    p = k["1X2"]
    top = next(iter(k["Score exact"].items()))
    kpi = lambda l, v, o: f'<div class="pf-kpi"><div class="l">{l}</div><div class="v">{v}</div><div class="o">{o}</div></div>'  # noqa: E731
    st.markdown(f"""<div class="pf-hero">
      <div class="pf-meta"><span style="text-transform:none">{e(comp)}</span><span>{e(note)}</span></div>
      <div class="pf-teams"><div class="pf-team">{crest_h}{e(home)}</div>
        <div class="pf-score">{lh:.2f} – {la:.2f}<small>buts attendus</small></div>
        <div class="pf-team r">{crest_a}{e(away)}</div></div>
      {_bar(p['1'], p['N'], p['2'])}
      <div class="pf-kpis">
        {kpi("Victoire " + e(home[:12]), f"{p['1']:.0%}", f"cote juste {1/p['1']:.2f}")}
        {kpi("Nul", f"{p['N']:.0%}", f"cote juste {1/p['N']:.2f}")}
        {kpi("Victoire " + e(away[:12]), f"{p['2']:.0%}", f"cote juste {1/p['2']:.2f}")}
        {kpi("+2.5 buts", f"{k['Plus/Moins buts']['+2.5']:.0%}", f"cote juste {1/k['Plus/Moins buts']['+2.5']:.2f}")}
        {kpi("Les 2 marquent", f"{k['BTTS']['Oui']:.0%}", f"cote juste {1/k['BTTS']['Oui']:.2f}")}
        {kpi("Score n°1", e(top[0]), f"{top[1]:.0%} · cote {1/top[1]:.1f}")}
      </div></div>""", unsafe_allow_html=True)


def footer():
    st.markdown('<div class="pf-foot">Probabilités, pas certitudes · Joue responsable · '
                'Joueurs Info Service 09 74 75 13 13</div>', unsafe_allow_html=True)


def page_title(title: str, subtitle: str = ""):
    sub = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="pf-page"><h1>{html.escape(title)}</h1>{sub}</div>', unsafe_allow_html=True)


def section(title: str):
    st.markdown(f'<div class="pf-section">{html.escape(title)}</div>', unsafe_allow_html=True)


def kpis(items: list[tuple]):
    """items : (libellé, valeur, sous-texte[, ton 'good'|'bad'|''])"""
    cells = []
    for it in items:
        label, value, sub = it[:3]
        tone = it[3] if len(it) > 3 else ""
        cells.append(f'<div class="pf-k {tone}"><div class="l">{html.escape(str(label))}</div>'
                     f'<div class="v">{html.escape(str(value))}</div><div class="s">{html.escape(str(sub))}</div></div>')
    st.markdown(f'<div class="pf-kgrid">{"".join(cells)}</div>', unsafe_allow_html=True)


def market_list(title: str, d: dict, rename: dict | None = None, target=None):
    """Liste "pro" d'un marché : nom, barre de proba, %, cote juste."""
    rows = []
    for k, p in d.items():
        name = (rename or {}).get(k, k)
        fair = f"{1 / p:.2f}" if p > 0.0005 else "—"
        rows.append(f'<div class="pf-row"><span class="n">{html.escape(str(name))}</span>'
                    f'<span class="b"><i style="width:{min(100, p * 100):.1f}%"></i></span>'
                    f'<span class="p">{p * 100:.0f}%</span><span class="o">@ {fair}</span></div>')
    (target or st).markdown(f'<div class="pf-list"><div class="t">{html.escape(title)}</div>{"".join(rows)}</div>',
                            unsafe_allow_html=True)


def bet_row(title: str, detail: str, right: str, right_sub: str = "", tag: tuple[str, str] | None = None,
            target=None):
    tg = f'<span class="pf-tag {tag[1]}">{html.escape(tag[0])}</span>' if tag else ""
    (target or st).markdown(
        f'<div class="pf-bet"><div><div class="m">{tg}{html.escape(title)}</div>'
        f'<div class="d">{html.escape(detail)}</div></div>'
        f'<div class="r">{html.escape(right)}<small>{html.escape(right_sub)}</small></div></div>',
        unsafe_allow_html=True)


def _short(team: str, n: int = 18) -> str:
    return team if len(team) <= n else team[: n - 1] + "…"


def match_accordion(comp_lbl: str, when: str, day: str, home: str, away: str, k: dict, lam: tuple,
                    chips: list[tuple[str, bool]], national: bool = False, open_: bool = False,
                    href: str | None = None) -> str:
    """Affiche compacte qui se déroule (HTML <details>) : résumé + détails des principaux paris."""
    from .badges import crest
    e = html.escape
    p = k["1X2"]
    best = max(p, key=p.get)
    pp = "".join(f'<span class="{"hi" if s == best else ""}">{p[s] * 100:.0f}%</span>' for s in ("1", "N", "2"))
    top = list(k["Score exact"].items())[:4]
    chips_html = "".join(f'<span class="pf-chip{" v" if v else ""}">{e(c)}</span>' for c, v in chips)
    mini = (f'<div><small>+2,5 buts</small><b>{k["Plus/Moins buts"]["+2.5"]:.0%}</b></div>'
            f'<div><small>2 marquent</small><b>{k["BTTS"]["Oui"]:.0%}</b></div>'
            f'<div><small>xG</small><b>{lam[0]:.1f}–{lam[1]:.1f}</b></div>'
            f'<div><small>{e(_short(home, 10))} ou nul</small><b>{k["Double chance"]["1N"]:.0%}</b></div>'
            f'<div><small>Pas de nul</small><b>{k["Double chance"]["12"]:.0%}</b></div>'
            f'<div><small>Nul ou {e(_short(away, 8))}</small><b>{k["Double chance"]["N2"]:.0%}</b></div>')
    scores = "".join(f"<span><b>{e(sc)}</b>{pr:.0%}</span>" for sc, pr in top)
    link = (f'<a class="pf-link" href="{e(href)}" target="_self">Tous les paris de ce match →</a>' if href else "")
    return f"""<details class="pf-acc"{' open' if open_ else ''}><summary>
      <div class="pf-sum"><div class="pf-time">{e(when)}<small>{e(day)}</small></div>
        <div><div class="pf-tm">{crest(home, national, 24)}{e(_short(home))}</div>
             <div class="pf-tm">{crest(away, national, 24)}{e(_short(away))}</div></div>
        <div class="pf-pp">{pp}</div></div>
      {_bar_only(p['1'], p['N'], p['2'])}
      <div class="pf-chev">▼</div></summary>
      <div class="pf-body"><div class="pf-meta"><span style="text-transform:none">{e(comp_lbl)}</span>
        <span>score probable {e(top[0][0])}</span></div>
        <div class="pf-chips">{chips_html}</div><div class="pf-mini">{mini}</div>
        <div class="pf-section" style="margin:12px 0 0 2px">Scores exacts les plus probables</div>
        <div class="pf-scores">{scores}</div>{link}</div></details>"""


def featured(comp_lbl: str, when: str, home: str, away: str, k: dict, lam: tuple, national: bool = False):
    from .badges import crest
    e = html.escape
    p = k["1X2"]
    top = next(iter(k["Score exact"]))
    st.markdown(f"""<div class="pf-feat"><div class="pf-meta"><span class="lbl">★ Match à la une</span>
      <span>{e(comp_lbl)} · {e(when)}</span></div>
      <div class="pf-teams"><div class="pf-team">{crest(home, national, 54)}{e(home)}</div>
        <div class="pf-score">{e(top)}<small>score probable</small></div>
        <div class="pf-team r">{crest(away, national, 54)}{e(away)}</div></div>
      {_bar(p['1'], p['N'], p['2'])}</div>""", unsafe_allow_html=True)


def ticket(name: str, subtitle: str, c1: str, c2: str, legs: list[dict], total_odds: float, prob: float):
    e = html.escape
    rows = "".join(
        f'<div class="lg"><div><div class="m">{e(l["home"])} – {e(l["away"])}</div>'
        f'<div class="d">{e(l["label"])} · {l["proba"]:.0%}</div></div>'
        f'<div class="o">{l["cote"]:.2f}<small>{"cote" if l.get("reelle") else "estimée"}</small></div></div>'
        for l in legs)
    st.markdown(f"""<div class="pf-ticket" style="--c1:{c1};--c2:{c2}">
      <div class="hd"><b>{e(name)}</b><span>{e(subtitle)}</span></div>{rows}
      <div class="ft"><div><small>Cote</small><b>{total_odds:.2f}</b></div>
        <div><small>Chance</small><b>{prob:.0%}</b></div>
        <div><small>10 € →</small><b>{10 * total_odds:.0f} €</b></div></div></div>""", unsafe_allow_html=True)
