-- Fantasy UFC league database.
--
-- Two principles drive the shape:
--   1. Raw source facts are stored separately from computed points, so a
--      rule change or a corrected result is a recompute, never a re-entry.
--   2. Roster ownership is time-indexed. Points attach to a fight; team
--      totals are a join through whoever owned that fighter on that date.

PRAGMA foreign_keys = ON;

-- ---------- identity ----------

CREATE TABLE fighters (
    id            INTEGER PRIMARY KEY,
    display_name  TEXT NOT NULL,
    norm_name     TEXT NOT NULL UNIQUE,
    division      TEXT,              -- current division, informational only
    status        TEXT NOT NULL DEFAULT 'active',
                                     -- active | cut | retired | suspended
    ufc_url       TEXT,
    mmadec_id     TEXT
);

-- Confirmed spelling variants. Populated by a human clearing the review
-- queue; the matcher never writes here on its own.
CREATE TABLE fighter_aliases (
    alias_norm    TEXT PRIMARY KEY,
    fighter_id    INTEGER NOT NULL REFERENCES fighters(id),
    source        TEXT,
    confirmed_at  TEXT NOT NULL
);

-- Names that arrived from a source and could not be resolved.
-- Nothing is ever silently dropped or scored as zero.
CREATE TABLE name_review_queue (
    id            INTEGER PRIMARY KEY,
    raw_name      TEXT NOT NULL,
    source        TEXT NOT NULL,
    context       TEXT,              -- event/fight it appeared in
    best_guess_id INTEGER REFERENCES fighters(id),
    best_score    REAL,
    seen_at       TEXT NOT NULL,
    resolved_at   TEXT
);

-- ---------- league ----------

CREATE TABLE teams (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    owner    TEXT NOT NULL
);

-- The central design decision: ownership is a history, not a state.
-- "Who owned Ankalaev on March 8" is a query, not a guess.
CREATE TABLE roster_history (
    id           INTEGER PRIMARY KEY,
    team_id      INTEGER NOT NULL REFERENCES teams(id),
    fighter_id   INTEGER NOT NULL REFERENCES fighters(id),
    division     TEXT NOT NULL,
    slot         INTEGER NOT NULL CHECK (slot IN (1, 2)),
    acquired_at  TEXT NOT NULL,
    released_at  TEXT,               -- NULL = currently held
    acquired_via TEXT                -- draft | waiver | commissioner
);
CREATE INDEX idx_roster_fighter ON roster_history(fighter_id, acquired_at, released_at);

CREATE TABLE transactions (
    id             INTEGER PRIMARY KEY,
    team_id        INTEGER NOT NULL REFERENCES teams(id),
    kind           TEXT NOT NULL,    -- add | drop | claim
    fighter_id     INTEGER NOT NULL REFERENCES fighters(id),
    submitted_at   TEXT NOT NULL,
    processed_at   TEXT,
    -- Booking status captured at SUBMIT time, so a bout announced between
    -- submission and processing cannot void an otherwise valid claim.
    was_booked     INTEGER NOT NULL DEFAULT 0,
    outcome        TEXT,             -- granted | denied | superseded
    denied_reason  TEXT
);

CREATE TABLE waiver_priority (
    team_id   INTEGER PRIMARY KEY REFERENCES teams(id),
    position  INTEGER NOT NULL
);

-- ---------- source facts ----------

CREATE TABLE events (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    ufc_url     TEXT,
    ingested_at TEXT
);

CREATE TABLE fights (
    id             INTEGER PRIMARY KEY,
    event_id       INTEGER NOT NULL REFERENCES events(id),
    winner_id      INTEGER REFERENCES fighters(id),   -- NULL for draw / NC
    loser_id       INTEGER REFERENCES fighters(id),
    outcome        TEXT NOT NULL,    -- win | draw | no_contest
    method         TEXT,
    method_detail  TEXT,
    end_round      INTEGER,
    end_time       TEXT,
    weight_class   TEXT,
    -- Explicit, never inferred from whether a rank cell says "C".
    -- Vacant-title bouts have no reigning champion in them.
    is_title_fight INTEGER NOT NULL DEFAULT 0,
    is_interim     INTEGER NOT NULL DEFAULT 0,
    scheduled_rounds INTEGER,
    UNIQUE (event_id, winner_id, loser_id)
);

