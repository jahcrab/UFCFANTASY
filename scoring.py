"""Fantasy UFC scoring engine.

Pure function over fight facts -> per-fighter points.
No I/O, no scraping: this is the piece that must be provably correct.
"""

CHAMP = "C"


def _rank(v):
    """Normalise a rank cell. Returns ('champ',0) / ('ranked',n) / ('unranked',None)."""
    if v is None or v == "":
        return ("unranked", None)
    if isinstance(v, str):
        if v.strip().upper() == CHAMP:
            return ("champ", 0)
        v = v.strip()
        try:
            return ("ranked", int(v))
        except ValueError:
            return ("unranked", None)
    return ("ranked", int(v))


def _is_finish(method):
    m = (method or "").lower()
    if "decision" in m:
        return False
    return any(k in m for k in ("ko", "tko", "submission"))


def _is_dq(method):
    return "disqualification" in (method or "").lower() or " dq" in (method or "").lower()


def _is_split(method):
    return "split" in (method or "").lower()


def _round_tallies(rounds):
    """rounds: list of majority-card strings like '10 9', '9 10', '10 8'.

    Returns (winner_rounds, loser_rounds, winner_dominant, loser_dominant)
    where 'winner'/'loser' are the fight's winner/loser, matching the
    left/right ordering of the score string.
    """
    w = l = wd = ld = 0
    for cell in rounds:
        if not cell:
            continue
        s = str(cell).strip()
        if s == "10 9":
            w += 1
        elif s == "9 10":
            l += 1
        elif s in ("10 8", "10 7"):
            wd += 1
        elif s in ("8 10", "7 10"):
            ld += 1
    return w, l, wd, ld


def score_fight(f, rules):
    """Score one fight. Returns {fighter_name: {component: points}}."""
    R = rules
    winner, loser = f["winner"], f["loser"]
    finish = _is_finish(f["method"])
    dq = _is_dq(f["method"])
    split = _is_split(f["method"])
    w_kind, w_num = _rank(f.get("w_rank"))
    l_kind, l_num = _rank(f.get("l_rank"))
    wr, lr, wdr, ldr = _round_tallies(f.get("rounds") or [])

    W, L = {}, {}

    W["win"] = R["win"]
    L["loss"] = R["loss"]

    if finish:
        W["finish"] = R["finish"]
        L["finish_loss"] = R["finish_loss"]
        if f.get("rnd") == 1:
            W["quick_finish"] = R["quick_finish"]

    W["rounds"] = wr * R["round_won"]
    L["rounds"] = lr * R["round_won"]
    W["dominant_rounds"] = wdr * R["dominant_round"]
    L["dominant_rounds"] = ldr * R["dominant_round"]

    # Beating a reigning champion
    if l_kind == "champ":
        W["beat_champion"] = R["beat_champion"]
        L["title_loss"] = R["title_loss"]

    # Champion who won (successful defence)
    if w_kind == "champ":
        W["title_defense"] = R["title_defense"]

    # Ranked opponent (champion handled separately above)
    if l_kind == "ranked":
        W["beat_ranked"] = R["beat_ranked"]
        # Lower rank number == higher ranked. Unranked winner never qualifies.
        if w_kind == "ranked" and l_num < w_num:
            W["beat_higher_ranked"] = R["beat_higher_ranked"]

    if f.get("fotn"):
        W["fotn"] = R["fotn"]
        L["fotn"] = R["fotn"]
    if f.get("potn"):
        W["potn"] = R["potn"]

    if split:
        W["split_decision"] = R["split_win"]
        L["split_decision"] = R["split_loss"]

    if dq:
        L["dq"] = R["dq_loss"]

    # Bad scorecard loss: 30-26 / 50-44 or worse on the majority card
    total_rounds = len([c for c in (f.get("rounds") or []) if c])
    if total_rounds:
        loser_pts = lr * 10 + ldr * 10 + (wr + wdr) * 9  # placeholder, refined below
    if f.get("bad_scorecard"):
        L["bad_scorecard"] = R["bad_scorecard"]

    if f.get("comeback"):
        W["comeback"] = R["comeback"]
    if f.get("short_notice"):
        W["short_notice"] = R["short_notice"]

    return {winner: W, loser: L}


DEFAULT_RULES = dict(
    win=10, loss=-5,
    finish=5, finish_loss=-5, quick_finish=5,
    round_won=1, dominant_round=2,
    beat_champion=10, title_defense=5, title_loss=-5,
    beat_ranked=5, beat_higher_ranked=5,
    fotn=3, potn=3,
    comeback=5, short_notice=5,
    split_win=-5, split_loss=5,
    bad_scorecard=-3, dq_loss=-5,
)
