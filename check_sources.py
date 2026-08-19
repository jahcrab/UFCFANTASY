"""Run this first. It checks whether both sources are reachable from your
machine and whether the parsers understand their current page structure.

    python check_sources.py

Everything it downloads is saved in the cache/ folder. If a check fails,
send me the file it names and I can fix the parser against the real HTML
instead of guessing.
"""

import sys
import traceback

from sources import http, mmadec, ufc

UFC_RESULTS = "https://www.ufc.com/events"
MMADEC_EVENTS = "https://mmadecisions.com/decisions-by-event/2026/"

OK, FAIL, WARN = "  OK  ", " FAIL ", " WARN "


def line(status, msg):
    print(f"[{status}] {msg}")


def check_reachable(name, url):
    try:
        html = http.get(url)
    except Exception as e:
        line(FAIL, f"{name} unreachable: {type(e).__name__}: {e}")
        return None
    if len(html) < 2000:
        line(WARN, f"{name} returned only {len(html)} bytes "
                   f"(bot check?) -> {http.cached_path(url)}")
        return html
    line(OK, f"{name} reachable ({len(html):,} bytes)")
    return html


def check_ufc(html, url):
    if not html:
        return
    try:
        bouts = ufc.parse_results(html)
    except Exception:
        line(FAIL, "UFC parser raised:")
        traceback.print_exc()
        return
    if not bouts:
        line(WARN, f"UFC page reachable but no bouts parsed. This page may be "
                   f"a schedule rather than results. Saved: {http.cached_path(url)}")
        return
    line(OK, f"parsed {len(bouts)} bouts from UFC.com")
    for b in bouts[:5]:
        who = b["winner"] or " / ".join(b.get("fighters", ()))
        rnd = " R%s" % b["end_round"] if b["end_round"] else ""
        print(f"         {who} over {b['loser']} — {b['method']}{rnd}")


def check_mmadec(html, url):
    if not html:
        return
    try:
        decisions = mmadec.event_decisions(url)
    except Exception:
        line(FAIL, "MMA Decisions index parser raised:")
        traceback.print_exc()
        return
    if not decisions:
        line(WARN, f"no decision links found. Saved: {http.cached_path(url)}")
        return
    line(OK, f"found {len(decisions)} decision pages")

    target = decisions[0]
    try:
        d = mmadec.fetch_decision(target)
    except Exception:
        line(FAIL, f"scorecard fetch failed for {target}")
        traceback.print_exc()
        return

    if not d["judges"]:
        line(FAIL, f"no scorecards parsed from {target}\n"
                   f"         saved: {http.cached_path(target)}")
        return

    line(OK, f"parsed {len(d['judges'])} judges for "
             f"{d['fighters'][0]} vs {d['fighters'][1]}")
    for judge, card in d["judges"].items():
        print(f"         {judge}: {card}")
    maj = mmadec.majority_card(d["judges"])
    print(f"         majority card: {maj}")
    if len(d["judges"]) < 3:
        line(WARN, "fewer than 3 judges parsed — the majority rule needs all three")
    if any(r is None for r in maj):
        line(WARN, "some rounds had no majority; those go to review")


def main():
    print("Checking sources. First run downloads a few pages; "
          "later runs read from cache/\n")

    print("--- UFC.com ---")
    html = check_reachable("UFC.com", UFC_RESULTS)
    check_ufc(html, UFC_RESULTS)

    print("\n--- MMA Decisions ---")
    html = check_reachable("MMA Decisions", MMADEC_EVENTS)
    check_mmadec(html, MMADEC_EVENTS)

    print("\nDone. Anything marked FAIL or WARN — send me the saved file "
          "from cache/ named above.")


if __name__ == "__main__":
    sys.exit(main())
