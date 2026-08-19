"""Load the hand-verified 2025 season into the schema and check the
standings view reproduces the spreadsheet's team totals.

This tests the ownership model, not just the scorer: two mid-season
transactions mean points have to route by date, not by current roster.
"""

import json
import sqlite3
from datetime import datetime

from names import FighterIndex, normalise
from scoring import score_fight, DEFAULT_RULES

SEASON_START = "2025-03-01"

# Facts no source publishes as data; in production these live in manual_flags.
COMEBACK = {"Chidi Njokuani", "Lone'er Kavanagh", "Shauna Bannon", "Dan Ige",
            "Nora Cornolle", "Ode' Osbourne", "Da'Mon Blackshear"}
BAD_CARD = {"Andrey Pulyaev", "Joanderson Brito", "Vanessa Demopoulos"}
TITLE_FIGHTS = {("Alexander Volkanovski", "Diego Lopes")}

TRANSACTIONS = [
    ("Bill", "2025-03-28", "CJ Vergara", "Brandon Royval"),
    ("Jon",  "2025-04-07", "Jalin Turner", "Nazim Sadykov"),
]

EVENT_DATES = {
    "UFC 313": "2025-03-08",
    "UFC Fight Night: Vettori vs. Dolidze 2": "2025-03-15",
    "UFC Fight Night: Edwards vs. Brady": "2025-03-22",
    "UFC Fight Night: Moreno vs Erceg": "2025-03-29",
    "UFC on ESPN: Emmett vs. Murphy": "2025-04-05",
    "UFC 314": "2025-04-12",
}


def build(db):
    db.executescript(open("schema.sql").read())
    league = json.load(open("league.json"))
    events = json.load(open("verified.json"))

    idx = FighterIndex()
    next_id = [1]

    def fighter(name):
        kind, fid, score = idx.resolve(name)
        if kind in ("exact", "alias", "fuzzy"):
            return fid
        if kind == "review":
            db.execute(
                "INSERT INTO name_review_queue"
                " (raw_name, source, best_guess_id, best_score, seen_at)"
                " VALUES (?,?,?,?,?)",
                (name, "load", fid, score, datetime.now().isoformat()))
        fid = next_id[0]
        next_id[0] += 1
        idx.add(fid, name)
        db.execute(
            "INSERT INTO fighters (id, display_name, norm_name) VALUES (?,?,?)",
            (fid, name, normalise(name)))
        return fid

    # teams + opening rosters
    team_ids = {}
    for i, t in enumerate(league["teams"], start=1):
        team_ids[t] = i
        db.execute("INSERT INTO teams (id, name, owner) VALUES (?,?,?)", (i, t, t))
    for team, entries in league["roster"].items():
        seen = {}
        for div, nm in entries:
            slot = seen.get(div, 0) + 1
            seen[div] = slot
            db.execute(
                "INSERT INTO roster_history"
                " (team_id, fighter_id, division, slot, acquired_at, acquired_via)"
                " VALUES (?,?,?,?,?,?)",
                (team_ids[team], fighter(nm), div, slot, SEASON_START, "draft"))

    # The Teams sheet is an END-OF-SEASON snapshot: dropped fighters are
    # already absent from it. So history is reconstructed by rewinding —
    # the added fighter's tenure starts at the transaction date, and the
    # dropped fighter held that slot from season start until then.
    for team, date, dropped, added in TRANSACTIONS:
        add_id = fighter(added)
        row = db.execute(
            "SELECT id, division, slot FROM roster_history"
            " WHERE team_id=? AND fighter_id=? AND released_at IS NULL",
            (team_ids[team], add_id)).fetchone()
        if row is None:
            raise SystemExit(f"{added} not on {team}'s final roster")
        db.execute("UPDATE roster_history SET acquired_at=?, acquired_via=?"
                   " WHERE id=?", (date, "waiver", row[0]))
        db.execute(
            "INSERT INTO roster_history"
            " (team_id, fighter_id, division, slot, acquired_at, released_at,"
            " acquired_via) VALUES (?,?,?,?,?,?,?)",
            (team_ids[team], fighter(dropped), row[1], row[2],
             SEASON_START, date, "draft"))

    # events, fights, scores
    for ei, ev in enumerate(events, start=1):
        if not ev["scores"]:
            continue
        db.execute("INSERT INTO events (id, name, event_date) VALUES (?,?,?)",
                   (ei, ev["event"], EVENT_DATES[ev["event"]]))
        for fi, f in enumerate(ev["fights"]):
            f = dict(f)
            if f["winner"] in COMEBACK:
                f["comeback"] = True
            if f["loser"] in BAD_CARD:
                f["bad_scorecard"] = True
            title = (f["winner"], f["loser"]) in TITLE_FIGHTS
            w, l = fighter(f["winner"]), fighter(f["loser"])
            fight_id = ei * 100 + fi
            db.execute(
                "INSERT INTO fights (id, event_id, winner_id, loser_id, outcome,"
                " method, end_round, is_title_fight) VALUES (?,?,?,?,?,?,?,?)",
                (fight_id, ei, w, l, "win", f["method"], f["rnd"], int(title)))

            res = score_fight(f, DEFAULT_RULES)
            if title:
                res[f["winner"]]["beat_champion"] = DEFAULT_RULES["beat_champion"]
                res[f["loser"]]["title_loss"] = DEFAULT_RULES["title_loss"]
            for nm, comps in res.items():
                for comp, pts in comps.items():
                    if pts:
                        db.execute(
                            "INSERT INTO fight_scores (fight_id, fighter_id,"
                            " component, points, rules_version, computed_at)"
                            " VALUES (?,?,?,?,?,?)",
                            (fight_id, fighter(nm), comp, pts, "2025.1",
                             datetime.now().isoformat()))
    db.commit()
    return team_ids


if __name__ == "__main__":
    db = sqlite3.connect(":memory:")
    build(db)
    expected = json.load(open("league.json"))["totals"]

    print(f"{'team':10s} {'sheet':>7} {'engine':>7} {'delta':>7}")
    bad = 0
    for name, sheet in expected.items():
        got = db.execute(
            "SELECT points FROM standings WHERE team_name=?", (name,)).fetchone()
        got = got[0] if got else 0
        flag = "" if got == sheet else "  <-- differs"
        if got != sheet:
            bad += 1
        print(f"{name:10s} {sheet:>7} {got:>7} {got - sheet:>+7}{flag}")
    print(f"\n{len(expected) - bad}/{len(expected)} teams reproduce exactly")

    q = db.execute("SELECT raw_name, best_score FROM name_review_queue").fetchall()
    if q:
        print("\nname review queue:")
        for nm, sc in q:
            print(f"  {nm}  ({sc:.3f})")
