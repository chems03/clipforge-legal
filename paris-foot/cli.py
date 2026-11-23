#!/usr/bin/env python3
"""Interface en ligne de commande.

  python cli.py maj                         # télécharge / met à jour les données
  python cli.py match "Paris SG" "Marseille" --comp F1
  python cli.py match "Arsenal" "Paris SG" --comp CL --cotes 2.10 3.50 3.60 --cote-o25 1.80
  python cli.py prochains --ligues F1 E0
  python cli.py classement --ligue F1
  python cli.py backtest                    # mesure la fiabilité (≈ 1-2 min)
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from pronos import engine
from pronos.data import COMPETITIONS, MAIN_LEAGUES


def pct(x):
    return f"{100 * x:5.1f} %"


def cmd_match(a):
    m, df = engine.get_model()
    home, away = engine.resolve_team(m, a.dom), engine.resolve_team(m, a.ext)
    odds = dict(h=a.cotes[0], d=a.cotes[1], a=a.cotes[2]) if a.cotes else None
    if odds and a.cote_o25:
        odds.update(o25=a.cote_o25[0], u25=a.cote_o25[1] if len(a.cote_o25) > 1 else None)
    r = engine.predict(m, home, away, a.comp, neutral=a.neutre, odds=odds)
    k = r["markets"]
    print(f"\n{home} – {away}  ({COMPETITIONS.get(a.comp, a.comp)}{', terrain neutre' if a.neutre else ''})")
    print(f"Buts attendus : modèle {r['lambda_model'][0]:.2f} – {r['lambda_model'][1]:.2f}", end="")
    if r["lambda_market"]:
        print(f" | marché {r['lambda_market'][0]:.2f} – {r['lambda_market'][1]:.2f}"
              f" | retenu {r['lambda'][0]:.2f} – {r['lambda'][1]:.2f}")
    else:
        print()
    for name in ["1X2", "Double chance", "BTTS", "Plus/Moins buts", "Mi-temps / Fin de match"]:
        print(f"\n[{name}]")
        for sel, p in k[name].items():
            print(f"  {sel:>6} {pct(p)}   cote juste {1 / p:6.2f}")
    print("\n[Scores exacts les plus probables]")
    for s, p in list(k["Score exact"].items())[:10]:
        print(f"  {s:>5} {pct(p)}   cote juste {1 / p:6.2f}")
    if r["value"]:
        print("\n[Value bets 1X2 / +-2.5]")
        for v in r["value"]:
            print(f"  {v['pari']:<10} proba {pct(v['proba'])}  cote {v['cote']:.2f}  value {v['value']:+.1%}"
                  f"  Kelly/4 {v['kelly']:.1%}")


def cmd_prochains(a):
    m, df = engine.get_model()
    t = engine.upcoming_table(m, leagues=a.ligues)
    if t.empty:
        print("Aucun match à venir dans fixtures.csv pour ces championnats.")
        return
    cols = ["date", "comp", "home", "away", "P1", "PN", "P2", "score_probable", "P+2.5", "BTTS", "value"]
    with np.printoptions(precision=2):
        print(t[cols].to_string(index=False, formatters={c: pct for c in ["P1", "PN", "P2", "P+2.5", "BTTS"]}))


def cmd_classement(a):
    m, _ = engine.get_model()
    r = m.ratings()
    if a.ligue:
        r = r[r.ligue == a.ligue]
    print(r.head(a.n).round(2).to_string())


def cmd_backtest(a):
    res = engine.run_backtest(start=a.debut, verbose=True)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=float))


def main(argv=None):
    p = argparse.ArgumentParser(description="Pronostics football (modèle Dixon-Coles + marché)")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("maj").set_defaults(f=lambda a: (engine.get_model(force=True), print("Données à jour.")))
    m = sp.add_parser("match")
    m.add_argument("dom"); m.add_argument("ext")
    m.add_argument("--comp", default="F1", help="F1, E0, SP1, I1, D1, CL…")
    m.add_argument("--neutre", action="store_true")
    m.add_argument("--cotes", nargs=3, type=float, metavar=("C1", "CN", "C2"))
    m.add_argument("--cote-o25", nargs="+", type=float, metavar="C", help="cote +2.5 [et -2.5]")
    m.set_defaults(f=cmd_match)
    n = sp.add_parser("prochains")
    n.add_argument("--ligues", nargs="+", default=MAIN_LEAGUES)
    n.set_defaults(f=cmd_prochains)
    c = sp.add_parser("classement")
    c.add_argument("--ligue"); c.add_argument("-n", type=int, default=30)
    c.set_defaults(f=cmd_classement)
    b = sp.add_parser("backtest")
    b.add_argument("--debut", default=None)
    b.set_defaults(f=cmd_backtest)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    sys.exit(main())
