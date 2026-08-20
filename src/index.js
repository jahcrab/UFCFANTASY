/**
 * Fantasy UFC — API Worker
 *
 * Identity comes from Cloudflare Access, which sets
 * Cf-Access-Authenticated-User-Email on every request that reaches us.
 * There are no passwords in this system and no session handling.
 *
 * Writes REQUIRE that header. If Access is not configured, the app is
 * readable but nothing can be changed — a safe failure rather than an
 * open door.
 */

import { teamOnClock, totalPicks, openSlots, validatePick,
         autopickChoice, deadlineFor } from "./draft.js";

const json = (data, status = 200) =>
  new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

const bad = (msg, status = 400) => json({ error: msg }, status);

/** Same normal form the Python matcher uses: accents and punctuation
 *  stripped, so "Maurício Ruffy" and "Mauricio Ruffy" collide on purpose. */
function normName(name) {
  return (name || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/['\u2019`]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function identity(request) {
  const email = request.headers.get("Cf-Access-Authenticated-User-Email");
  return email ? email.toLowerCase().trim() : null;
}

/** Look up (or first-run create) the manager row for this email. */
async function whoami(env, email) {
  if (!email) return null;
  const league = await env.DB.prepare("SELECT * FROM leagues LIMIT 1").first();
  if (!league) return null;

  let mgr = await env.DB.prepare(
    "SELECT * FROM managers WHERE league_id = ? AND email = ?"
  ).bind(league.id, email).first();

  if (!mgr) {
    // First authenticated visitor bootstraps as commissioner. Everyone
    // after that must be added by the commissioner, so this is only ever
    // a door for exactly one person.
    const { count } = await env.DB.prepare(
      "SELECT COUNT(*) AS count FROM managers WHERE league_id = ?"
    ).bind(league.id).first();
    if (count > 0) return { league, manager: null, email };

    await env.DB.prepare(
      `INSERT INTO managers (league_id, email, display_name, is_commissioner)
       VALUES (?, ?, ?, 1)`
    ).bind(league.id, email, email.split("@")[0]).run();

    mgr = await env.DB.prepare(
      "SELECT * FROM managers WHERE league_id = ? AND email = ?"
    ).bind(league.id, email).first();
  }
  return { league, manager: mgr, email };
}

async function getState(env, me) {
  const league = me?.league
    ?? await env.DB.prepare("SELECT * FROM leagues LIMIT 1").first();
  if (!league) return { league: null };

  const [teams, managers, draft, fighterCount] = await Promise.all([
    env.DB.prepare(
      `SELECT t.id, t.name, t.manager_id, m.display_name AS manager_name
         FROM teams t LEFT JOIN managers m ON m.id = t.manager_id
        WHERE t.league_id = ? ORDER BY t.id`
    ).bind(league.id).all(),
    env.DB.prepare(
      `SELECT id, email, display_name, is_commissioner
         FROM managers WHERE league_id = ? ORDER BY id`
    ).bind(league.id).all(),
    env.DB.prepare(
      `SELECT * FROM drafts WHERE league_id = ?
        ORDER BY id DESC LIMIT 1`
    ).bind(league.id).first(),
    env.DB.prepare("SELECT COUNT(*) AS count FROM fighters").first(),
  ]);

  const divisions = JSON.parse(league.divisions);
  return {
    league: {
      id: league.id,
      name: league.name,
      season_year: league.season_year,
      slots_per_div: league.slots_per_div,
      divisions,
      roster_size: divisions.length * league.slots_per_div,
    },
    teams: teams.results,
    managers: managers.results,
    draft: draft ?? null,
    fighter_count: fighterCount ? fighterCount.count : 0,
    me: me?.manager
      ? {
          id: me.manager.id,
          email: me.email,
          display_name: me.manager.display_name,
          is_commissioner: !!me.manager.is_commissioner,
        }
      : me?.email
        ? { email: me.email, pending: true }
        : null,
  };
}

async function currentDraft(env, leagueId) {
  if (!leagueId) return null;
  return env.DB.prepare(
    "SELECT * FROM drafts WHERE league_id=? ORDER BY id DESC LIMIT 1"
  ).bind(leagueId).first();
}

async function heldBy(env, leagueId, teamId) {
  const { results } = await env.DB.prepare(
    `SELECT f.id, f.display_name, f.division
       FROM roster_history rh JOIN fighters f ON f.id = rh.fighter_id
      WHERE rh.league_id=? AND rh.team_id=? AND rh.released_at IS NULL`
  ).bind(leagueId, teamId).all();
  return results;
}

async function draftState(env, me) {
  const base = await getState(env, me);
  const d = await currentDraft(env, base.league?.id);
  if (!d) return { ...base, draft: null };

  const order = JSON.parse(d.team_order || "[]");
  const total = totalPicks(order, d.rounds);
  const done = d.current_pick > total;
  const clock = done ? null : teamOnClock(order, d.current_pick);

  const { results: picks } = await env.DB.prepare(
    `SELECT p.overall, p.round, p.team_id, p.autopicked,
            t.name AS team_name, f.display_name AS fighter, f.division
       FROM draft_picks p
       JOIN teams t ON t.id = p.team_id
       LEFT JOIN fighters f ON f.id = p.fighter_id
      WHERE p.draft_id=? ORDER BY p.overall DESC LIMIT 20`
  ).bind(d.id).all();

  let mine = null;
  if (me?.manager) {
    const team = base.teams.find((t) => t.manager_id === me.manager.id);
    if (team) {
      const held = await heldBy(env, base.league.id, team.id);
      const picksMade = held.length;
      mine = {
        team_id: team.id,
        team_name: team.name,
        on_clock: clock?.teamId === team.id,
        roster: held,
        open_slots: openSlots(base.league.divisions,
                              base.league.slots_per_div, held),
        picks_remaining: d.rounds - picksMade,
      };
    }
  }

  return {
    ...base,
    draft: {
      id: d.id, status: d.status, rounds: d.rounds,
      pick_seconds: d.pick_seconds, scheduled_at: d.scheduled_at,
      current_pick: d.current_pick, total_picks: total,
      deadline_at: d.deadline_at,
      on_clock_team: clock?.teamId ?? null,
      current_round: clock?.round ?? null,
      complete: done,
      team_order: order,
      recent_picks: picks,
    },
    me: mine ? { ...base.me, ...mine } : base.me,
  };
}

async function makePick(env, me, fighterId, isAuto) {
  const league = me?.league;
  if (!league) return bad("No league", 400);
  const d = await currentDraft(env, league.id);
  if (!d || d.status !== "live") return bad("The draft is not live");

  const order = JSON.parse(d.team_order || "[]");
  const total = totalPicks(order, d.rounds);
  if (d.current_pick > total) return bad("The draft is already complete");

  const clock = teamOnClock(order, d.current_pick);
  const teamId = clock.teamId;

  if (!isAuto) {
    const { results: mine } = await env.DB.prepare(
      "SELECT id FROM teams WHERE id=? AND manager_id=?"
    ).bind(teamId, me.manager ? me.manager.id : -1).all();
    if (!mine.length && !me.manager?.is_commissioner) {
      return bad("It is not your pick", 403);
    }
  }

  const divisions = JSON.parse(league.divisions);
  const held = await heldBy(env, league.id, teamId);
  const open = openSlots(divisions, league.slots_per_div, held);
  const picksRemaining = d.rounds - held.length;

  let fighter = null;
  if (fighterId) {
    fighter = await env.DB.prepare(
      `SELECT f.id, f.display_name, f.division, rh.team_id AS taken_by
         FROM fighters f
         LEFT JOIN roster_history rh
           ON rh.fighter_id=f.id AND rh.league_id=? AND rh.released_at IS NULL
        WHERE f.id=?`
    ).bind(league.id, fighterId).first();
    const why = validatePick({ fighter, held, divisions,
                               slotsPerDivision: league.slots_per_div,
                               picksRemainingForTeam: picksRemaining });
    if (why) return bad(why);
  } else {
    const { results: avail } = await env.DB.prepare(
      `SELECT f.id, f.division, f.proj_vorp FROM fighters f
         LEFT JOIN roster_history rh
           ON rh.fighter_id=f.id AND rh.league_id=? AND rh.released_at IS NULL
        WHERE rh.team_id IS NULL`
    ).bind(league.id).all();
    const { results: queue } = await env.DB.prepare(
      "SELECT fighter_id FROM draft_queue WHERE team_id=? ORDER BY position"
    ).bind(teamId).all();
    fighter = autopickChoice(avail, open, queue.map((q) => q.fighter_id));
    if (!fighter) return bad("No eligible fighter remains for that team", 500);
    fighter = await env.DB.prepare(
      "SELECT id, display_name, division FROM fighters WHERE id=?"
    ).bind(fighter.id).first();
  }

  const slotUsed = (league.slots_per_div
    - (open[fighter.division] ?? 0)) + 1;
  const now = new Date();
  const nextPick = d.current_pick + 1;
  const finished = nextPick > total;

  // Guarded by UNIQUE(draft_id, overall) and by current_pick in the WHERE
  // clause: two clients racing the same pick cannot both succeed.
  const res = await env.DB.prepare(
    `UPDATE drafts SET current_pick=?, deadline_at=?, status=?,
            completed_at=? WHERE id=? AND current_pick=?`
  ).bind(nextPick,
         finished ? null : deadlineFor(d.pick_seconds, now),
         finished ? "complete" : "live",
         finished ? now.toISOString() : null,
         d.id, d.current_pick).run();

  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO draft_picks (draft_id, overall, round, team_id,
                                fighter_id, division, picked_at, autopicked)
       VALUES (?,?,?,?,?,?,?,?)`
    ).bind(d.id, d.current_pick, clock.round, teamId, fighter.id,
           fighter.division, now.toISOString(), isAuto ? 1 : 0),
    env.DB.prepare(
      `INSERT INTO roster_history (league_id, team_id, fighter_id, division,
                                   slot, acquired_at, acquired_via)
       VALUES (?,?,?,?,?,?,'draft')`
    ).bind(league.id, teamId, fighter.id, fighter.division,
           slotUsed, now.toISOString()),
  ]);

  return json({
    picked: fighter.display_name, division: fighter.division,
    team_id: teamId, overall: d.current_pick, autopicked: isAuto,
    complete: finished,
  });
}

const routes = {
  "POST /api/admin/import-fighters": async (req, env, me) => {
    if (!me?.manager?.is_commissioner) return bad("Commissioner only", 403);

    // The board ships as a static asset, so importing needs no upload
    // and no giant SQL paste — the Worker reads its own bundled file.
    const res = await env.ASSETS.fetch(new URL("/board.json", req.url));
    if (!res.ok) return bad("board.json not found in the deployed site", 500);
    const rows = await res.json();
    if (!Array.isArray(rows) || !rows.length) return bad("board.json is empty");

    const now = new Date().toISOString();
    const stmts = rows
      .filter((r) => r && r.fighter && r.division)
      .map((r) =>
        env.DB.prepare(
          `INSERT INTO fighters
             (display_name, norm_name, division, rank, age, ufc_record, form,
              proj_points, proj_vorp, proj_fights, is_booked, imported_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(norm_name) DO UPDATE SET
             display_name = excluded.display_name,
             division     = excluded.division,
             rank         = excluded.rank,
             age          = excluded.age,
             ufc_record   = excluded.ufc_record,
             form         = excluded.form,
             proj_points  = excluded.proj_points,
             proj_vorp    = excluded.proj_vorp,
             proj_fights  = excluded.proj_fights,
             is_booked    = excluded.is_booked,
             imported_at  = excluded.imported_at`
        ).bind(
          r.fighter, normName(r.fighter), r.division,
          r.rank === null || r.rank === undefined ? null : String(r.rank),
          r.age ?? null, r.ufc_record ?? null, r.form ?? null,
          r.projected ?? null, r.vorp ?? null, r.proj_fights ?? null,
          r.booked ? 1 : 0, now
        )
      );

    await env.DB.batch(stmts);
    const { count } = await env.DB.prepare(
      "SELECT COUNT(*) AS count FROM fighters"
    ).first();
    return json({ imported: stmts.length, total_in_db: count });
  },

  "GET /api/fighters": async (req, env, me) => {
    const url = new URL(req.url);
    const division = url.searchParams.get("division");
    const q = (url.searchParams.get("q") || "").toLowerCase();
    const availableOnly = url.searchParams.get("available") === "1";
    const limit = Math.min(500, Number(url.searchParams.get("limit")) || 100);

    const league = me?.league
      ?? await env.DB.prepare("SELECT id FROM leagues LIMIT 1").first();

    // A fighter is taken if any team currently holds them.
    let sql =
      `SELECT f.id, f.display_name, f.division, f.rank, f.age, f.ufc_record,
              f.form, f.proj_points, f.proj_vorp, f.is_booked,
              rh.team_id AS taken_by, t.name AS taken_by_name
         FROM fighters f
         LEFT JOIN roster_history rh
           ON rh.fighter_id = f.id AND rh.league_id = ? AND rh.released_at IS NULL
         LEFT JOIN teams t ON t.id = rh.team_id
        WHERE 1=1`;
    const args = [league ? league.id : 0];
    if (division) { sql += " AND f.division = ?"; args.push(division); }
    if (q) { sql += " AND lower(f.display_name) LIKE ?"; args.push(`%${q}%`); }
    if (availableOnly) sql += " AND rh.team_id IS NULL";
    sql += " ORDER BY f.proj_vorp DESC NULLS LAST LIMIT ?";
    args.push(limit);

    const { results } = await env.DB.prepare(sql).bind(...args).all();
    return json({ count: results.length, fighters: results });
  },

  "POST /api/draft/start": async (req, env, me) => {
    if (!me?.manager?.is_commissioner) return bad("Commissioner only", 403);
    const d = await currentDraft(env, me.league.id);
    if (!d) return bad("No draft scheduled");
    if (d.status === "live") return bad("The draft is already live");
    if (d.status === "complete") return bad("This draft is finished");

    const now = new Date();
    await env.DB.prepare(
      `UPDATE drafts SET status='live', started_at=?, deadline_at=?
        WHERE id=?`
    ).bind(now.toISOString(), deadlineFor(d.pick_seconds, now), d.id).run();
    return json(await draftState(env, me));
  },

  "GET /api/draft/state": async (req, env, me) => json(await draftState(env, me)),

  "POST /api/draft/pick": async (req, env, me) => {
    const body = await req.json().catch(() => ({}));
    return makePick(env, me, Number(body.fighter_id), false);
  },

  // Called by any connected client once the clock shows expired. The
  // server re-checks the deadline, so a client with a fast clock cannot
  // steal someone's pick.
  "POST /api/draft/autopick": async (req, env, me) => {
    const d = await currentDraft(env, me?.league?.id);
    if (!d || d.status !== "live") return bad("No live draft");
    if (!d.deadline_at || new Date(d.deadline_at) > new Date()) {
      return bad("The pick clock has not expired");
    }
    return makePick(env, me, null, true);
  },

  "GET /api/state": async (req, env, me) => json(await getState(env, me)),

  "POST /api/teams": async (req, env, me) => {
    if (!me?.manager?.is_commissioner) return bad("Commissioner only", 403);
    const body = await req.json().catch(() => ({}));
    const name = (body.name || "").trim();
    if (!name) return bad("Team name is required");
    if (name.length > 40) return bad("Team name must be 40 characters or fewer");

    const dupe = await env.DB.prepare(
      "SELECT id FROM teams WHERE league_id = ? AND lower(name) = lower(?)"
    ).bind(me.league.id, name).first();
    if (dupe) return bad(`There is already a team called ${name}`);

    let managerId = null;
    const email = (body.manager_email || "").toLowerCase().trim();
    if (email) {
      const existing = await env.DB.prepare(
        "SELECT id FROM managers WHERE league_id = ? AND email = ?"
      ).bind(me.league.id, email).first();
      if (existing) {
        managerId = existing.id;
      } else {
        const res = await env.DB.prepare(
          `INSERT INTO managers (league_id, email, display_name)
           VALUES (?, ?, ?)`
        ).bind(me.league.id, email, body.manager_name?.trim() || email.split("@")[0]).run();
        managerId = res.meta.last_row_id;
      }
    }

    const res = await env.DB.prepare(
      "INSERT INTO teams (league_id, manager_id, name) VALUES (?, ?, ?)"
    ).bind(me.league.id, managerId, name).run();
    return json({ id: res.meta.last_row_id, name }, 201);
  },

  "DELETE /api/teams": async (req, env, me) => {
    if (!me?.manager?.is_commissioner) return bad("Commissioner only", 403);
    const id = new URL(req.url).searchParams.get("id");
    if (!id) return bad("Missing team id");
    const draft = await env.DB.prepare(
      "SELECT status FROM drafts WHERE league_id = ? ORDER BY id DESC LIMIT 1"
    ).bind(me.league.id).first();
    if (draft && draft.status !== "scheduled") {
      return bad("Teams cannot be removed once the draft has started");
    }
    await env.DB.prepare(
      "DELETE FROM teams WHERE id = ? AND league_id = ?"
    ).bind(id, me.league.id).run();
    return json({ ok: true });
  },

  "PATCH /api/league": async (req, env, me) => {
    if (!me?.manager?.is_commissioner) return bad("Commissioner only", 403);
    const body = await req.json().catch(() => ({}));
    const name = (body.name || "").trim();
    if (!name) return bad("League name is required");
    await env.DB.prepare("UPDATE leagues SET name = ? WHERE id = ?")
      .bind(name, me.league.id).run();
    return json({ ok: true });
  },

  "POST /api/draft": async (req, env, me) => {
    if (!me?.manager?.is_commissioner) return bad("Commissioner only", 403);
    const body = await req.json().catch(() => ({}));

    const teams = await env.DB.prepare(
      "SELECT id FROM teams WHERE league_id = ? ORDER BY id"
    ).bind(me.league.id).all();
    if (teams.results.length < 2) {
      return bad("Add at least two teams before scheduling a draft");
    }

    const existing = await env.DB.prepare(
      "SELECT id, status FROM drafts WHERE league_id = ? ORDER BY id DESC LIMIT 1"
    ).bind(me.league.id).first();
    if (existing && existing.status !== "scheduled") {
      return bad("A draft is already underway");
    }

    const divisions = JSON.parse(me.league.divisions);
    const rounds = divisions.length * me.league.slots_per_div;
    const pickSeconds = Math.min(600, Math.max(15, Number(body.pick_seconds) || 90));

    // Randomise draft order unless the commissioner supplied one.
    let order = Array.isArray(body.team_order) && body.team_order.length
      ? body.team_order
      : teams.results.map((t) => t.id);
    if (!body.team_order) {
      for (let i = order.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [order[i], order[j]] = [order[j], order[i]];
      }
    }

    if (existing) {
      await env.DB.prepare("DELETE FROM drafts WHERE id = ?").bind(existing.id).run();
    }
    const res = await env.DB.prepare(
      `INSERT INTO drafts (league_id, status, scheduled_at, pick_seconds,
                           rounds, team_order, snake)
       VALUES (?, 'scheduled', ?, ?, ?, ?, 1)`
    ).bind(
      me.league.id,
      body.scheduled_at || null,
      pickSeconds,
      rounds,
      JSON.stringify(order)
    ).run();

    return json({ id: res.meta.last_row_id, rounds, team_order: order }, 201);
  },
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) {
      return env.ASSETS.fetch(request);
    }

    const email = identity(request);
    const isWrite = request.method !== "GET";
    if (isWrite && !email) {
      return bad(
        "Sign-in required. This league is protected by Cloudflare Access — " +
        "if you are seeing this, Access is not yet switched on for this site.",
        401
      );
    }

    let me = null;
    try {
      me = await whoami(env, email);
    } catch (err) {
      return bad(`Database not ready: ${err.message}`, 500);
    }

    const handler = routes[`${request.method} ${url.pathname}`];
    if (!handler) return bad("Not found", 404);

    try {
      return await handler(request, env, me);
    } catch (err) {
      return bad(err.message || "Something went wrong", 500);
    }
  },
};
