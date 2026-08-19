"""Fighter identity resolution.

Three sources spell fighters three ways. UFC.com writes "Ian Machado Garry",
MMA Decisions writes "Ian Garry", an odds feed might write "Ian Machado-Garry".
Accents come and go. Typos happen on the roster side.

This module never guesses silently. Every lookup returns one of:
  ("exact",  fighter_id, 1.0)
  ("alias",  fighter_id, 1.0)     - previously confirmed by a human
  ("fuzzy",  fighter_id, score)   - candidate, needs confirmation
  ("none",   None, 0.0)           - goes to the review queue
"""

import re
import unicodedata
from difflib import SequenceMatcher

# Particles that appear inconsistently across sources.
_DROPPABLE = {"jr", "sr", "ii", "iii", "iv", "the"}


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def normalise(name: str) -> str:
    """Aggressive normal form used only for comparison, never for display."""
    s = strip_accents(name or "").lower()
    s = s.replace("'", "").replace("`", "").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    parts = [p for p in s.split() if p not in _DROPPABLE]
    return " ".join(parts)


def token_set(name: str) -> frozenset:
    return frozenset(normalise(name).split())


def _part_sim(a, b):
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _directional(ta, tb):
    """Compare two token lists as (given name ... surname).

    Middle names are ignored: sources drop them inconsistently
    ("Ian Machado Garry" vs "Ian Garry"). Both ends must agree, so a
    shared surname cannot rescue a mismatched given name.
    """
    first = _part_sim(ta[0], tb[0])
    last = _part_sim(ta[-1], tb[-1])
    score = min(first, last)
    # A middle name present on both sides that agrees is mild confirmation.
    if len(ta) > 2 and len(tb) > 2 and set(ta[1:-1]) & set(tb[1:-1]):
        score = min(1.0, score + 0.02)
    return score


def similarity(a, b):
    """0..1 confidence that two source strings name the same fighter."""
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = na.split(), nb.split()
    if len(ta) == 1 or len(tb) == 1:
        return _part_sim(na, nb) * 0.8  # single token: never confident
    forward = _directional(ta, tb)
    # Some sources invert Asian name order ("Song Yadong" / "Yadong Song").
    flipped = _directional(list(reversed(ta)), tb)
    return max(forward, flipped)


class FighterIndex:
    """Resolves an incoming source name to a canonical fighter id."""

    AUTO_ACCEPT = 0.88   # above this, accept automatically
    REVIEW_FLOOR = 0.70  # between floor and accept, ask a human

    def __init__(self):
        self._canonical = {}   # fighter_id -> display name
        self._by_norm = {}     # normalised form -> fighter_id
        self._aliases = {}     # normalised alias -> fighter_id

    def add(self, fighter_id, display_name):
        self._canonical[fighter_id] = display_name
        self._by_norm[normalise(display_name)] = fighter_id
        return fighter_id

    def add_alias(self, fighter_id, alias):
        self._aliases[normalise(alias)] = fighter_id

    def resolve(self, name):
        n = normalise(name)
        if n in self._by_norm:
            return ("exact", self._by_norm[n], 1.0)
        if n in self._aliases:
            return ("alias", self._aliases[n], 1.0)

        best_id, best_score = None, 0.0
        for fid, disp in self._canonical.items():
            s = similarity(name, disp)
            if s > best_score:
                best_id, best_score = fid, s

        if best_score >= self.AUTO_ACCEPT:
            return ("fuzzy", best_id, best_score)
        if best_score >= self.REVIEW_FLOOR:
            return ("review", best_id, best_score)
        return ("none", None, best_score)
