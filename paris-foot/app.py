"""Appli web de pronostics football — lancer avec :  streamlit run app.py"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from pronos import engine
from pronos.data import COMPETITIONS, LEAGUES, MAIN_LEAGUES
from pronos.scorers import COLUMNS, load_players, save_players, scorer_probs

st.set_page_config(page_title="Pronos Foot", page_icon="⚽", layout="wide")


@st.cache_resource(ttl=6 * 3600, show_spinner="Téléchargement des données et calcul du modèle…")
def model(_nonce: int = 0):
    return engine.get_model(force=_nonce > 0)


if "nonce" not in st.session_state:
    st.session_state.nonce = 0
if "ticket" not in st.session_state:
    st.session_state.ticket = []

m, results = model(st.session_state.nonce)
info = getattr(m, "info", {})

# ------------------------------------------------------------------ barre latérale
st.sidebar.title("⚽ Pronos Foot")
page = st.sidebar.radio("Menu", ["📅 Prochains matchs", "🔍 Analyse d'un match", "🎟️ Ticket combiné",
                                 "🏆 Classement de puissance", "👟 Données buteurs", "📈 Fiabilité du modèle"])
st.sidebar.caption(
    f"{m.n_matches:,} matchs analysés · dernier résultat : {pd.Timestamp(m.ref_date - pd.Timedelta(days=1)).date()}"
    .replace(",", " "))
if st.sidebar.button("🔄 Mettre à jour les données"):
    model.clear()
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


def team_label(t):
    return f"{t} ({m.team_league[t]})"


# ------------------------------------------------------------------ pages
if page == "📅 Prochains matchs":
    st.header("📅 Prochains matchs")
    st.caption("Calendrier et cotes moyennes du marché : football-data.co.uk. Les probabilités combinent le "
               f"modèle ({int(engine.ALPHA_MODEL * 100)} %) et le consensus des bookmakers "
               f"({int((1 - engine.ALPHA_MODEL) * 100)} %). Value = proba × meilleure cote − 1 ≥ "
               f"{engine.MIN_EDGE:.0%}.")
    leagues = st.multiselect("Championnats", list(LEAGUES), default=MAIN_LEAGUES,
                             format_func=lambda c: LEAGUES[c])
    t = engine.upcoming_table(m, leagues=leagues)
    if t.empty:
        st.info("Pas de matchs à venir publiés pour l'instant (le fichier est mis à jour en milieu de "
                "semaine). Utilise « Analyse d'un match » pour n'importe quelle affiche, y compris en C1.")
    else:
        only_value = st.toggle("Seulement les matchs avec value bet")
        if only_value:
            t = t[t.value != ""]
        show = t.copy()
        for c in ["P1", "PN", "P2", "P+2.5", "BTTS"]:
            show[c] = (show[c] * 100).round(1)
        show["comp"] = show["comp"].map(LEAGUES)
        st.dataframe(show.drop(columns=["cale_marche"]).round(2), hide_index=True, width="stretch",
                     column_config={c: st.column_config.ProgressColumn(c, format="%.1f %%", min_value=0,
                                                                       max_value=100)
                                    for c in ["P1", "PN", "P2", "P+2.5", "BTTS"]})

elif page == "🔍 Analyse d'un match":
    st.header("🔍 Analyse d'un match")
    c1, c2, c3 = st.columns([2, 2, 1])
    comp = c3.selectbox("Compétition", ["CL"] + list(LEAGUES), index=1 + list(LEAGUES).index("F1"),
                        format_func=lambda c: COMPETITIONS[c])
    pool = sorted(m.teams) if comp == "CL" else sorted(t for t in m.teams if m.team_league[t] == comp) or m.teams
    default_h = pool.index("Paris SG") if "Paris SG" in pool else 0
    home = c1.selectbox("Domicile", pool, index=default_h, format_func=team_label)
    away = c2.selectbox("Extérieur", pool, index=1 if default_h == 0 else 0, format_func=team_label)
    neutral = c3.checkbox("Terrain neutre (finale)")

    with st.expander("💶 Cotes du bookmaker (fortement recommandé : cale le modèle sur le marché)"):
        o1, o2, o3, o4, o5 = st.columns(5)
        ch = o1.number_input("Cote 1", 0.0, 100.0, 0.0, 0.01)
        cd = o2.number_input("Cote N", 0.0, 100.0, 0.0, 0.01)
        ca = o3.number_input("Cote 2", 0.0, 100.0, 0.0, 0.01)
        co = o4.number_input("Cote +2.5", 0.0, 20.0, 0.0, 0.01)
        cu = o5.number_input("Cote −2.5", 0.0, 20.0, 0.0, 0.01)
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
    r = engine.predict(m, home, away, comp, neutral, odds=odds, adj=adj)
    k = r["markets"]
    lh, la = r["lambda"]

    st.subheader(f"{home} – {away}")
    if r["lambda_market"]:
        st.caption(f"Buts attendus — modèle : {r['lambda_model'][0]:.2f}–{r['lambda_model'][1]:.2f} · "
                   f"marché : {r['lambda_market'][0]:.2f}–{r['lambda_market'][1]:.2f} · "
                   f"**retenu : {lh:.2f}–{la:.2f}**")
    else:
        st.caption(f"Buts attendus (modèle seul) : **{lh:.2f} – {la:.2f}**. Ajoute les cotes pour plus de précision.")
    x1, x2, x3, x4, x5 = st.columns(5)
    x1.metric(f"Victoire {home}", pct(k["1X2"]["1"]), f"cote juste {1 / k['1X2']['1']:.2f}", delta_color="off")
    x2.metric("Nul", pct(k["1X2"]["N"]), f"cote juste {1 / k['1X2']['N']:.2f}", delta_color="off")
    x3.metric(f"Victoire {away}", pct(k["1X2"]["2"]), f"cote juste {1 / k['1X2']['2']:.2f}", delta_color="off")
    x4.metric("Plus de 2.5 buts", pct(k["Plus/Moins buts"]["+2.5"]))
    x5.metric("Les deux marquent", pct(k["BTTS"]["Oui"]))

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
        for team, lam in ((home, lh), (away, la)):
            sp = scorer_probs(players, team, lam, tot, results)
            st.markdown(f"**{team}** — {lam:.2f} but(s) attendu(s)")
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

elif page == "🎟️ Ticket combiné":
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

elif page == "🏆 Classement de puissance":
    st.header("🏆 Classement de puissance")
    st.caption("Buts marqués / encaissés attendus contre une équipe moyenne de Premier League, terrain neutre. "
               "Comparable entre championnats grâce aux matchs de C1 et aux montées/descentes.")
    lg = st.multiselect("Championnats", list(LEAGUES), default=MAIN_LEAGUES, format_func=lambda c: LEAGUES[c])
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

elif page == "👟 Données buteurs":
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

elif page == "📈 Fiabilité du modèle":
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