-- One row per judge per round. Majority is computed, not typed.
CREATE TABLE scorecards (
    fight_id    INTEGER NOT NULL REFERENCES fights(id),
    judge       TEXT NOT NULL,
    round_no    INTEGER NOT NULL,
    winner_pts  INTEGER NOT NULL,
    loser_pts   INTEGER NOT NULL,
    PRIMARY KEY (fight_id, judge, round_no)
);

CREATE TABLE bonuses (
    fight_id   INTEGER NOT NULL REFERENCES fights(id),
    fighter_id INTEGER REFERENCES fighters(id),
    kind       TEXT NOT NULL,        -- FOTN | POTN
    PRIMARY KEY (fight_id, fighter_id, kind)
);

-- Captured on a schedule. These cannot be retrieved after the fact.
CREATE TABLE odds_snapshots (
    id          INTEGER PRIMARY KEY,
    fighter_id  INTEGER NOT NULL REFERENCES fighters(id),
    opponent_id INTEGER REFERENCES fighters(id),
    event_date  TEXT,
    american    INTEGER NOT NULL,
    bookmaker   TEXT,
    captured_at TEXT NOT NULL
);

CREATE TABLE rankings_snapshots (
    fighter_id  INTEGER NOT NULL REFERENCES fighters(id),
    division    TEXT NOT NULL,
    rank        INTEGER,             -- 0 = champion, NULL = unranked
    snapshot_at TEXT NOT NULL,
    PRIMARY KEY (fighter_id, division, snapshot_at)
);

-- Bout announcements, diffed daily. Gives short-notice calculation and
-- the booked/unbooked flag the waiver rules depend on.
CREATE TABLE bookings (
    id            INTEGER PRIMARY KEY,
    fighter_id    INTEGER NOT NULL REFERENCES fighters(id),
    opponent_id   INTEGER REFERENCES fighters(id),
    event_date    TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    withdrawn_at  TEXT
);

-- ---------- human input ----------

-- The short list of things no source publishes as data.
CREATE TABLE manual_flags (
    id          INTEGER PRIMARY KEY,
    fight_id    INTEGER REFERENCES fights(id),
    fighter_id  INTEGER REFERENCES fighters(id),
    kind        TEXT NOT NULL,
        -- comeback | short_notice | missed_weight | withdrawal
        -- | failed_test | overturned
    value       INTEGER NOT NULL DEFAULT 1,
    note        TEXT,
    entered_by  TEXT,
    entered_at  TEXT NOT NULL
);

-- ---------- computed ----------

CREATE TABLE fight_scores (
    fight_id     INTEGER NOT NULL REFERENCES fights(id),
    fighter_id   INTEGER NOT NULL REFERENCES fighters(id),
    component    TEXT NOT NULL,
    points       INTEGER NOT NULL,
    rules_version TEXT NOT NULL,
    computed_at  TEXT NOT NULL,
    PRIMARY KEY (fight_id, fighter_id, component, rules_version)
);

-- Standings: points routed to whoever held the fighter on fight day.
CREATE VIEW standings AS
SELECT t.id AS team_id,
       t.name AS team_name,
       COALESCE(SUM(fs.points), 0) AS points
FROM teams t
LEFT JOIN roster_history rh ON rh.team_id = t.id
LEFT JOIN fights f          ON f.winner_id = rh.fighter_id OR f.loser_id = rh.fighter_id
LEFT JOIN events e          ON e.id = f.event_id
                           AND e.event_date >= rh.acquired_at
                           AND (rh.released_at IS NULL OR e.event_date < rh.released_at)
LEFT JOIN fight_scores fs   ON fs.fight_id = f.id AND fs.fighter_id = rh.fighter_id
WHERE e.id IS NOT NULL
GROUP BY t.id, t.name;
