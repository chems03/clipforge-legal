"""Appli web de pronostics football — lancer avec :  streamlit run app.py"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd
import streamlit as st

import os

from pronos import apifootball, engine
from pronos.data import COMPETITIONS, CUPS, LEAGUES, MAIN_LEAGUES, NAT_COMPS
from pronos.nationals import active_teams, national_scorers
from pronos import historique as hist
from pronos import ui
from pronos import simulation as sim
from pronos.badges import comp_label, crest, team_text
from pronos.scorers import COLUMNS, load_players, save_players, scorer_probs

st.set_page_config(page_title="Pronos Foot", page_icon="⚽", layout="wide", initial_sidebar_state="collapsed")
ui.inject()
try:  # clé API-Football : Streamlit Cloud → Settings → Secrets  (API_FOOTBALL_KEY = "...")
    if "API_FOOTBALL_KEY" in st.secrets:
        os.environ["API_FOOTBALL_KEY"] = str(st.secrets["API_FOOTBALL_KEY"])
except Exception:
    pass


@st.cache_resource(ttl=6 * 3600, show_spinner="Téléchargement des données et calcul du modèle…")
def model(_nonce: int = 0):
    return engine.get_model(force=_nonce > 0)


if "nonce" not in st.session_state:
    st.session_state.nonce = 0
if "ticket" not in st.session_state:
    st.session_state.ticket = []

@st.cache_resource(ttl=6 * 3600, show_spinner="Chargement des matchs des sélections nationales…")
def nat_model(_nonce: int = 0):
    return engine.get_national_model(force=_nonce > 0)


m, results = model(st.session_state.nonce)


@st.cache_resource(ttl=3 * 3600, show_spinner="Récupération des blessés, compos et cotes…")
def api_data(_nonce: int = 0):
    return apifootball.enrich(m.teams, m.team_league)


API = api_data(st.session_state.nonce)
engine.set_api(API, results)
info = getattr(m, "info", {})

# ------------------------------------------------------------------ navigation (barre d'onglets en bas)
NAV = ["🏠 Accueil", "⚽ Matchs", "🎟️ Combinés", "🎮 Simu", "🧩 Plus"]
SUB = ["🔒 Pronos sûrs", "🔍 Analyse", "📊 Bilan", "🧾 Mon ticket", "🏆 Classement", "👟 Buteurs", "📈 Fiabilité",
       "⚙️ Données"]
SLUGS = {"accueil": "🏠 Accueil", "matchs": "⚽ Matchs", "combines": "🎟️ Combinés", "simu": "🎮 Simu",
         "surs": "🔒 Pronos sûrs", "analyse": "🔍 Analyse", "bilan": "📊 Bilan", "donnees": "⚙️ Données"}


def goto(target: str):
    if target in NAV:
        st.session_state.nav, st.session_state.more = target, None
    else:
        st.session_state.nav, st.session_state.more = "🧩 Plus", target


_qp = st.query_params
if "h" in _qp and "a" in _qp and "c" in _qp:
    goto("🔍 Analyse")
    st.session_state.kind = "⚽ Clubs"
    _c = _qp["c"]
    st.session_state.comp_pill = _c if _c in ["F1", "E0", "SP1", "I1", "D1", "CL", "EL", "ECL"] else "➕"
    if st.session_state.comp_pill == "➕":
        st.session_state.comp_other = _c
    st.session_state.home_club, st.session_state.away_club = _qp["h"], _qp["a"]
    for _key in ["ch", "cd", "ca", "co", "cu"]:
        try:
            st.session_state[_key] = float(_qp.get(_key, 0) or 0)
        except ValueError:
            st.session_state[_key] = 0.0
    st.query_params.clear()
elif "p" in _qp:
    goto(SLUGS.get(_qp["p"], NAV[0]))
    st.query_params.clear()
st.session_state.setdefault("nav", NAV[0])
if st.session_state.nav not in NAV:
    st.session_state.nav = NAV[0]
with st.container(key="bottomnav"):
    nav = st.pills("Navigation", NAV, label_visibility="collapsed", key="nav",
                   on_change=lambda: st.session_state.update(more=None)) or NAV[0]
page = nav
if nav == "🧩 Plus":
    if st.session_state.get("more"):
        st.button("‹ Plus", type="tertiary", on_click=lambda: st.session_state.update(more=None))
        page = st.session_state.more
    else:
        ui.page_title("Plus", "Tous les outils de l'appli.")
        with st.container(key="moregrid"):
            st.pills("Plus", SUB, label_visibility="collapsed", key="more_pick",
                     on_change=lambda: st.session_state.update(more=st.session_state.more_pick, more_pick=None))
for _k, _v in dict(ch=0.0, cd=0.0, ca=0.0, co=0.0, cu=0.0).items():
    st.session_state.setdefault(_k, _v)


@st.cache_data(ttl=1800, show_spinner=False)
def upcoming_cached(_m, nonce, day):
    return engine.upcoming_table(_m, leagues=list(LEAGUES))


@st.cache_data(ttl=1800, show_spinner=False)
def combos_cached(_m, nonce, day):
    return engine.build_combos(_m)


@st.cache_data(ttl=1800, show_spinner=False)
def safe_cached(_m, nonce, day, min_p, min_c):
    return engine.safe_picks(_m, min_p, min_c)


_today = str(pd.Timestamp.today().date())


def analysis_href(r) -> str | None:
    from urllib.parse import urlencode
    if getattr(r, "approx", False):
        return None
    vals = [getattr(r, c, None) for c in ("o_h", "o_d", "o_a", "o_o25", "o_u25")]
    return "?" + urlencode(dict(h=r.home, a=r.away, c=r.comp, **{k_: (f"{v:.2f}" if v and v == v else "0")
                                                                  for k_, v in zip(["ch", "cd", "ca", "co", "cu"], vals)}))


QUICK_COMPS = ["F1", "E0", "SP1", "I1", "D1", "CL", "EL", "ECL"]


def open_match(comp, home, away, odds):
    """Bouton « Analyser » d'une carte : ouvre l'analyse détaillée pré-remplie (équipes + cotes)."""
    goto("🔍 Analyse")
    st.session_state.kind = "⚽ Clubs"
    if comp in QUICK_COMPS:
        st.session_state.comp_pill = comp
    else:
        st.session_state.comp_pill = "➕"
        st.session_state.comp_other = comp
    st.session_state.home_club = home
    st.session_state.away_club = away
    for key, v in zip(["ch", "cd", "ca", "co", "cu"], odds):
        st.session_state[key] = float(v) if v and v == v else 0.0


def refresh_data():
    model.clear()
    nat_model.clear()
    api_data.clear()
    st.session_state.nonce += 1


html_escape = html.escape


def pct(x):
    return f"{100 * x:.1f} %"


def market_table(d: dict, value_odds: dict | None = None) -> pd.DataFrame:
    rows = []
    for k, p in d.items():
        rows.append({"Pari": k, "Probabilité": pct(p), "Cote juste": round(1 / p, 2) if p > 0 else None})
    return pd.DataFrame(rows)


def sim_options(k: dict) -> dict:
    """Marchés jouables dans le simulateur -> {sélection: proba}."""
    ou = {}
    for sel, p in k["Plus/Moins buts"].items():
        ou[sel] = p
        ou["-" + sel[1:]] = 1 - p
    return {"1X2": k["1X2"], "Double chance": k["Double chance"], "Plus/Moins buts": ou, "BTTS": k["BTTS"],
            "Score exact": k["Score exact"]}


def get_portfolio() -> dict:
    if "portfolio" not in st.session_state:
        st.session_state.portfolio = sim.load_portfolio()
    return st.session_state.portfolio


def team_label(t):
    return f"{t} ({m.team_league[t]})"



# ------------------------------------------------------------------ pages
if page == "🏠 Accueil":
    t_all = upcoming_cached(m, st.session_state.nonce, _today)
    n_today = int((pd.to_datetime(t_all.date) == pd.Timestamp(_today)).sum()) if not t_all.empty else 0
    ui.top_bar(n_today)
    days_fr = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

    def when(r):
        d = pd.Timestamp(r.date)
        return f"{days_fr[d.weekday()]} {d.day} · {r.heure}"

    if t_all.empty:
        st.info("Pas de match publié pour les prochains jours. Utilise ☰ Plus → 🔍 Analyse pour n'importe quelle affiche.")
    else:
        strength = m.ratings().set_index("equipe")["diff"].to_dict()
        soon = t_all[pd.to_datetime(t_all.date) <= pd.Timestamp(_today) + pd.Timedelta(days=3)]
        top = sorted(soon[~soon.approx].itertuples(), key=lambda r: -min(strength.get(r.home, -9), strength.get(r.away, -9)))[:6]
        ui.h2("★", "À la une", "?p=matchs")
        ui.carousel([ui.card_une(f"{COMPETITIONS.get(r.comp, r.comp)} · {when(r)}", r.home, r.away,
                                 f"Favori : {(r.home if r.P1 >= r.P2 else r.away)} {max(r.P1, r.P2):.0%} · "
                                 f"score probable {r.score_probable.split(' ')[0]}", analysis_href(r)) for r in top])

        ui.h2("📅", "Matchs à l'affiche", "?p=matchs")
        big = t_all[t_all.comp.isin(["CL", "EL", "ECL", *MAIN_LEAGUES])]
        nxt = (big if len(big) >= 4 else t_all).sort_values(["date", "heure"]).head(14)
        ui.carousel([ui.card_affiche(r.comp, COMPETITIONS.get(r.comp, r.comp), when(r), r.home, r.away,
                                     {"1": r.P1, "N": r.PN, "2": r.P2}, analysis_href(r)) for r in nxt.itertuples()])

        picks = safe_cached(m, st.session_state.nonce, _today, 0.75, 1.15)
        if not picks.empty:
            ui.h2("🔒", "Pronos sûrs", "?p=surs")
            ui.carousel([ui.card_small(f"{COMPETITIONS.get(r.comp, r.comp)} · {pd.Timestamp(r.date):%d/%m} {r.heure}",
                                       f"{r.home} – {r.away}", f"{r.proba:.0%}", f"@ {r.cote:.2f}",
                                       engine.leg_label(r.marche, r.pari, r.home, r.away), href="?p=surs")
                         for r in picks.head(10).itertuples()])

        combos = combos_cached(m, st.session_state.nonce, _today)
        if combos:
            ui.h2("🎟️", "Combinés du jour", "?p=combines")
            ui.carousel([ui.card_small(f"{len(cb['legs'])} matchs", cb["name"], f"{cb['odds']:.2f}", "cote",
                                       f"{cb['proba']:.0%} de chances · 10 € → {10 * cb['odds']:.0f} €",
                                       grad=(cb["c1"], cb["c2"]), href="?p=combines") for cb in combos.values()])

    pf = get_portfolio()
    bal = sim.balance(pf)
    ui.h2("🎮", "Mon simulateur", "?p=simu")
    ui.carousel([
        ui.card_small("Solde fictif", "Argent virtuel", f"{bal['solde']:.0f} €", "",
                      f"{bal['solde'] + bal['en_jeu'] - pf['start']:+.0f} € depuis le départ", href="?p=simu"),
        ui.card_small("Paris", "En cours", f"{bal['en_cours']}", "pari(s)", f"{bal['en_jeu']:.0f} € en jeu", href="?p=simu"),
        ui.card_small("Réussite", "Paris réglés", f"{bal['gagnes'] / max(1, bal['gagnes'] + bal['perdus']):.0%}", "",
                      f"✅ {bal['gagnes']} · ❌ {bal['perdus']}", href="?p=simu")])

    try:
        hs = hist.build_history(results, "clubs")
        s5 = hist.summary(hs[hs.comp.isin(MAIN_LEAGUES)])
        ui.h2("📊", "Bilan de l'appli", "?p=bilan")
        ui.carousel([ui.card_small("Saison 2026-27", row["Pari"], f"{row['% réussite']:.0%}", "réussis",
                                   f"✅ {row['✅ Réussis']} · ❌ {row['❌ Ratés']}", href="?p=bilan")
                     for _, row in s5.iterrows()])
    except Exception:
        pass

elif page == "⚽ Matchs":
    ui.page_title("Prochains matchs", "Touche une affiche pour la dérouler. Les 3 pourcentages = victoire "
                  "domicile, nul, victoire extérieur.")
    _info = st.expander("ℹ️ Comment lire une carte")
    _info.markdown("- **Barre verte / grise / bleue** : chances de victoire domicile, nul, victoire extérieur.\n"
                   "- **Score probable** : le score le plus fréquent si on rejouait le match des milliers de fois.\n"
                   "- **💰 Value** : la cote du bookmaker est plus haute que ce qu'elle devrait être → pari "
                   "intéressant sur le long terme.\n- **xG** : buts attendus pour chaque équipe.")
    _info.caption("Calendrier et cotes moyennes du marché : football-data.co.uk. Les probabilités combinent le "
               f"modèle ({int(engine.ALPHA_MODEL * 100)} %) et le consensus des bookmakers "
               f"({int((1 - engine.ALPHA_MODEL) * 100)} %). Value = proba × meilleure cote − 1 ≥ "
               f"{engine.MIN_EDGE:.0%}.")
    _info.caption("Coupes d'Europe et sélections nationales : aucun calendrier gratuit n'est disponible → "
               "choisis l'affiche dans « 🔍 Analyse d'un match » (Ligue des champions, Ligue Europa, "
               "Conférence, Coupe du monde, Euro, qualifs, Ligue des nations, amicaux).")
    t_all = upcoming_cached(m, st.session_state.nonce, _today)
    avail = [c for c in ["CL", "EL", "ECL", *LEAGUES] if not t_all.empty and c in set(t_all.comp)]
    st.session_state.setdefault("lg_pills", [c for c in ["CL", "EL", "ECL", *MAIN_LEAGUES] if c in avail] or avail)
    st.session_state.lg_pills = [c for c in st.session_state.lg_pills if c in avail]
    leagues = st.pills("Championnats", avail, selection_mode="multi", key="lg_pills",
                       format_func=lambda c: comp_label(c, COMPETITIONS), label_visibility="collapsed")
    t = t_all[t_all.comp.isin(leagues)] if not t_all.empty else t_all
    if t.empty:
        st.info("Pas de matchs à venir publiés pour l'instant (le fichier est mis à jour en milieu de "
                "semaine). Utilise « Analyse d'un match » pour n'importe quelle affiche.")
    else:
        f1, f2 = st.columns(2)
        only_value = f1.toggle("💰 Value bets uniquement")
        table_view = f2.toggle("Vue tableau")
        if only_value:
            t = t[t.value != ""]
        if table_view:
            show = t.drop(columns=["cale_marche", "approx", "o_h", "o_d", "o_a", "o_o25", "o_u25"]).copy()
            for c in ["P1", "PN", "P2", "P+2.5", "BTTS"]:
                show[c] = (show[c] * 100).round(1)
            show["comp"] = show["comp"].map(COMPETITIONS)
            st.dataframe(show.round(2), hide_index=True, width="stretch",
                         column_config={c: st.column_config.ProgressColumn(c, format="%.1f %%", min_value=0,
                                                                           max_value=100)
                                        for c in ["P1", "PN", "P2", "P+2.5", "BTTS"]})
        else:
            from urllib.parse import urlencode
            days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
            months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
                      "nov.", "déc."]
            strength = m.ratings().set_index("equipe")["diff"].to_dict()

            def _k(r):
                o = {k_: (v if v == v else None) for k_, v in dict(h=r.o_h, d=r.o_d, a=r.o_a, o25=r.o_o25,
                                                                    u25=r.o_u25).items()}
                ctx = engine.match_context(r.home, r.away, r.date)
                res = engine.predict(m, r.home, r.away, r.comp, odds=o if o["h"] else None, adj=ctx["adj"],
                                     allow_unknown=bool(r.approx))
                return res["markets"], res["lambda"]

            # match à la une : la plus grosse affiche des 2 prochains jours
            soon = t[t.date <= t.date.min() + pd.Timedelta(days=1)]
            if not soon.empty:
                fr = max(soon.itertuples(), key=lambda r: min(strength.get(r.home, -9), strength.get(r.away, -9)))
                fk, fl = _k(fr)
                ui.featured(comp_label(fr.comp, COMPETITIONS), f"{pd.Timestamp(fr.date):%d/%m} · {fr.heure}",
                            fr.home, fr.away, fk, fl)
            for d, grp in t.rename(columns={"P+2.5": "P_o25"}).groupby("date", sort=True):
                d = pd.Timestamp(d)
                st.markdown(f'<div class="pf-day">{days[d.weekday()]} {d.day} {months[d.month - 1]} · '
                            f'{len(grp)} match{"s" if len(grp) > 1 else ""}</div>', unsafe_allow_html=True)
                html_items = []
                for r in grp.itertuples():
                    kk, lam = _k(r)
                    chips = []
                    if r.value:
                        chips.append((f"💰 Value : {r.value}", True))
                    if r.abs_h or r.abs_a:
                        chips.append((f"🩹 Absents : {r.home[:12]} {r.abs_h} · {r.away[:12]} {r.abs_a}", False))
                    if r.approx:
                        chips.append(("⚠️ Estimation : équipe hors base", False))
                    href = None if r.approx else "?" + urlencode(dict(
                        h=r.home, a=r.away, c=r.comp, **{k_: (f"{v:.2f}" if v == v and v else "0") for k_, v in
                                                        zip(["ch", "cd", "ca", "co", "cu"],
                                                            [r.o_h, r.o_d, r.o_a, r.o_o25, r.o_u25])}))
                    html_items.append(ui.match_accordion(comp_label(r.comp, COMPETITIONS), str(r.heure),
                                                         comp_label(r.comp, COMPETITIONS).split(" ")[0], r.home,
                                                         r.away, kk, lam, chips, href=href))
                st.markdown("".join(html_items), unsafe_allow_html=True)

elif page == "🎟️ Combinés":
    ui.page_title("Combinés", "Trois tickets construits par l'appli sur les matchs à venir, du plus sûr au plus "
                  "audacieux. Une seule sélection par match.")
    combos = combos_cached(m, st.session_state.nonce, _today)
    if not combos:
        st.info("Pas assez de matchs publiés pour construire des combinés. Reviens quand le calendrier du "
                "week-end sera sorti (jeudi/vendredi).")
    for key, cb in combos.items():
        ui.ticket(cb["name"], cb["sub"], cb["c1"], cb["c2"], cb["legs"], cb["odds"], cb["proba"])
        c1, c2 = st.columns([1, 1])
        mise = c1.number_input("Mise fictive (€)", 1.0, 10000.0, 10.0, 1.0, key=f"cb_mise_{key}",
                               label_visibility="collapsed")
        if c2.button("🎮 Jouer en fictif", key=f"cb_{key}", width="stretch"):
            pf = get_portfolio()
            err = sim.place_combo(pf, cb["name"], cb["legs"], mise)
            if err:
                st.error(err)
            else:
                sim.save_portfolio(pf)
                st.success("Combiné ajouté au simulateur ✅ Il se réglera tout seul après les matchs.")
    if combos:
        with st.expander("ℹ️ Bien comprendre un combiné"):
            st.markdown("- **Chance** = probabilité que *tous* les pronos passent (on multiplie les probabilités).\n"
                        "- Chaque match ajouté **multiplie la cote mais aussi la marge du bookmaker** : à long terme, "
                        "un combiné rapporte moins qu'un pari simple, sauf si chaque sélection a de la value.\n"
                        "- « estimée » = cote calculée par l'appli (vraie cote inconnue). **Vérifie chez ton "
                        "bookmaker** : si sa cote est plus basse, le ticket rapportera moins.")

elif page == "🔒 Pronos sûrs":
    ui.page_title("Pronos sûrs", "Le pari le plus probable de chaque match, avec une cote minimum. "
                  "Rien n'est sûr à 100 % : un prono à 80 % perd 1 fois sur 5.")
    c1, c2 = st.columns(2)
    min_p = c1.slider("Probabilité minimum", 0.60, 0.95, 0.75, 0.01, format="%.2f")
    min_c = c2.slider("Cote minimum", 1.05, 2.00, 1.15, 0.01, format="%.2f")
    picks = safe_cached(m, st.session_state.nonce, _today, min_p, min_c)
    if picks.empty:
        st.info("Aucun pari ne remplit ces conditions pour les matchs publiés. Baisse un peu la probabilité "
                "minimum ou attends la publication du calendrier du week-end (jeudi/vendredi).")
    else:
        mode = {"1X2": "Victoire", "Double chance": "Double chance", "Plus/Moins buts": "Buts",
                "BTTS": "Les 2 marquent", "Remboursé si nul": "Remboursé si nul"}
        for i, r in picks.iterrows():
            chips = [(f"✅ {mode[r.marche]} : {r.pari}", True), (f"Proba {r.proba:.0%}", False),
                     (f"Cote {r.cote:.2f}{'' if r.cote_reelle else ' (estimée)'}", False)]
            res = engine.predict(m, r.home, r.away, r.comp)
            kk = res["markets"]
            ui.match_card(comp_label(r.comp, COMPETITIONS), f"{pd.Timestamp(r.date):%d/%m} {r.heure}", r.home, r.away,
                          kk["1X2"]["1"], kk["1X2"]["N"], kk["1X2"]["2"], next(iter(kk["Score exact"])), chips)
            if st.button(f"🎮 Tester avec 10 € fictifs →", key=f"safe_{i}_{r.home}", type="tertiary"):
                pf = get_portfolio()
                err = sim.place_bet(pf, home=r.home, away=r.away, comp=r.comp, market=r.marche, selection=r.pari,
                                    odds=r.cote, stake=10, proba=r.proba, match_date=r.date)
                if err:
                    st.error(err)
                else:
                    sim.save_portfolio(pf)
                    st.success("Pari fictif ajouté au simulateur ✅")
        if len(picks) >= 2:
            top = picks.head(3)
            p_comb, c_comb = float(np.prod(top.proba)), float(np.prod(top.cote))
            ui.section(f"Combiné des {len(top)} plus sûrs")
            ui.kpis([("Cote totale", f"{c_comb:.2f}", "si tous passent"),
                     ("Chance de passer", f"{p_comb:.0%}", "tous les pronos justes")])
            for a, b, c in zip(top.home, top.away, top.pari):
                ui.bet_row(f"{a} – {b}", "Prono", c)
            st.caption("Plus tu ajoutes de matchs, plus le combiné devient risqué : 3 pronos à 80 % ne passent "
                       "ensemble qu'environ 1 fois sur 2.")

    with st.expander("📊 Ce que cette méthode aurait donné cette saison"):
        hs = hist.build_history(results, "clubs")
        bt = sim.run_strategy(hs, results, "fav", min_p, min_odds=min_c)
        if bt.empty:
            st.write("Pas assez de matchs avec ces réglages.")
        else:
            w = int(bt.gagne.sum())
            st.markdown(f"Favori de l'appli à **{min_p:.0%}** ou plus et cote ≥ **{min_c:.2f}**, 10 € par pari, "
                        f"cote moyenne du marché : **{len(bt)} paris · ✅ {w} · ❌ {len(bt) - w} "
                        f"({w / len(bt):.0%} de réussite) · bénéfice {bt.gain.sum():+.0f} € "
                        f"(ROI {bt.gain.sum() / bt.mise.sum():+.1%})**")
            st.line_chart(bt.assign(n=range(1, len(bt) + 1)).set_index("n")[["bankroll"]])
            st.caption("Avec des cotes autour de 1,20, une seule défaite efface 4 à 5 victoires : un taux de "
                       "réussite élevé ne garantit pas un bénéfice.")

elif page == "🔍 Analyse":
    ui.page_title("Analyse d'un match", "Choisis l'affiche : tous les paris et leurs vraies probabilités.")
    st.session_state.setdefault("kind", "⚽ Clubs")
    kind = st.segmented_control("Type", ["⚽ Clubs", "🌍 Sélections nationales"], label_visibility="collapsed",
                                key="kind") or "⚽ Clubs"
    national = kind.startswith("🌍")
    if national:
        mod, nat_df, nat_goals = nat_model(st.session_state.nonce)
        st.session_state.setdefault("comp_nat", "CDM")
        comp = st.pills("Compétition", list(NAT_COMPS), key="comp_nat", label_visibility="collapsed",
                        format_func=lambda c: f"{comp_label(c, NAT_COMPS)}") or "CDM"
        c1, c2, c3 = st.columns([2, 2, 1])
        pool = [t for t in active_teams(nat_df) if t in mod.att]
        default_h = pool.index("France") if "France" in pool else 0
        default_a = pool.index("Spain") if "Spain" in pool else 1
        home = c1.selectbox("Équipe 1 (domicile)", pool, index=default_h, format_func=lambda t: team_text(t, True))
        away = c2.selectbox("Équipe 2", pool, index=default_a, format_func=lambda t: team_text(t, True))
        neutral = c3.checkbox("Terrain neutre", value=comp in ("CDM", "CONTINENTAL"),
                              help="Coupe du monde / Euro : terrain neutre sauf pour le pays organisateur.")

    else:
        mod = m
        st.session_state.setdefault("comp_pill", "F1")
        pick = st.pills("Compétition", QUICK_COMPS + ["➕"], key="comp_pill", label_visibility="collapsed",
                        format_func=lambda c: "➕ Autres championnats" if c == "➕" else comp_label(c, COMPETITIONS)) or "F1"
        if pick == "➕":
            others = [c for c in LEAGUES if c not in QUICK_COMPS]
            st.session_state.setdefault("comp_other", others[0])
            comp = st.selectbox("Championnat", others, key="comp_other",
                                format_func=lambda c: comp_label(c, COMPETITIONS))
        else:
            comp = pick
        c1, c2, c3 = st.columns([2, 2, 1])
        pool = sorted(m.teams) if comp in CUPS else sorted(t for t in m.teams if m.team_league[t] == comp) or m.teams
        if st.session_state.get("home_club") not in pool:
            st.session_state.home_club = "Paris SG" if "Paris SG" in pool else pool[0]
        if st.session_state.get("away_club") not in pool:
            st.session_state.away_club = next(t for t in pool if t != st.session_state.home_club)
        home = c1.selectbox("Domicile", pool, format_func=team_label, key="home_club")
        away = c2.selectbox("Extérieur", pool, format_func=team_label, key="away_club")
        neutral = c3.checkbox("Terrain neutre (finale)")


    hero_slot = st.container()
    with st.expander("💶 Ajouter les cotes de ton bookmaker (plus précis + détection de value)"):
        o1, o2, o3, o4, o5 = st.columns(5)
        ch = o1.number_input("Cote 1", 0.0, 100.0, step=0.01, key="ch")
        cd = o2.number_input("Cote N", 0.0, 100.0, step=0.01, key="cd")
        ca = o3.number_input("Cote 2", 0.0, 100.0, step=0.01, key="ca")
        co = o4.number_input("Cote +2.5", 0.0, 20.0, step=0.01, key="co")
        cu = o5.number_input("Cote −2.5", 0.0, 20.0, step=0.01, key="cu")
    with st.expander("🩹 Blessures, suspensions, rotation…"):
        st.caption("Ex. : buteur principal absent ≈ −8 à −12 % en attaque ; défenseur central titulaire "
                   "absent ≈ −5 % en défense ; équipe B / rotation avant un gros match ≈ −10 à −15 %.")
        a1, a2, a3, a4 = st.columns(4)
        adj = dict(att_h=a1.slider(f"Attaque {home}", -30, 30, 0) / 100,
                   def_h=a2.slider(f"Défense {home}", -30, 30, 0) / 100,
                   att_a=a3.slider(f"Attaque {away}", -30, 30, 0) / 100,
                   def_a=a4.slider(f"Défense {away}", -30, 30, 0) / 100)

    if home == away:
        st.warning("Choisis deux équipes différentes.")
        st.stop()
    odds = None
    if ch > 1 and cd > 1 and ca > 1:
        odds = dict(h=ch, d=cd, a=ca, o25=co if co > 1 else None, u25=cu if cu > 1 else None)
    ctx = engine.match_context(home, away) if not national else engine.match_context("", "")
    auto = ctx["adj"]
    if auto:
        adj = {k_: adj.get(k_, 0) + auto.get(k_, 0) for k_ in ("att_h", "def_h", "att_a", "def_a")}
    if odds is None and ctx["odds"].get("h"):
        odds = ctx["odds"]
    if odds is None and ctx["fixture_id"] and comp in CUPS:   # vraies cotes de coupe à la demande
        _fo = apifootball.fixture_odds(ctx["fixture_id"])
        if _fo.get("h"):
            odds = {k_: _fo.get(k_) for k_ in ("h", "d", "a", "o25", "u25")}
            st.caption(f"Cotes réelles {_fo.get('bookmaker') or ''} chargées automatiquement (API-Football).")
    r = engine.predict(mod, home, away, comp, neutral, odds=odds, adj=adj)
    k = r["markets"]
    lh, la = r["lambda"]

    note = "modèle + cotes" if r["lambda_market"] else "modèle seul"
    with hero_slot:
        ui.hero(comp_label(comp, NAT_COMPS if national else COMPETITIONS), home, away, lh, la, k, note,
                crest(home, national, 52), crest(away, national, 52))
        if ctx["fixture_id"]:
            ui.section("Absents & compos")
            for team, lst, a_att in ((home, ctx["abs_h"], auto.get("att_h", 0)), (away, ctx["abs_a"], auto.get("att_a", 0))):
                if lst:
                    ui.bet_row(f"{team} : {len(lst)} absent(s)",
                               " · ".join(f"{a['nom']} ({a['raison'] or a['type']})" for a in lst),
                               f"{a_att:+.0%}" if a_att else "≈ 0 %", "impact attaque", ("PRIS EN COMPTE", "y"))
                else:
                    ui.bet_row(f"{team} : aucun absent signalé", "Source : API-Football", "✓", "", ("OK", "g"))
            if st.button("📋 Voir les compos officielles", type="tertiary"):
                lu = apifootball.lineups(ctx["fixture_id"])
                if not lu:
                    st.info("Compos pas encore publiées (elles sortent environ 1 h avant le coup d'envoi).")
                for x in lu:
                    ui.bet_row(f"{x['team']} · {x['formation'] or ''}", ", ".join(x["xi"]), "XI",
                               f"coach {x['coach'] or '?'}")
        elif apifootball.enabled() and not national:
            st.caption("Match non trouvé dans API-Football pour les 3 prochains jours (absents non chargés).")
        if r["all_value"]:
            ui.section("Tes cotes valent-elles le coup ?")
            names = {"1": f"Victoire {home}", "N": "Match nul", "2": f"Victoire {away}", "+2.5": "Plus de 2,5 buts",
                     "-2.5": "Moins de 2,5 buts"}
            for v in r["all_value"]:
                good = v["value"] >= engine.MIN_EDGE
                ui.bet_row(names.get(v["pari"], v["pari"]),
                           f"Proba {v['proba']:.0%} · cote juste {1 / v['proba']:.2f} · ta cote {v['cote']:.2f}",
                           f"{v['value']:+.0%}", f"mise conseillée {v['kelly']:.1%}" if good else "pas de value",
                           ("VALUE", "g") if good else ("NON", "w"))

    st.caption("Chaque ligne : probabilité de l'appli et **cote juste** (@). Une cote de bookmaker plus haute "
               "que la cote juste = pari intéressant.")
    hs_, as_ = home[:14], away[:14]
    tabs = st.tabs(["Résultat", "Buts", "Score exact", "Mi-temps", "Handicaps", "Buteurs"])
    with tabs[0]:
        c1, c2 = st.columns(2)
        ui.market_list("Résultat final", k["1X2"], {"1": f"{hs_}", "N": "Nul", "2": f"{as_}"}, c1)
        ui.market_list("Double chance", k["Double chance"],
                       {"1N": f"{hs_} ou nul", "N2": f"Nul ou {as_}", "12": "Pas de nul"}, c1)
        ui.market_list("Remboursé si nul", k["Remboursé si nul"], {"1": hs_, "2": as_}, c1)
        ui.market_list("Résultat + les 2 marquent", k["Résultat + BTTS"], target=c2)
        ui.market_list("Résultat + buts", k["Résultat + 2.5"], target=c2)
        ui.market_list("Gagne sans encaisser", k["Gagne sans encaisser"], {"Domicile": hs_, "Extérieur": as_}, c2)
    with tabs[1]:
        c1, c2 = st.columns(2)
        ui.market_list("Nombre de buts", k["Plus/Moins buts"],
                       {f"+{i}.5": f"Plus de {i},5" for i in range(6)}, c1)
        ui.market_list("Les deux équipes marquent", k["BTTS"], target=c1)
        ui.market_list("Nombre exact de buts", k["Nombre exact de buts"], target=c1)
        ui.market_list(f"Buts {hs_}", k["Buts domicile"], {f"+{i}.5": f"Plus de {i},5" for i in range(4)}, c2)
        ui.market_list(f"Buts {as_}", k["Buts extérieur"], {f"+{i}.5": f"Plus de {i},5" for i in range(4)}, c2)
        ui.market_list("Clean sheet (n'encaisse pas)", k["Clean sheet"], {"Domicile": hs_, "Extérieur": as_}, c2)
    with tabs[2]:
        c1, c2 = st.columns([2, 3])
        ui.market_list("Scores les plus probables", dict(list(k["Score exact"].items())[:10]), target=c1)
        M = k["matrix"][:6, :6]
        hm = pd.DataFrame(M * 100, index=[f"{hs_} {i}" for i in range(6)], columns=[f"{j}" for j in range(6)])
        c2.markdown(f"<div class='pf-section'>Tous les scores (%) · lignes {html_escape(hs_)}, colonnes "
                    f"{html_escape(as_)}</div>", unsafe_allow_html=True)
        c2.dataframe(hm.style.format("{:.1f}").background_gradient(cmap="Greens", axis=None), width="stretch")
    with tabs[3]:
        c1, c2 = st.columns(2)
        ui.market_list("Résultat à la mi-temps", k["Mi-temps 1X2"], {"1": hs_, "N": "Nul", "2": as_}, c1)
        ui.market_list("Buts en 1re mi-temps", k["Buts 1re mi-temps"],
                       {f"+{i}.5": f"Plus de {i},5" for i in range(3)}, c1)
        ui.market_list("Mi-temps / fin de match", k["Mi-temps / Fin de match"], target=c2)
    with tabs[4]:
        ah = {f"{hs_} {name.split()[1]}": w / max(1e-9, 1 - p) for name, (w, p) in k["Handicap asiatique"].items()}
        ui.market_list("Handicap asiatique (hors remboursement)", ah)
        ui.market_list("Écart final", k["Écart"])
    with tabs[5]:
        players = load_players()
        tot = lh + la
        any_ = False
        if national:
            st.caption("Calculé automatiquement à partir de tous les buteurs en sélection (4 dernières années, "
                       "le récent compte plus). ⚠️ Vérifie que le joueur est convoqué et titulaire : retire "
                       "les absents ci-dessous.")
        for team, lam in ((home, lh), (away, la)):
            if national:
                base = national_scorers(nat_goals, team, lam, tot)
                absents = st.multiselect(f"Absents / non convoqués — {team}",
                                         list(base.joueur) if not base.empty else [], key=f"abs_{team}")
                sp = national_scorers(nat_goals, team, lam, tot, absents=absents)
            else:
                sp = scorer_probs(players, team, lam, tot, results)
                api_sc = API.get("scorers", pd.DataFrame())
                if sp.empty and not api_sc.empty and "equipe" in api_sc:
                    absent = {a["nom"] for a in (ctx["abs_h"] if team == home else ctx["abs_a"])}
                    rows = api_sc[(api_sc.equipe == team) & ~api_sc.joueur.isin(absent)].copy()
                    if not rows.empty:
                        rows["xg"] = np.nan
                        rows["minutes_prevues"] = np.nan
                        rows["tireur_penalty"] = (rows.penaltys == rows.penaltys.max()) & (rows.penaltys > 0)
                        sp = scorer_probs(rows[COLUMNS].astype({"tireur_penalty": int}), team, lam, tot, results)
            st.markdown(f"**{team}** — {lam:.2f} but(s) attendu(s)")
            if sp.empty and national:
                st.info(f"Pas assez de buteurs récents connus pour {team}.")
                continue
            if sp.empty:
                st.info(f"Aucun joueur saisi pour {team}. Va dans « 👟 Données buteurs » pour ajouter "
                        "ses attaquants (buts, minutes, xG…).")
                continue
            any_ = True
            for _, pl in sp.head(8).iterrows():
                ui.bet_row(str(pl["joueur"]), f"Doublé {pl['P_doublé']:.0%} · 1er buteur {pl['P_1er_buteur']:.0%}",
                           f"{pl['P_buteur']:.0%}", f"cote juste {pl['cote_juste_buteur']:.2f}")
        p_nobody = np.exp(-tot)
        st.caption(f"Pas de buteur (0-0) : {pct(k['Score exact'].get('0-0', p_nobody))}")

    ui.section("Jouer ce match")
    st.markdown("**🎟️ Ajouter au ticket combiné**")
    s1, s2, s3, s4 = st.columns([2, 2, 1, 1])
    market_names = [n for n, v in k.items() if isinstance(v, dict) and n != "Handicap asiatique"]
    mk_name = s1.selectbox("Marché", market_names)
    sel = s2.selectbox("Sélection", list(k[mk_name].keys()))
    cote = s3.number_input("Cote proposée", 1.0, 1000.0, 2.0, 0.01)
    if s4.button("Ajouter"):
        st.session_state.ticket.append(dict(match=f"{home} – {away}", marche=mk_name, selection=sel,
                                            proba=float(k[mk_name][sel]), cote=cote))
        st.success("Ajouté au ticket.")

    st.markdown("**🎮 Parier avec de l'argent fictif**")
    pf = get_portfolio()
    opts = sim_options(k)
    g1, g2 = st.columns(2)
    smk = g1.selectbox("Marché ", list(opts), key="sim_mk")
    ssel = g2.selectbox("Sélection ", list(opts[smk]), key="sim_sel")
    sp = float(opts[smk][ssel])
    g3, g4, g5 = st.columns([1, 1, 1])
    scote = g3.number_input("Cote du bookmaker", 1.01, 1000.0, round(max(1.01, 0.95 / sp), 2), 0.01,
                            key=f"sim_cote_{smk}_{ssel}_{home}_{away}")
    smise = g4.number_input("Mise (€ fictifs)", 1.0, 100000.0, 10.0, 1.0, key="sim_mise")
    g5.markdown(f"<div style='padding-top:1.9rem;color:#94a3b8;font-size:.85rem'>Proba appli {sp:.0%} · "
                f"value {sp * scote - 1:+.0%}</div>", unsafe_allow_html=True)
    if st.button(f"🎮 Parier {smise:.0f} € fictifs · solde {sim.balance(pf)['solde']:.0f} €", width="stretch"):
        err = sim.place_bet(pf, home=home, away=away, comp=comp, market=smk, selection=ssel, odds=scote,
                            stake=smise, proba=sp, kind="nat" if national else "clubs")
        if err:
            st.error(err)
        else:
            sim.save_portfolio(pf)
            st.success("Pari fictif enregistré ! Il sera réglé automatiquement après le match (page 🎮 Simulateur).")

elif page == "🎮 Simu":
    ui.page_title("Simulateur", "Parie avec de l'argent fictif sur les vrais matchs, sans risque.")
    pf = get_portfolio()
    n_auto = sim.auto_settle(pf, results, nat_model(st.session_state.nonce)[1]
                             if any(b.get("kind") == "nat" and b["status"] == "en cours" for b in pf["bets"]) else None)
    if n_auto:
        sim.save_portfolio(pf)
        st.toast(f"{n_auto} pari(s) réglé(s) automatiquement")
    bal = sim.balance(pf)
    _gain = bal["solde"] + bal["en_jeu"] - pf["start"]
    ui.kpis([("Solde", f"{bal['solde']:.0f} €", f"{_gain:+.0f} € depuis le départ", "good" if _gain > 0 else ("bad" if _gain < 0 else "")),
             ("En jeu", f"{bal['en_jeu']:.0f} €", f"{bal['en_cours']} pari(s) en cours"),
             ("Réussite", f"{bal['gagnes'] / max(1, bal['gagnes'] + bal['perdus']):.0%}",
              f"✅ {bal['gagnes']} · ❌ {bal['perdus']}"),
             ("Rentabilité", f"{bal['roi']:+.0%}", "bénéfice / mises")])

    t_bet, t_mine, t_strat, t_save = st.tabs(["Parier", "Mes paris", "Tester une stratégie", "Sauvegarde"])

    with t_bet:
        up = upcoming_cached(m, st.session_state.nonce, _today)
        if up.empty:
            st.info("Aucun match à venir publié pour l'instant. Tu peux parier sur n'importe quelle affiche "
                    "(C1, sélections…) depuis 🔍 Analyse → « Parier avec de l'argent fictif ».")
        else:
            labels = {i: f"{comp_label(r.comp, COMPETITIONS)} · {r.home} – {r.away} · {pd.Timestamp(r.date):%d/%m} {r.heure}"
                      for i, r in up.iterrows()}
            i = st.selectbox("Match", list(labels), format_func=labels.get)
            r = up.loc[i]
            odds = {k_: (v if v == v else None) for k_, v in
                    dict(h=r.o_h, d=r.o_d, a=r.o_a, o25=r.o_o25, u25=r.o_u25).items()}
            res = engine.predict(m, r.home, r.away, r.comp, odds=odds if odds["h"] else None, allow_unknown=True)
            kk = res["markets"]
            ui.match_card(comp_label(r.comp, COMPETITIONS), f"{pd.Timestamp(r.date):%d/%m} {r.heure}", r.home, r.away,
                          kk["1X2"]["1"], kk["1X2"]["N"], kk["1X2"]["2"], next(iter(kk["Score exact"])), [])
            opts = sim_options(kk)
            c1, c2 = st.columns(2)
            mk = c1.selectbox("Marché", list(opts), key="sb_mk")
            sel = c2.selectbox("Sélection", list(opts[mk]), key="sb_sel")
            p_ = float(opts[mk][sel])
            real = {("1X2", "1"): odds["h"], ("1X2", "N"): odds["d"], ("1X2", "2"): odds["a"],
                    ("Plus/Moins buts", "+2.5"): odds["o25"], ("Plus/Moins buts", "-2.5"): odds["u25"]}.get((mk, sel))
            default = float(real) if real else round(max(1.01, 0.93 / p_), 2)
            c3, c4 = st.columns(2)
            cote = c3.number_input("Cote", 1.01, 1000.0, default, 0.01, key=f"sb_cote_{i}_{mk}_{sel}",
                                   help="Cote moyenne du marché si connue, sinon estimation (cote juste − 7 %). "
                                        "Mets la cote de ton bookmaker pour être réaliste.")
            mise = c4.number_input("Mise (€ fictifs)", 1.0, 100000.0, 10.0, 1.0, key="sb_mise")
            v = p_ * cote - 1
            st.markdown(f"Proba de l'appli **{p_:.0%}** · cote juste **{1 / p_:.2f}** · value "
                        f"**{v:+.0%}** {'✅' if v >= engine.MIN_EDGE else ''} · gain potentiel "
                        f"**{mise * (cote - 1):.2f} €**")
            if st.button(f"🎮 Valider le pari ({mise:.0f} €)", width="stretch", type="primary"):
                err = sim.place_bet(pf, home=r.home, away=r.away, comp=r.comp, market=mk, selection=sel, odds=cote,
                                    stake=mise, proba=p_, match_date=r.date)
                if err:
                    st.error(err)
                else:
                    sim.save_portfolio(pf)
                    st.success("Pari enregistré ✅")
                    st.rerun()

    with t_mine:
        bf = sim.bets_frame(pf)
        if bf.empty:
            st.info("Aucun pari pour l'instant.")
        else:
            curve = sim.bankroll_curve(pf)
            if not curve.empty:
                st.line_chart(curve.set_index("n")[["Bankroll (€)"]])
            tags = {"en cours": ("EN COURS", "y"), "gagné": ("GAGNÉ", "g"), "perdu": ("PERDU", "r"),
                    "annulé": ("REMBOURSÉ", "w")}
            for b in reversed(pf["bets"]):
                gain = (b["payout"] - b["stake"]) if b["status"] in ("gagné", "perdu") else 0.0
                right = f"{gain:+.2f} €" if b["status"] in ("gagné", "perdu") else f"{b['stake']:.0f} €"
                sub = (f"score {b['score']}" if b["score"] else f"gain possible {b['stake'] * (b['odds'] - 1):.0f} €")
                if b.get("market") == "Combiné":
                    done = sum(1 for lg in b["legs"] if lg["status"] != "en cours")
                    icon = {"gagné": "✅", "perdu": "❌", "annulé": "↩️", "en cours": "⏳"}
                    ui.bet_row(f"{b['selection']} ({len(b['legs'])} matchs)",
                               " · ".join(f"{icon[lg['status']]} {lg['home']}–{lg['away']} : {lg.get('label') or lg['selection']}"
                                          for lg in b["legs"]) + f" · cote {b['odds']:.2f} · mise {b['stake']:.0f} €",
                               right, sub if b["status"] != "en cours" else f"{done}/{len(b['legs'])} joués",
                               tags[b["status"]])
                else:
                    ui.bet_row(f"{b['home']} – {b['away']}", f"{b['market']} : {b['selection']} · cote {b['odds']:.2f} · "
                               f"mise {b['stake']:.0f} €", right, sub, tags[b["status"]])
                if b["status"] == "en cours":
                    act = st.selectbox("Régler à la main", ["—", "gagné", "perdu", "annulé"], key=f"set_{b['id']}",
                                       label_visibility="collapsed")
                    if act != "—":
                        sim.settle_manual(pf, b["id"], act)
                        sim.save_portfolio(pf)
                        st.rerun()
            st.caption("Les paris se règlent tout seuls dès que le score est publié (championnats, coupes d'Europe, "
                       "sélections). Seuls les matchs d'équipes « hors base » sont à régler à la main.")

    with t_strat:
        st.markdown("Rejoue **tous les matchs de la saison** avec une règle simple, aux **vraies cotes "
                    "d'avant-match**, en partant des pronos que l'appli donnait avant chaque match.")
        hs = hist.build_history(results, "clubs")
        sc1, sc2 = st.columns(2)
        strat = sc1.selectbox("Stratégie", list(sim.STRATEGIES), format_func=sim.STRATEGIES.get)
        if strat == "value":
            thr = sc2.slider("Value minimum", 0.0, 0.30, 0.05, 0.01, format="%.2f")
        else:
            lo, hi, dv = {"fav": (0.4, 0.9, 0.6), "over": (0.5, 0.85, 0.6), "under": (0.5, 0.85, 0.6),
                          "draw": (0.2, 0.4, 0.3), "outsider": (0.2, 0.5, 0.3)}[strat]
            thr = sc2.slider("Proba minimum", lo, hi, dv, 0.01, format="%.2f")
        lg = st.pills("Championnats ", [c for c in LEAGUES if c in set(hs.comp)], selection_mode="multi",
                      default=MAIN_LEAGUES, format_func=lambda c: comp_label(c, LEAGUES), key="strat_lg")
        sc3, sc4, sc5 = st.columns(3)
        mode = sc3.selectbox("Mise", ["fixe", "pct", "kelly"], format_func={
            "fixe": "Montant fixe (€)", "pct": "% de la bankroll", "kelly": "Kelly / 4 (selon la value)"}.get)
        amount = sc4.number_input("€ ou %", 0.5, 10000.0, 10.0 if mode == "fixe" else 2.0, 0.5,
                                  disabled=mode == "kelly")
        startb = sc5.number_input("Bankroll de départ", 10.0, 1e6, 1000.0, 50.0)
        best = st.toggle("Utiliser la meilleure cote du marché (sinon cote moyenne)", value=strat == "value")
        bt = sim.run_strategy(hs[hs.comp.isin(lg or [])], results, strat, thr, mode, amount, startb, best)
        if bt.empty:
            st.info("Aucun pari ne correspond à cette règle.")
        else:
            fin = bt.bankroll.iloc[-1]
            dd = float((bt.bankroll.cummax() - bt.bankroll).max())
            ui.kpis([("Bankroll finale", f"{fin:.0f} €", f"{fin - startb:+.0f} €", "good" if fin > startb else "bad"),
                     ("Paris", len(bt), f"✅ {int(bt.gagne.sum())} · ❌ {int((~bt.gagne).sum())} ({bt.gagne.mean():.0%})"),
                     ("Rentabilité", f"{bt.gain.sum() / bt.mise.sum():+.1%}", f"pire chute −{dd:.0f} €")])
            st.line_chart(bt.assign(n=range(1, len(bt) + 1)).set_index("n")[["bankroll"]])
            show = bt.sort_values("date", ascending=False).copy()
            show["date"] = show.date.dt.strftime("%d/%m")
            show["comp"] = show.comp.map(LEAGUES)
            show["proba"] = show.proba.map(pct)
            show["gagne"] = show.gagne.map({True: "✅", False: "❌"})
            st.dataframe(show.round(2), hide_index=True, width="stretch", height=420)
            st.caption("Résultat passé ≠ résultat futur. Une stratégie gagnante sur 100-200 paris peut "
                       "très bien être de la chance : regarde surtout la régularité de la courbe.")

    with t_save:
        st.caption("En ligne, le portefeuille est remis à zéro si le serveur redémarre : télécharge une "
                   "sauvegarde de temps en temps, tu pourras la recharger ici.")
        st.download_button("⬇️ Télécharger ma sauvegarde", data=sim.json.dumps(pf, ensure_ascii=False),
                           file_name="pronos_foot_simulation.json", mime="application/json", width="stretch")
        upf = st.file_uploader("⬆️ Restaurer une sauvegarde", type="json")
        if upf is not None and st.button("Restaurer"):
            try:
                data = sim.json.loads(upf.read())
                assert "bets" in data and "start" in data
                st.session_state.portfolio = data
                sim.save_portfolio(data)
                st.success("Sauvegarde restaurée.")
                st.rerun()
            except Exception:
                st.error("Fichier invalide.")
        st.markdown("---")
        nb = st.number_input("Nouvelle bankroll de départ (€)", 10.0, 1e6, 1000.0, 50.0)
        if st.button("🔄 Recommencer à zéro"):
            st.session_state.portfolio = sim.new_portfolio(nb)
            sim.save_portfolio(st.session_state.portfolio)
            st.rerun()

elif page == "📊 Bilan":
    ui.page_title("Bilan des pronos", "Le prono donné AVANT chaque match, comparé au vrai score.")

    LABELS = {**COMPETITIONS, **NAT_COMPS}
    scope_name = st.segmented_control("Quoi ?", ["⚽ Championnats", "🏆 Coupes d'Europe", "🌍 Sélections"],
                                      default="⚽ Championnats", label_visibility="collapsed") or "⚽ Championnats"
    scope = {"⚽": "clubs", "🏆": "euro", "🌍": "nat"}[scope_name[0]]
    if scope == "euro":
        st.caption("C1, Ligue Europa et Conférence depuis 2024-25. Prono = modèle seul (pas de cotes).")
    if scope == "nat":
        st.caption("Tous les matchs internationaux depuis septembre 2024, dont la Coupe du monde 2026. "
                   "Prono = modèle seul.")

    @st.cache_data(ttl=6 * 3600, show_spinner=False)
    def history(_df, scope, last_date, nonce):
        bar = st.progress(0.0, text="Calcul des pronos (une seule fois)…")
        h = hist.build_history(_df, scope, progress=lambda f: bar.progress(f, text="Calcul des pronos…"))
        bar.empty()
        return h

    src = nat_model(st.session_state.nonce)[1] if scope == "nat" else results
    h = history(src, scope, str(src.date.max()), st.session_state.nonce)
    if h.empty:
        st.info("Pas encore de matchs joués.")
        st.stop()
    filt = st.expander("🔎 Filtres (compétitions, équipe, période)")
    f1, f2 = filt.columns([3, 2])
    comps_avail = [c for c in LABELS if c in set(h.comp)]
    default = [c for c in MAIN_LEAGUES if c in comps_avail] if scope == "clubs" else comps_avail
    lg = f1.multiselect("Compétitions", comps_avail, default=default, format_func=lambda c: LABELS[c],
                        key=f"hist_lg_{scope}")
    teams = sorted(set(h.home) | set(h.away))
    team = f2.selectbox("Équipe", ["(toutes)"] + teams)
    d0, d1 = h.date.min().date(), h.date.max().date()
    per = filt.slider("Période", d0, d1, (d0, d1), format="DD/MM/YYYY")
    v = h[h.comp.isin(lg) & (h.date.dt.date >= per[0]) & (h.date.dt.date <= per[1])]
    if team != "(toutes)":
        v = v[(v.home == team) | (v.away == team)]
    if v.empty:
        st.warning("Aucun match avec ces filtres.")
        st.stop()

    tb, tr, tv = st.tabs(["Réussite", "Matchs joués", "Value bets"])
    with tb:
        s = hist.summary(v)
        ui.kpis([(row["Pari"], f"{row['% réussite']:.0%}", f"✅ {row['✅ Réussis']} · ❌ {row['❌ Ratés']}")
                 for _, row in s.iterrows()])
        st.caption(f"Sur {len(v)} matchs. Le score exact réussit rarement (~10-13 %), même quand c'est le "
                   "plus probable : c'est normal, il paye en conséquence.")
        st.markdown("**Résultat 1X2 selon la confiance du prono**")
        bc = hist.by_confidence(v)
        bc["% réussite"] = bc["% réussite"].map(pct)
        st.dataframe(bc, hide_index=True, width="stretch")
        st.markdown("**Réussite par compétition (1X2)**")
        g = v.groupby("comp").agg(Pronos=("ok_1x2", "size"), Reussis=("ok_1x2", "sum"))
        g["% réussite"] = (g.Reussis / g.Pronos).map(pct)
        g.index = g.index.map(LABELS)
        st.dataframe(g.rename(columns={"Reussis": "✅ Réussis"}), width="stretch")

    with tr:
        ok = lambda b: "✅" if b else "❌"  # noqa: E731
        t = pd.DataFrame({
            "Date": v.date.dt.strftime("%d/%m"),
            "Match": [f"{a} {sc} {b}" for a, sc, b in zip(v.home, v.score, v.away)],
            "1X2": [f"{ok(o)} {p} ({q:.0%})" for p, q, o in zip(v.prono_1x2, v.p_prono_1x2, v.ok_1x2)],
            "Buts": [f"{ok(o)} {p}" for p, o in zip(v.prono_buts, v.ok_buts)],
            "BTTS": [f"{ok(o)} {p}" for p, o in zip(v.prono_btts, v.ok_btts)],
            "Score prévu": [f"{ok(o)} {p}" for p, o in zip(v.prono_score, v.ok_score)],
            "Double ch.": [f"{ok(o)} {p}" for p, o in zip(v.prono_dc, v.ok_dc)],
            "MT": v.mt,
            "xG": [f"{a:.1f}-{b:.1f}" if np.isfinite(a) else "" for a, b in zip(v.hxg, v.axg)],
            "Champ.": v.comp.map(LABELS),
        })
        st.dataframe(t, hide_index=True, width="stretch", height=650)

    with tv:
        vb = hist.value_bets(v)
        if vb.empty:
            st.info("Aucun value bet détecté sur cette sélection.")
        else:
            n, w = len(vb), int(vb.gagne.sum())
            profit = float(vb.profit.sum())
            ui.kpis([("Value bets", n, f"✅ {w} · ❌ {n - w}"), ("Gagnés", f"{w / n:.0%}", "des paris"),
                     ("Bénéfice", f"{profit:+.1f} €", "1 € par pari", "good" if profit > 0 else "bad"),
                     ("Rentabilité", f"{profit / n:+.1%}", "bénéfice / mises")])
            st.caption("Mise fixe de 1 € par pari, à la meilleure cote du marché avant le match. Les value bets "
                       "sont souvent des outsiders : on en perd plus qu'on en gagne, c'est la cote qui doit "
                       "compenser. Sur quelques centaines de paris, le résultat reste très incertain.")
            st.line_chart(vb.assign(**{"Bénéfice cumulé (€)": vb.profit.cumsum()}).set_index("date")[
                ["Bénéfice cumulé (€)"]])
            sv = vb.sort_values("date", ascending=False).copy()
            sv["date"] = sv.date.dt.strftime("%d/%m")
            sv["comp"] = sv.comp.map(LABELS)
            sv["proba"] = sv.proba.map(pct)
            sv["gagne"] = sv.gagne.map({True: "✅", False: "❌"})
            sv["profit"] = sv.profit.map(lambda x: f"{x:+.2f} €")
            st.dataframe(sv, hide_index=True, width="stretch")

elif page == "🧾 Mon ticket":
    ui.page_title("Ticket combiné", "Assemble plusieurs paris et vois la vraie chance que tout passe.")
    t = st.session_state.ticket
    if not t:
        st.info("Ticket vide. Ajoute des sélections depuis « Analyse d'un match ».")
    else:
        df = pd.DataFrame(t)
        df["value"] = df.proba * df.cote - 1
        show = df.copy()
        show["proba"] = show.proba.map(pct)
        show["value"] = show.value.map(lambda v: f"{v:+.1%}")
        st.dataframe(show, hide_index=True, width="stretch")
        same_match = df.match.duplicated().any()
        p = float(np.prod(df.proba))
        o = float(np.prod(df.cote))
        ui.kpis([("Chance de passer", pct(p), "tous les paris justes"),
                 ("Cote totale", f"{o:.2f}", f"cote juste {1 / p:.2f}"),
                 ("Espérance", f"{p * o - 1:+.1%}", "par € misé", "good" if p * o > 1 else "bad")])
        if same_match:
            st.warning("Plusieurs sélections sur le même match : elles sont corrélées, la probabilité "
                       "affichée (produit) est approximative. Utilise plutôt les marchés combinés "
                       "(Résultat + BTTS, Résultat + 2.5) de l'analyse.")
        st.caption("Chaque sélection ajoutée multiplie la marge du bookmaker : un combiné n'est rentable que "
                   "si chaque sélection a de la value.")
        if st.button("Vider le ticket"):
            st.session_state.ticket = []
            st.rerun()

elif page == "🏆 Classement":
    ui.page_title("Classement de puissance", "Le vrai niveau des équipes, comparable entre championnats.")
    if (st.segmented_control("Type", ["⚽ Clubs", "🌍 Sélections"], default="⚽ Clubs",
                             label_visibility="collapsed") or "⚽").startswith("🌍"):
        nm, nd, _ = nat_model(st.session_state.nonce)
        act = set(active_teams(nd))
        r = nm.ratings()
        r = r[r.equipe.isin(act)].drop(columns=["ligue"]).reset_index(drop=True)
        r.index += 1
        st.caption("Buts marqués / encaissés attendus contre une sélection de niveau mondial moyen, terrain neutre.")
        st.dataframe(r.round(2), width="stretch", height=700)
        st.stop()
    st.caption("Buts marqués / encaissés attendus contre une équipe moyenne de Premier League, terrain neutre. "
               "Comparable entre championnats grâce aux matchs de C1 et aux montées/descentes.")
    lg = st.pills("Championnats", list(LEAGUES), selection_mode="multi", default=MAIN_LEAGUES,
                  format_func=lambda c: comp_label(c, LEAGUES), label_visibility="collapsed")
    r = m.ratings()
    r = r[r.ligue.isin(lg)].reset_index(drop=True)
    r.index += 1
    r["ligue"] = r.ligue.map(LEAGUES)
    st.dataframe(r.round(2), width="stretch", height=700)
    st.markdown("**Niveau des championnats** (log-force, 0 = moyenne de référence)")
    lv = pd.DataFrame({"championnat": [LEAGUES[l] for l in m.S], "niveau": list(m.S.values()),
                       "avantage domicile": [np.exp(m.H.get(l, 0)) - 1 for l in m.S]}).sort_values("niveau", ascending=False)
    lv["avantage domicile"] = lv["avantage domicile"].map(lambda v: f"+{v:.0%} de buts")
    st.dataframe(lv.round(3), hide_index=True)

elif page == "👟 Buteurs":
    ui.page_title("Données buteurs", "Les stats des attaquants de clubs (les sélections sont automatiques).")
    st.markdown(
        "Les stats individuelles ne sont pas disponibles en libre accès : saisis-les (ou copie-colle depuis "
        "FBref, Sofascore, L'Équipe…) **pour le championnat en cours**. Il suffit des 4-6 joueurs offensifs "
        "principaux par équipe.\n\n"
        "- `buts` : buts en championnat (penaltys inclus) · `penaltys` : penaltys marqués\n"
        "- `xg` *(optionnel)* : xG en championnat — rend l'estimation plus stable\n"
        "- `tireur_penalty` : 1 si c'est le tireur désigné\n"
        "- `minutes_prevues` *(optionnel)* : 90 titulaire sûr, ~65 s'il sort souvent, ~20 remplaçant, 0 absent")
    players = load_players()
    teams = sorted(m.teams)
    flt = st.selectbox("Équipe à éditer", ["(toutes)"] + teams)
    view = players if flt == "(toutes)" else players[players.equipe == flt]
    edited = st.data_editor(
        view, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={"equipe": st.column_config.SelectboxColumn("equipe", options=teams, required=True,
                                                                  default=None if flt == "(toutes)" else flt)})
    if st.button("💾 Enregistrer"):
        rest = players if flt == "(toutes)" else players[players.equipe != flt]
        out = edited if flt == "(toutes)" else pd.concat([rest, edited], ignore_index=True)
        save_players(out.dropna(subset=["equipe", "joueur"]))
        st.success("Enregistré dans data/joueurs.csv")

elif page == "📈 Fiabilité":
    ui.page_title("Fiabilité du modèle", "Comment l'appli se compare aux bookmakers sur les matchs passés.")
    st.markdown(
        "Le modèle est ré-entraîné toutes les 3 semaines **avec uniquement le passé**, puis il prédit les "
        "matchs suivants des 5 grands championnats. On compare à la cote moyenne des bookmakers.")
    res = engine.load_backtest()
    if st.button("Relancer le backtest (1-2 min)"):
        with st.spinner("Backtest en cours…"):
            res = engine.run_backtest()
    if not res:
        st.info("Aucun backtest enregistré. Clique sur le bouton ci-dessus.")
    else:
        ev = res["evaluation"]
        st.caption(f"{ev['n']} matchs depuis le {res['debut']} · calculé le {res['date']}")
        comp_df = pd.DataFrame({
            "Source": ["Modèle seul", "Marché (ouverture)", "Marché (clôture)"],
            "Log-loss (↓ mieux)": [ev["modele"]["logloss"], ev["marche_ouverture"]["logloss"],
                                   ev["marche_cloture"]["logloss"]],
            "RPS (↓ mieux)": [ev["modele"]["rps"], ev["marche_ouverture"]["rps"], ev["marche_cloture"]["rps"]]})
        st.dataframe(comp_df.round(4), hide_index=True)
        st.markdown("**Stratégies de value bet simulées (1X2, meilleure cote du marché)**")
        s = pd.DataFrame(res["strategies"]).T
        s["roi_mise_fixe"] = s.roi_mise_fixe.map(lambda v: f"{v:+.1%}")
        s["roi_kelly"] = s.roi_kelly.map(lambda v: f"{v:+.1%}")
        st.dataframe(s, width="stretch")
        st.caption("alpha = poids du modèle (0 = consensus du marché pur, 1 = modèle seul). Peu de paris = "
                   "résultat très incertain. Les « meilleures cotes » ne sont pas toujours accessibles en France.")
        st.markdown("**Calibration** — quand le modèle annonce X %, ça arrive-t-il X % du temps ?")
        cal = pd.DataFrame(res["calibration"])
        cal = cal.rename(columns={"prevu": "proba annoncée", "observe": "fréquence observée"})
        st.line_chart(cal.set_index("proba annoncée")[["fréquence observée"]])
        st.dataframe(cal.round(3), hide_index=True)

elif page == "⚙️ Données":
    ui.page_title("Données", "D'où viennent les chiffres, et mise à jour manuelle.")
    ui.kpis([("Matchs analysés", f"{m.n_matches:,}".replace(",", " "), "clubs, 4 saisons"),
             ("Dernier résultat", f"{pd.Timestamp(m.ref_date - pd.Timedelta(days=1)):%d/%m/%Y}", "mise à jour auto ~6 h"),
             ("Équipes", len(m.teams), "23 championnats + coupes")])
    ui.section("API-Football (compos, blessés, vraies cotes)")
    if apifootball.enabled():
        n_inj = len(API.get("injuries", [])) if API.get("ok") else 0
        ui.kpis([("Statut", "Connectée" if API.get("ok") else "Erreur", API.get("error") or "clé valide",
                  "good" if API.get("ok") else "bad"),
                 ("Requêtes aujourd'hui", f"{apifootball.usage_today()} / 100", "offre gratuite"),
                 ("Absents suivis", n_inj, "3 prochains jours")])
    else:
        st.info("Pas encore de clé API-Football : l'appli fonctionne, mais sans compos, blessés ni vraies cotes "
                "de coupe. Ajoute ta clé dans Streamlit → ⋮ → Settings → Secrets :  API_FOOTBALL_KEY = \"ta_clé\"")
    if st.button("🔄 Mettre à jour maintenant", type="primary", width="stretch", on_click=refresh_data):
        st.toast("Mise à jour lancée")
    st.markdown("- **Résultats, tirs, xG, cotes, calendrier des championnats** : football-data.co.uk\n"
                "- **Coupes d'Europe** (calendrier + résultats) : fixturedownload.com et openfootball\n"
                "- **Sélections nationales et buteurs** : base internationale ouverte (martj42)\n\n"
                "Le modèle (Dixon-Coles + xG + forme récente, calé sur les cotes du marché) est recalculé chaque jour.")
    st.caption("Les paris restent un jeu de hasard. Ne mise que ce que tu peux perdre. "
               "Joueurs Info Service : 09 74 75 13 13.")

ui.footer()
