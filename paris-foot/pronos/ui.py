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
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def brand(subtitle: str):
    st.markdown(f"""<div class="pf-brand"><div class="pf-logo">⚽</div><div>
        <div class="pf-title">Pronos Foot</div><div class="pf-sub">{html.escape(subtitle)}</div></div></div>""",
                unsafe_allow_html=True)


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
