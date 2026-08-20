/**
 * Draft engine.
 *
 * Pure functions plus the SQL to record a pick. Kept separate from the
 * live-connection layer so the rules can be tested without sockets.
 *
 * The invariant that matters: a fighter can be picked exactly once, and
 * only by the team that is genuinely on the clock. Everything else is
 * recoverable; a double-assignment with seven people watching is not.
 */

/** Snake order: 1..N, then N..1, then 1..N. */
export function teamOnClock(order, overall) {
  const n = order.length;
  const round = Math.floor((overall - 1) / n);      // 0-based
  const slot = (overall - 1) % n;
  const idx = round % 2 === 0 ? slot : n - 1 - slot;
  return { round: round + 1, teamId: order[idx] };
}

export function totalPicks(order, rounds) {
  return order.length * rounds;
}

/**
 * Which division slots does a team still need?
 * Returns { division: remaining } for anything not yet full.
 */
export function openSlots(divisions, slotsPerDivision, held) {
  const counts = {};
  for (const d of divisions) counts[d] = 0;
  for (const h of held) counts[h.division] = (counts[h.division] || 0) + 1;
  const open = {};
  for (const d of divisions) {
    const left = slotsPerDivision - (counts[d] || 0);
    if (left > 0) open[d] = left;
  }
  return open;
}

/**
 * Can this team take this fighter right now?
 * Returns null if legal, or a human-readable reason if not.
 */
export function validatePick({ fighter, held, divisions, slotsPerDivision,
                               picksRemainingForTeam }) {
  if (!fighter) return "That fighter is not in the pool";
  if (fighter.taken_by) return `${fighter.display_name} is already taken`;
  if (!divisions.includes(fighter.division)) {
    return `${fighter.division} is not a division in this league`;
  }

  const open = openSlots(divisions, slotsPerDivision, held);
  if (!open[fighter.division]) {
    return `Your ${fighter.division} slots are full`;
  }

  // Late in the draft, remaining picks must exactly cover remaining slots.
  // Taking a second heavyweight when one flyweight slot is still empty and
  // only one pick remains would leave an unfillable roster.
  const slotsStillNeeded = Object.values(open).reduce((a, b) => a + b, 0);
  if (picksRemainingForTeam <= slotsStillNeeded) {
    const mustFill = Object.keys(open).filter((d) => open[d] >= 1);
    const wouldStrand = slotsStillNeeded - 1 > picksRemainingForTeam - 1;
    if (wouldStrand && !mustFill.includes(fighter.division)) {
      return `You need every remaining pick to fill: ${mustFill.join(", ")}`;
    }
  }
  return null;
}

/** The best available fighter for a team's open slots, by projection. */
export function autopickChoice(available, open, queue = []) {
  for (const q of queue) {
    const f = available.find((a) => a.id === q && open[a.division]);
    if (f) return f;
  }
  const eligible = available.filter((a) => open[a.division]);
  if (!eligible.length) return null;
  return eligible.reduce((best, f) =>
    (f.proj_vorp ?? -999) > (best.proj_vorp ?? -999) ? f : best);
}

export function deadlineFor(pickSeconds, from = new Date()) {
  return new Date(from.getTime() + pickSeconds * 1000).toISOString();
}
