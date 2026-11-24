"""Appli web de pronostics football — lancer avec :  streamlit run app.py"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from pronos import engine
from pronos.data import COMPETITIONS, CUPS, LEAGUES, MAIN_LEAGUES, NAT_COMPS
from pronos.nationals import active_teams, national_scorers
from pronos import historique as hist
from pronos import ui
from pronos import simulation as sim
from pronos.badges import comp_label, crest, team_text
from pronos.scorers import COLUMNS, load_players, save_players, scorer_probs

st.set_page_config(page_title="Pronos Foot", page_icon="⚽", layout="wide", initial_sidebar_state="collapsed")
ui.inject()


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
info = getattr(m, "info", {})

# ------------------------------------------------------------------ navigation
PAGES = ["📅 Matchs", "🔍 Analyse", "🎮 Simulateur", "📊 Bilan", "🎟️ Ticket", "🏆 Classement", "👟 Buteurs",
         "📈 Fiabilité"]
ui.brand(f"{m.n_matches:,} matchs analysés · données au "
         f"{pd.Timestamp(m.ref_date - pd.Timedelta(days=1)):%d/%m/%Y}".replace(",", " "))
st.session_state.setdefault("page", PAGES[0])
if st.session_state.page not in PAGES:
    st.session_state.page = PAGES[0]
page = st.pills("Menu", PAGES, label_visibility="collapsed", key="page") or PAGES[0]
for _k, _v in dict(ch=0.0, cd=0.0, ca=0.0, co=0.0, cu=0.0).items():
    st.session_state.setdefault(_k, _v)


QUICK_COMPS = ["F1", "E0", "SP1", "I1", "D1", "CL", "EL", "ECL"]


def open_match(comp, home, away, odds):
    """Bouton « Analyser » d'une carte : ouvre l'analyse détaillée pré-remplie (équipes + cotes)."""
    st.session_state.page = "🔍 Analyse"
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
if st.sidebar.button("🔄 Mettre à jour les données"):
    model.clear()
    nat_model.clear()
    st.session_state.nonce += 1
    st.rerun()
st.sidebar.markdown("---")
st.sidebar.caption("Le modèle donne des probabilités, pas des certitudes. Ne mise que ce que tu peux "
                   "perdre. Aide : Joueurs Info Service 09 74 75 13 13.")


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
if page == "📅 Matchs":
    st.header("📅 Prochains matchs")
    _info = st.expander("ℹ️ Comment lire les cartes")
    _info.caption("Calendrier et cotes moyennes du marché : football-data.co.uk. Les probabilités combinent le "
               f"modèle ({int(engine.ALPHA_MODEL * 100)} %) et le consensus des bookmakers "
               f"({int((1 - engine.ALPHA_MODEL) * 100)} %). Value = proba × meilleure cote − 1 ≥ "
               f"{engine.MIN_EDGE:.0%}.")
    _info.caption("Coupes d'Europe et sélections nationales : aucun calendrier gratuit n'est disponible → "
               "choisis l'affiche dans « 🔍 Analyse d'un match » (Ligue des champions, Ligue Europa, "
               "Conférence, Coupe du monde, Euro, qualifs, Ligue des nations, amicaux).")
    t_all = engine.upcoming_table(m, leagues=list(LEAGUES))
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
        only_value = f1.toggle("Seulement les value bets")
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
            days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
            months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
                      "nov.", "déc."]
            for d, grp in t.rename(columns={"P+2.5": "P_o25"}).groupby("date", sort=True):
                d = pd.Timestamp(d)
                st.markdown(f'<div class="pf-day">{days[d.weekday()]} {d.day} {months[d.month - 1]}</div>',
                            unsafe_allow_html=True)
                for i, r in enumerate(grp.itertuples()):
                    chips = [(f"+2.5 buts {r.P_o25:.0%}", False), (f"Les 2 marquent {r.BTTS:.0%}", False),
                             (f"xG {r.xg_dom:.1f} – {r.xg_ext:.1f}", False)]
                    if r.value:
                        chips.insert(0, (f"💰 Value : {r.value}", True))
                    if r.approx:
                        chips.insert(0, ("⚠️ Estimation : équipe hors base", False))
                    ui.match_card(comp_label(r.comp, COMPETITIONS), str(r.heure), r.home, r.away, r.P1, r.PN, r.P2,
                                  r.score_probable.split(" ")[0], chips)
                    if not r.approx:
                      st.button("Analyse complète ›", key=f"an_{r.comp}_{r.home}_{r.away}",
                              on_click=open_match, args=(r.comp, r.home, r.away,
                                                         (r.o_h, r.o_d, r.o_a, r.o_o25, r.o_u25)),
                              width="stretch")

elif page == "🔍 Analyse":
    st.header("🔍 Analyse d'un match")
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
        st.caption("Noms des pays en anglais (France, Spain, Germany, England, Morocco, Algeria…).")
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
        if comp in CUPS:
            st.caption("Coupes d'Europe : clubs des 23 championnats couverts (5 grands, Portugal, Pays-Bas, "
                       "Belgique, Turquie, Écosse, Grèce, Autriche, Suisse, Danemark, Norvège, Suède, "
                       "Pologne, Roumanie + 2es divisions).")

    with st.expander("💶 Cotes du bookmaker (fortement recommandé : cale le modèle sur le marché)"):
        o1, o2, o3, o4, o5 = st.columns(5)
        ch = o1.number_input("Cote 1", 0.0, 100.0, step=0.01, key="ch")
        cd = o2.number_input("Cote N", 0.0, 100.0, step=0.01, key="cd")
        ca = o3.number_input("Cote 2", 0.0, 100.0, step=0.01, key="ca")
        co = o4.number_input("Cote +2.5", 0.0, 20.0, step=0.01, key="co")
        cu = o5.number_input("Cote −2.5", 0.0, 20.0, step=0.01, key="cu")
    with st.expander("🩹 Ajustements (blessures, suspensions, rotation, météo…)"):
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
    r = engine.predict(mod, home, away, comp, neutral, odds=odds, adj=adj)
    k = r["markets"]
    lh, la = r["lambda"]

    if r["lambda_market"]:
        note = "modèle + marché"
        st.caption(f"Buts attendus — modèle : {r['lambda_model'][0]:.2f}–{r['lambda_model'][1]:.2f} · "
                   f"marché : {r['lambda_market'][0]:.2f}–{r['lambda_market'][1]:.2f} · "
                   f"retenu : {lh:.2f}–{la:.2f}")
    else:
        note = "modèle seul · ajoute les cotes"
    ui.hero(comp_label(comp, NAT_COMPS if national else COMPETITIONS), home, away, lh, la, k, note,
            crest(home, national, 52), crest(away, national, 52))

    if r["all_value"]:
        st.markdown("**Analyse des cotes saisies**")
        vt = pd.DataFrame(r["all_value"])
        vt["proba"] = vt.proba.map(pct)
        vt["value"] = vt.value.map(lambda v: f"{v:+.1%}")
        vt["kelly"] = vt.kelly.map(lambda v: f"{v:.1%} de la bankroll")
        vt["jouable"] = vt.jouable.map({True: "✅ value", False: "❌"})
        st.dataframe(vt, hide_index=True, width="stretch")

    tabs = st.tabs(["Score exact", "Buts", "Résultat", "Handicaps", "Mi-temps", "Buteurs"])
    with tabs[0]:
        c1, c2 = st.columns([3, 2])
        M = k["matrix"][:7, :7]
        hm = pd.DataFrame(M * 100, index=[f"{home} {i}" for i in range(7)], columns=[f"{j}" for j in range(7)])
        c1.markdown(f"Probabilité (%) de chaque score — lignes : buts **{home}**, colonnes : buts **{away}**")
        c1.dataframe(hm.style.format("{:.1f}").background_gradient(cmap="Greens", axis=None),
                     width="stretch")
        c2.dataframe(market_table(k["Score exact"]), hide_index=True, width="stretch")
        c2.caption(f"Autres scores : {pct(k['Score exact (autre)'])}")
    with tabs[1]:
        c1, c2, c3 = st.columns(3)
        c1.markdown("**Plus de … buts**"); c1.dataframe(market_table(k["Plus/Moins buts"]), hide_index=True)
        c1.markdown("**Les deux équipes marquent**"); c1.dataframe(market_table(k["BTTS"]), hide_index=True)
        c2.markdown(f"**Buts {home}**"); c2.dataframe(market_table(k["Buts domicile"]), hide_index=True)
        c2.markdown(f"**Buts {away}**"); c2.dataframe(market_table(k["Buts extérieur"]), hide_index=True)
        c3.markdown("**Nombre exact de buts**"); c3.dataframe(market_table(k["Nombre exact de buts"]), hide_index=True)
        c3.markdown("**Pair / impair**"); c3.dataframe(market_table(k["Pair/Impair"]), hide_index=True)
    with tabs[2]:
        c1, c2, c3 = st.columns(3)
        c1.markdown("**Double chance**"); c1.dataframe(market_table(k["Double chance"]), hide_index=True)
        c1.markdown("**Remboursé si nul**"); c1.dataframe(market_table(k["Remboursé si nul"]), hide_index=True)
        c2.markdown("**Résultat + BTTS**"); c2.dataframe(market_table(k["Résultat + BTTS"]), hide_index=True)
        c2.markdown("**Résultat + 2.5**"); c2.dataframe(market_table(k["Résultat + 2.5"]), hide_index=True)
        c3.markdown("**Écart final**"); c3.dataframe(market_table(k["Écart"]), hide_index=True)
        c3.markdown("**Clean sheet / gagne sans encaisser**")
        c3.dataframe(market_table({**{f"CS {a}": b for a, b in k["Clean sheet"].items()},
                                   **{f"Gagne à zéro {a}": b for a, b in k["Gagne sans encaisser"].items()}}),
                     hide_index=True)
    with tabs[3]:
        rows = [{"Ligne": f"{home} {name.split()[1]}", "Gagné": pct(w), "Remboursé": pct(p),
                 "Cote juste": round((1 - p) / w + 0, 2) if w > 0 else None}
                for name, (w, p) in k["Handicap asiatique"].items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Cote juste en handicap asiatique : tient compte du remboursement sur les lignes entières.")
    with tabs[4]:
        c1, c2, c3 = st.columns(3)
        c1.markdown("**Résultat à la mi-temps**"); c1.dataframe(market_table(k["Mi-temps 1X2"]), hide_index=True)
        c2.markdown("**Mi-temps / fin de match**"); c2.dataframe(market_table(k["Mi-temps / Fin de match"]), hide_index=True)
        c3.markdown("**Buts en 1re mi-temps**"); c3.dataframe(market_table(k["Buts 1re mi-temps"]), hide_index=True)
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
            st.markdown(f"**{team}** — {lam:.2f} but(s) attendu(s)")
            if sp.empty and national:
                st.info(f"Pas assez de buteurs récents connus pour {team}.")
                continue
            if sp.empty:
                st.info(f"Aucun joueur saisi pour {team}. Va dans « 👟 Données buteurs » pour ajouter "
                        "ses attaquants (buts, minutes, xG…).")
                continue
            any_ = True
            show = sp.copy()
            for c in ["P_buteur", "P_doublé", "P_1er_buteur"]:
                show[c] = show[c].map(pct)
            st.dataframe(show.round(2), hide_index=True, width="stretch")
        p_nobody = np.exp(-tot)
        st.caption(f"Pas de buteur (0-0) : {pct(k['Score exact'].get('0-0', p_nobody))}")

    st.markdown("---")
    st.markdown("**➕ Ajouter une sélection au ticket**")
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

elif page == "🎮 Simulateur":
    st.header("🎮 Simulateur")
    st.caption("Joue avec de l'argent fictif pour tester tes idées sans risque.")
    pf = get_portfolio()
    n_auto = sim.auto_settle(pf, results, nat_model(st.session_state.nonce)[1]
                             if any(b.get("kind") == "nat" and b["status"] == "en cours" for b in pf["bets"]) else None)
    if n_auto:
        sim.save_portfolio(pf)
        st.toast(f"{n_auto} pari(s) réglé(s) automatiquement")
    bal = sim.balance(pf)
    b1, b2, b3 = st.columns(3)
    b1.metric("Solde fictif", f"{bal['solde']:.2f} €", f"{bal['solde'] + bal['en_jeu'] - pf['start']:+.2f} €")
    b2.metric("En jeu", f"{bal['en_jeu']:.2f} €", f"{bal['en_cours']} pari(s)", delta_color="off")
    b3.metric("Réussite", f"{bal['gagnes'] / max(1, bal['gagnes'] + bal['perdus']):.0%}",
              f"✅ {bal['gagnes']} · ❌ {bal['perdus']} · ROI {bal['roi']:+.0%}", delta_color="off")

    t_bet, t_mine, t_strat, t_save = st.tabs(["➕ Parier", "📋 Mes paris", "🧪 Tester une stratégie", "💾 Sauvegarde"])

    with t_bet:
        up = engine.upcoming_table(m, leagues=list(LEAGUES))
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
            icon = {"en cours": "⏳", "gagné": "✅", "perdu": "❌", "annulé": "↩️"}
            for b in reversed(pf["bets"]):
                gain = (b["payout"] - b["stake"]) if b["status"] in ("gagné", "perdu") else None
                cols = st.columns([5, 2])
                cols[0].markdown(
                    f"{icon[b['status']]} **{b['home']} – {b['away']}** {('· ' + b['score']) if b['score'] else ''}  \n"
                    f"<span style='color:#94a3b8;font-size:.85rem'>{b['market']} : <b>{b['selection']}</b> @ "
                    f"{b['odds']:.2f} · mise {b['stake']:.0f} €"
                    f"{f' · {gain:+.2f} €' if gain is not None else ''}</span>", unsafe_allow_html=True)
                if b["status"] == "en cours":
                    act = cols[1].selectbox("Régler", ["—", "gagné", "perdu", "annulé"], key=f"set_{b['id']}",
                                            label_visibility="collapsed")
                    if act != "—":
                        sim.settle_manual(pf, b["id"], act)
                        sim.save_portfolio(pf)
                        st.rerun()
            st.caption("Les paris sur les championnats et les sélections se règlent tout seuls dès que le résultat "
                       "est publié. Pour la C1 / C3 / C4 2026-27 (résultats pas encore publiés), règle-les à la main.")

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
            k1, k2, k3 = st.columns(3)
            k1.metric("Bankroll finale", f"{fin:.0f} €", f"{fin - startb:+.0f} €")
            k2.metric("Paris", len(bt), f"✅ {int(bt.gagne.sum())} · ❌ {int((~bt.gagne).sum())} "
                                        f"({bt.gagne.mean():.0%})", delta_color="off")
            k3.metric("ROI", f"{bt.gain.sum() / bt.mise.sum():+.1%}", f"pire chute −{dd:.0f} €", delta_color="off")
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
    st.header("📊 Résultats & bilan")
    st.caption("Prono donné AVANT chaque match (modèle ré-entraîné chaque semaine avec uniquement les "
               "matchs précédents + cotes d'avant-match), comparé au vrai résultat.")

    LABELS = {**COMPETITIONS, **NAT_COMPS}
    scope_name = st.radio("Quoi ?", ["⚽ Championnats (saison en cours)", "🏆 Coupes d'Europe",
                                     "🌍 Sélections nationales"], horizontal=True, label_visibility="collapsed")
    scope = {"⚽": "clubs", "🏆": "euro", "🌍": "nat"}[scope_name[0]]
    if scope == "euro":
        st.caption("C1, Ligue Europa, Conférence (+ tours préliminaires) des saisons 2024-25 et 2025-26 "
                   "(2026-27 pas encore publiée). Pas de cotes disponibles : prono = modèle seul.")
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

    tb, tr, tv = st.tabs(["✅ Bilan réussite", "📋 Résultats & pronos", "💰 Value bets"])
    with tb:
        s = hist.summary(v)
        c = st.columns(len(s))
        for col, (_, row) in zip(c, s.iterrows()):
            col.metric(row["Pari"], f"{row['% réussite']:.0%}",
                       f"✅ {row['✅ Réussis']}  ·  ❌ {row['❌ Ratés']}", delta_color="off")
        show = s.copy()
        show["% réussite"] = show["% réussite"].map(pct)
        show["% attendu"] = show["% attendu"].map(pct)
        st.dataframe(show, hide_index=True, width="stretch")
        st.caption("« % attendu » = moyenne des probabilités annoncées. Si les deux colonnes sont proches, "
                   "les probabilités de l'appli sont honnêtes. Le score exact réussit rarement (~10-13 %) "
                   "même quand c'est le plus probable : c'est normal, il paye en conséquence.")
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
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Value bets", n, f"✅ {w}  ·  ❌ {n - w}", delta_color="off")
            c2.metric("% gagnés", f"{w / n:.0%}")
            c3.metric("Bénéfice (mise 1 €)", f"{profit:+.2f} €")
            c4.metric("ROI", f"{profit / n:+.1%}")
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

elif page == "🎟️ Ticket":
    st.header("🎟️ Ticket combiné")
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
        c1, c2, c3 = st.columns(3)
        c1.metric("Probabilité du combiné", pct(p))
        c2.metric("Cote totale", f"{o:.2f}", f"cote juste {1 / p:.2f}", delta_color="off")
        c3.metric("Espérance par € misé", f"{p * o - 1:+.1%}")
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
    st.header("🏆 Classement de puissance")
    if st.radio("Type", ["⚽ Clubs", "🌍 Sélections nationales"], horizontal=True,
                label_visibility="collapsed").startswith("🌍"):
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
    st.header("👟 Données buteurs")
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
    st.header("📈 Fiabilité du modèle (backtest)")
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

ui.footer()
