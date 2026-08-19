"""UFC.com: results, methods, and bonus awards.

Results are read from prose rather than markup. The official scorecard
and results pages state every bout in a fixed sentence form, and prose
survives site redesigns far better than div structure does.
"""

import re

from bs4 import BeautifulSoup

from .http import get

BASE = "https://www.ufc.com"

# Names: every token must start uppercase. This is what stops a match
# running past a sentence boundary into "for their five-round war".
NAME = r"[A-Z][\w'\-\.\u00C0-\u024F]*(?:\s+[A-Z][\w'\-\.\u00C0-\u024F]*){0,3}"
BEAT = r"(?:defeated|def\.|defeats)"

FINISH = re.compile(
    rf"(?P<winner>{NAME})\s+{BEAT}\s+(?P<loser>{NAME})\s+by\s+"
    rf"(?P<method>.+?)\s+at\s+(?P<time>\d{{1,2}}:\d{{2}})\s+of\s+[Rr]ound\s+(?P<round>\d)",
    re.I,
)

DECISION = re.compile(
    rf"(?P<winner>{NAME})\s+{BEAT}\s+(?P<loser>{NAME})\s+by\s+"
    rf"(?P<method>(?:Unanimous|Split|Majority)\s+Decision|Technical\s+Decision"
    rf"|Disqualification|DQ)",
)

DRAW = re.compile(
    rf"(?P<a>{NAME})\s+and\s+(?P<b>{NAME})\s+(?:fought|battled)\s+to\s+a\s+"
    rf"(?P<kind>majority draw|split draw|unanimous draw|draw|no contest)",
    re.I,
)

TITLE_HINT = re.compile(r"\b(title|championship|belt|interim)\b", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip(" .,")


def _trim_method(m):
    """Cut trailing prose: 'Unanimous Decision in the lightweight title bout'."""
    m = re.split(r"\s+(?:in|to|at|after|for|during)\s+", m, maxsplit=1)[0]
    return _clean(m)


def _sentences(html):
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    for line in text.split("\n"):
        for sent in SENTENCE.split(line):
            sent = sent.strip()
            if sent:
                yield sent


def parse_results(html):
    """Extract every bout stated on the page. One sentence, one bout."""
    seen, out = set(), []
    for sent in _sentences(html):
        title = bool(TITLE_HINT.search(sent))
        bout = None

        m = FINISH.search(sent)
        if m:
            d = m.groupdict()
            bout = dict(winner=_clean(d["winner"]), loser=_clean(d["loser"]),
                        outcome="win", method=_trim_method(d["method"]),
                        end_round=int(d["round"]), end_time=d["time"])
        if bout is None:
            m = DECISION.search(sent)
            if m:
                d = m.groupdict()
                bout = dict(winner=_clean(d["winner"]), loser=_clean(d["loser"]),
                            outcome="win", method=_trim_method(d["method"]),
                            end_round=None, end_time=None)
        if bout is None:
            m = DRAW.search(sent)
            if m:
                d = m.groupdict()
                kind = d["kind"].lower()
                bout = dict(winner=None, loser=None,
                            fighters=(_clean(d["a"]), _clean(d["b"])),
                            outcome="no_contest" if "contest" in kind else "draw",
                            method=kind, end_round=None, end_time=None)
        if bout is None:
            continue

        key = (bout["winner"], bout["loser"]) if bout["winner"] else bout["fighters"]
        if key in seen:
            continue
        seen.add(key)
        bout["title_hint"] = title
        out.append(bout)
    return out


def parse_bonuses(html):
    """{'FOTN': [names], 'POTN': [names]} from a bonus article."""
    out = {"FOTN": [], "POTN": []}
    for sent in _sentences(html):
        if re.search(r"Fight of the Night", sent, re.I):
            m = re.search(rf"({NAME})\s+(?:and|vs\.?)\s+({NAME})", sent)
            if m:
                out["FOTN"] += [_clean(m.group(1)), _clean(m.group(2))]
        if re.search(r"Performance of the Night", sent, re.I):
            for m in re.finditer(rf"({NAME})", sent):
                n = _clean(m.group(1))
                if n and not re.match(r"^(Performance|Fight|Night|The|Round)\b", n):
                    out["POTN"].append(n)
    for k in out:
        out[k] = [n for n in dict.fromkeys(out[k]) if " " in n]
    return out


def event_urls_from_index(html):
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if re.search(r"/event/ufc-", h) or re.search(r"/news/ufc-.*results", h):
            full = h if h.startswith("http") else BASE + h
            if full not in urls:
                urls.append(full)
    return urls


def fetch_results(url):
    return parse_results(get(url))
