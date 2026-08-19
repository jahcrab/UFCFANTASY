"""MMA Decisions: per-judge, round-by-round scorecards.

Parsing is structural, not class-name based. A scorecard is recognised as
a table containing rows whose cells are two integers in the 6..10 range,
which is what a round score looks like and what almost nothing else does.
Judge names are taken from the nearest preceding link to /judge/.
"""

import re
from collections import defaultdict

from bs4 import BeautifulSoup

from .http import get

BASE = "https://mmadecisions.com"
ROUND_SCORE = re.compile(r"^(10|9|8|7|6)$")


def _int_cells(row):
    vals = []
    for td in row.find_all("td"):
        t = td.get_text(strip=True)
        if ROUND_SCORE.match(t):
            vals.append(int(t))
    return vals


def parse_decision(html):
    """Return {'judges': {judge: [(a, b), ...]}, 'fighters': (a, b)}.

    Scores are ordered as the page orders the two fighters; the caller
    maps them onto winner/loser using the recorded result.
    """
    soup = BeautifulSoup(html, "html.parser")
    judges = defaultdict(list)

    for table in soup.find_all("table"):
        rows = [r for r in table.find_all("tr") if len(_int_cells(r)) == 2]
        if len(rows) < 3:
            continue  # a scorecard has at least three rounds

        judge = None
        for prev in table.find_all_previous(["a", "td", "th"], limit=40):
            href = prev.get("href", "") if prev.name == "a" else ""
            if "/judge/" in href:
                judge = prev.get_text(strip=True)
                break
        link = table.find("a", href=re.compile(r"/judge/"))
        if link:
            judge = link.get_text(strip=True)
        if not judge:
            judge = f"judge_{len(judges) + 1}"

        scores = [tuple(_int_cells(r)) for r in rows]
        # Drop a trailing totals row if it is the sum of the rounds above.
        if len(scores) > 1:
            body, last = scores[:-1], scores[-1]
            if last[0] == sum(s[0] for s in body) and last[1] == sum(s[1] for s in body):
                scores = body
        judges[judge] = scores

    fighters = _fighter_names(soup)
    return {"judges": dict(judges), "fighters": fighters}


def _fighter_names(soup):
    names = []
    for a in soup.find_all("a", href=re.compile(r"/fighter/")):
        t = a.get_text(strip=True)
        if t and t not in names:
            names.append(t)
        if len(names) == 2:
            break
    title = soup.find("title")
    if len(names) < 2 and title:
        m = re.search(r"(.+?)\s+vs\.?\s+(.+?)(?:\s*[-|]|$)", title.get_text())
        if m:
            names = [m.group(1).strip(), m.group(2).strip()]
    return tuple(names[:2]) if len(names) >= 2 else (None, None)


def majority_card(judges):
    """Collapse three judges into the modal per-round score.

    This is the rule you already used by hand: if two judges say 10-9 and
    one says 9-10, the round is 10-9. Ties (three-way disagreement) return
    None for that round and go to review.
    """
    if not judges:
        return []
    n = max(len(v) for v in judges.values())
    out = []
    for i in range(n):
        votes = defaultdict(int)
        for card in judges.values():
            if i < len(card):
                votes[card[i]] += 1
        if not votes:
            out.append(None)
            continue
        top = max(votes.values())
        winners = [k for k, v in votes.items() if v == top]
        out.append(winners[0] if len(winners) == 1 else None)
    return out


def event_decisions(event_url):
    """All decision-page URLs linked from an event page."""
    soup = BeautifulSoup(get(event_url), "html.parser")
    urls = []
    for a in soup.find_all("a", href=re.compile(r"/decision/\d+")):
        href = a["href"]
        full = href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}"
        if full not in urls:
            urls.append(full)
    return urls


def fetch_decision(url):
    return parse_decision(get(url))
