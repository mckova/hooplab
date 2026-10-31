"""Coach-facing insights built on the skill model: team snapshot, trends,
opponent matchup / game plan, practice plans and per-player homework."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import drills as dr
from .db import DB, now_iso
from .skills import BASELINE, DIMENSIONS, build_profile, rates_from_events

TREND_DAYS = 21


def _profiles(db: DB, team_id: int, half_life: float, now: datetime | None = None):
    players = db.q("SELECT * FROM players WHERE team_id = ? ORDER BY number", (team_id,))
    out = []
    for p in players:
        evs = db.player_events(p["id"])
        out.append((p, build_profile(p["id"], p["position"], evs, now=now, half_life_days=half_life), len(evs)))
    return out


def _settings(db: DB, team_id: int) -> tuple[dict, float]:
    s = db.settings(team_id)
    return s.get("emphasis", {}), float(s.get("half_life_days", 45))


def player_card(p: dict, prof, n_events: int, emphasis: dict) -> dict:
    est = {d: e.to_dict() for d, e in prof.estimates.items()}
    needs = prof.needs(emphasis)
    return {
        "player": p, "events": n_events, "skills": est,
        "strengths": [e.to_dict() for e in prof.strengths()[:3]],
        "weaknesses": [e.to_dict() for e in prof.weaknesses()[:3]],
        "needs": needs,
        "focus": [d for d, v in sorted(needs.items(), key=lambda kv: -kv[1]) if v > 0.02][:2],
    }


def team_snapshot(db: DB, team_id: int) -> dict:
    emphasis, half_life = _settings(db, team_id)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=TREND_DAYS)).isoformat(timespec="seconds")
    current = _profiles(db, team_id, half_life, now)
    cards = [player_card(p, prof, n, emphasis) for p, prof, n in current]

    # team-level dimensions: mean posterior vs mean positional baseline
    team_dims = {}
    for d in DIMENSIONS:
        if not cards:
            break
        m = sum(c["skills"][d]["mean"] for c in cards) / len(cards)
        b = sum(c["skills"][d]["baseline"] for c in cards) / len(cards)
        ev = sum(c["skills"][d]["evidence"] for c in cards)
        team_dims[d] = {"name": DIMENSIONS[d][0], "mean": round(m, 3), "baseline": round(b, 3),
                        "gap": round((m - b) / b, 3), "evidence": round(ev, 1)}

    exploit = []
    for c in cards:
        for s in c["strengths"]:
            exploit.append({"player": c["player"]["name"], "player_id": c["player"]["id"],
                            "dimension": s["dimension"], "name": s["name"], "mean": s["mean"],
                            "baseline": s["baseline"], "score": round(s["gap"] * s["importance"], 3)})
    exploit.sort(key=lambda x: -x["score"])

    need = team_need(cards)
    movers = []
    for c in cards:
        for t in trends(db.player_events(c["player"]["id"]), cutoff):
            t["player"] = c["player"]["name"]
            c["skills"][t["dimension"]]["trend"] = t["trend"]
            movers.append(t)
    movers.sort(key=lambda m: -abs(m["z"]))
    return {
        "team": db.one("SELECT * FROM teams WHERE id = ?", (team_id,)),
        "generated_at": now_iso(),
        "players": cards,
        "team_dimensions": team_dims,
        "exploit": exploit[:6],
        "priorities": [{"dimension": d, "name": DIMENSIONS[d][0], "need": round(v, 3)}
                       for d, v in sorted(need.items(), key=lambda kv: -kv[1])[:4]],
        "trends": movers[:6],
        "data_coverage": {"events": sum(c["events"] for c in cards),
                          "players_with_little_data": [c["player"]["name"] for c in cards if c["events"] < 15]},
    }


def trends(events: list[dict], cutoff: str, min_n: int = 30, z_min: float = 2.8) -> list[dict]:
    """Is a player's success rate on a dimension moving over time?

    Fits a linear-probability slope of outcome vs. date per dimension and keeps
    it only if |slope / se| >= z_min (strict, because ~10 dimensions x roster
    size tests run at once). Reported alongside: rate before vs. since `cutoff`.
    """
    from .skills import event_to_observations
    series: dict[str, list[tuple[float, int]]] = {}
    for e in events:
        try:
            ts = datetime.fromisoformat(e["occurred_at"]).timestamp() / 86400.0
        except (TypeError, ValueError):
            continue
        for dim, ok in event_to_observations(e):
            series.setdefault(dim, []).append((ts, int(ok)))
    cut = datetime.fromisoformat(cutoff).timestamp() / 86400.0
    out = []
    for dim, pts in series.items():
        n = len(pts)
        if n < min_n:
            continue
        mt = sum(t for t, _ in pts) / n
        my = sum(y for _, y in pts) / n
        sxx = sum((t - mt) ** 2 for t, _ in pts)
        if sxx == 0 or my in (0, 1):
            continue
        slope = sum((t - mt) * (y - my) for t, y in pts) / sxx
        resid = sum((y - my - slope * (t - mt)) ** 2 for t, y in pts) / max(n - 2, 1)
        z = slope / (resid / sxx) ** 0.5
        recent = [y for t, y in pts if t >= cut]
        before = [y for t, y in pts if t < cut]
        if abs(z) >= z_min and recent and before:
            out.append({"dimension": dim, "name": DIMENSIONS[dim][0],
                        "before": round(sum(before) / len(before), 3),
                        "recent": round(sum(recent) / len(recent), 3),
                        "trend": round(slope * 30, 3),        # change per 30 days
                        "z": round(z, 2), "n": n})
    return out


def team_need(cards: list[dict]) -> dict[str, float]:
    if not cards:
        return {d: 0.1 for d in DIMENSIONS}
    return {d: round(sum(c["needs"][d] for c in cards) / len(cards), 4) for d in DIMENSIONS}


def who_needs(cards: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in DIMENSIONS:
        ranked = sorted(cards, key=lambda c: -c["needs"][d])
        out[d] = [c["player"]["name"] for c in ranked if c["needs"][d] > 0.04]
    return out


# ------------------------------------------------------------------ opponents
def opponent_profile(db: DB, opponent_id: int) -> dict:
    """Scouting = tagged opponent events (from video or manual), with manual
    ratings filling dimensions that have no events."""
    import json
    opp = db.one("SELECT * FROM opponents WHERE id = ?", (opponent_id,))
    if not opp:
        return {}
    rates = rates_from_events(db.opponent_events(opponent_id))
    manual = json.loads(opp.get("scouting") or "{}")
    dims = {}
    for d in DIMENSIONS:
        if d in rates and rates[d]["n"] >= 5:
            dims[d] = {"rate": round(rates[d]["rate"], 3), "n": rates[d]["n"], "source": "events"}
        elif d in manual:
            dims[d] = {"rate": float(manual[d]), "n": 0, "source": "scouting"}
    return {"opponent": {k: v for k, v in opp.items() if k != "scouting"}, "dimensions": dims}


LEAGUE = {d: sum(BASELINE[p][d] for p in BASELINE) / len(BASELINE) for d in DIMENSIONS}

RULES = [
    # (their dim, condition, our dim that exploits it, message)
    ("on_ball_defense", "low", "rim_finishing", "Their on-ball defense is weak: attack downhill and isolate {best}."),
    ("help_defense", "low", "playmaking", "Their help is slow: drive-and-kick, swing the ball one more time. Let {best} create."),
    ("rebounding", "low", "rebounding", "They lose the glass: send 3 to the offensive boards; {best} leads the crash."),
    ("ball_security", "low", "on_ball_defense", "They turn it over: pressure the ball handler and jump passing lanes. Put {best} on the ball."),
    ("transition", "low", "transition", "They don't get back: push the pace after every rebound; {best} runs the lane."),
    ("three_point", "low", None, "They can't shoot it from deep: go under screens and pack the paint."),
    ("three_point", "high", None, "They shoot it well from three: top-lock shooters and close out high."),
    ("rim_finishing", "high", "help_defense", "They finish well at the rim: wall up early, help from the weak side ({best} anchors)."),
    ("free_throw", "low", None, "Poor free-throw shooting: late in close games, foul and make them earn it from the line."),
    ("playmaking", "high", "on_ball_defense", "Their creator drives everything: deny the catch, show bodies. {best} takes the matchup."),
]


def matchup(db: DB, team_id: int, opponent_id: int) -> dict:
    snap = team_snapshot(db, team_id)
    opp = opponent_profile(db, opponent_id)
    ours = snap["team_dimensions"]
    table, plan = [], []
    for d, info in opp.get("dimensions", {}).items():
        us = ours.get(d, {}).get("mean")
        table.append({"dimension": d, "name": DIMENSIONS[d][0], "us": us, "them": info["rate"],
                      "league": round(LEAGUE[d], 3), "edge": None if us is None else round(us - info["rate"], 3),
                      "source": info["source"]})
    best_at = {}
    for d in DIMENSIONS:
        ranked = sorted(snap["players"], key=lambda c: -c["skills"][d]["mean"])
        best_at[d] = ranked[0]["player"]["name"] if ranked else "your best player"
    for their_dim, cond, our_dim, msg in RULES:
        info = opp.get("dimensions", {}).get(their_dim)
        if not info:
            continue
        rel = (info["rate"] - LEAGUE[their_dim]) / LEAGUE[their_dim]
        if (cond == "low" and rel <= -0.08) or (cond == "high" and rel >= 0.08):
            plan.append({"insight": msg.format(best=best_at.get(our_dim, "")).strip(),
                         "evidence": f"{DIMENSIONS[their_dim][0]}: {info['rate']:.0%} vs league {LEAGUE[their_dim]:.0%}"
                                     f" ({info['source']}{', n=' + str(info['n']) if info['n'] else ''})",
                         "strength": round(abs(rel), 3)})
    plan.sort(key=lambda x: -x["strength"])
    # practice emphasis for game prep: our weak dims where they're strong get extra weight
    prep = {}
    for row in table:
        if row["us"] is not None and row["them"] > row["league"]:
            prep[row["dimension"]] = round((row["them"] - row["league"]) / row["league"], 3)
    return {"opponent": opp.get("opponent"), "comparison": table, "game_plan": plan, "prep_emphasis": prep}


# ------------------------------------------------------------------ plans + homework
def library(db: DB, team_id: int) -> list:
    """Built-in drills + drills Claude designed for this team."""
    import json
    custom = [dr.drill_from_dict(json.loads(r["drill"]))
              for r in db.q("SELECT drill FROM custom_drills WHERE team_id = ?", (team_id,))]
    return dr.LIBRARY + custom

def practice_plan(db: DB, team_id: int, req: dr.PlanRequest, opponent_id: int | None = None) -> dict:
    snap = team_snapshot(db, team_id)
    need = team_need(snap["players"])
    if opponent_id:
        for d, w in matchup(db, team_id, opponent_id)["prep_emphasis"].items():
            need[d] = need.get(d, 0) + 0.1 * w
    fb = db.q("SELECT drill_id, rating, ran FROM drill_feedback WHERE team_id = ?", (team_id,))
    lib = library(db, team_id)
    prefs = dr.preference_weights(fb, lib)
    plan = dr.plan_practice(need, req, prefs, who_needs(snap["players"]), lib)
    plan["team_need"] = need
    return plan


def assign_homework(db: DB, team_id: int, days: int = 7) -> list[dict]:
    """Two items per player for their top development needs, drawn from solo
    drills the coach hasn't rejected; replaces still-open assignments."""
    snap = team_snapshot(db, team_id)
    fb = db.q("SELECT drill_id, rating, ran FROM drill_feedback WHERE team_id = ?", (team_id,))
    lib = library(db, team_id)
    prefs = dr.preference_weights(fb, lib)
    disliked = {f["drill_id"] for f in fb if (f["rating"] or 0) <= -0.5}
    due = (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
    created = []
    for c in snap["players"]:
        pid = c["player"]["id"]
        with db.tx() as conn:
            conn.execute("DELETE FROM homework WHERE player_id = ? AND status = 'assigned'", (pid,))
        used = set()
        for dim in c["focus"]:
            d = dr.homework_for(dim, prefs, exclude=disliked | used, lib=lib)
            if not d:
                continue
            used.add(d.id)
            pl = build_playlist(db, team_id, f"{c['player']['name']}: {DIMENSIONS[dim][0]} (watch before the drill)",
                                pid, dim, outcome=False, note="Auto-built from your own possessions", limit=5)
            hid = db.insert("homework", {"player_id": pid, "drill_id": d.id, "dimension": dim,
                                         "target": d.metric, "due": due, "created_at": now_iso(),
                                         "playlist_id": pl["id"] if pl else None})
            created.append({"id": hid, "player": c["player"]["name"], "player_id": pid,
                            "playlist_id": pl["id"] if pl else None, "clips": len(pl["clips"]) if pl else 0,
                            "dimension": dim, "drill": d.to_dict(), "target": d.metric, "due": due,
                            "reason": f"{DIMENSIONS[dim][0]}: {c['skills'][dim]['mean']:.0%} vs "
                                      f"{c['skills'][dim]['baseline']:.0%} expected for a {c['player']['position']}"})
    return created


def complete_homework(db: DB, homework_id: int, made: int | None, attempts: int | None) -> dict:
    """Self-reported homework results become low-weight evidence (0.3x): they
    show work done, but uncontested reps are weaker evidence than game events."""
    hw = db.one("SELECT * FROM homework WHERE id = ?", (homework_id,))
    if not hw:
        raise KeyError(homework_id)
    db.update("homework", homework_id, {"status": "done", "made": made, "attempts": attempts})
    if made is not None and attempts:
        ev_type = {"three_point": ("shot", "three"), "midrange": ("shot", "mid"),
                   "rim_finishing": ("shot", "rim"), "free_throw": ("shot", "ft")}.get(hw["dimension"])
        if ev_type:
            sess = db.one("SELECT s.id FROM sessions s JOIN players p ON p.team_id = s.team_id "
                          "WHERE p.id = ? AND s.kind = 'homework'", (hw["player_id"],))
            if not sess:
                team = db.one("SELECT team_id FROM players WHERE id = ?", (hw["player_id"],))
                sid = db.insert("sessions", {"team_id": team["team_id"], "kind": "homework",
                                             "title": "Homework log", "date": now_iso()})
            else:
                sid = sess["id"]
            evs = [{"player_id": hw["player_id"], "type": ev_type[0], "zone": ev_type[1],
                    "outcome": i < made, "weight": 0.3, "source": "homework"} for i in range(attempts)]
            db.add_events(sid, evs, now_iso(), source="homework")
    return db.one("SELECT * FROM homework WHERE id = ?", (homework_id,))


# ------------------------------------------------------------------ play types (PPP)
def play_type_report(db: DB, team_id: int, player_id: int | None = None,
                     opponent_id: int | None = None, min_n: int = 5) -> dict:
    """Points per possession by play type for the team, one player, or a
    scouted opponent. Possession-ending events: shots (made/missed) and
    turnovers that carry a play_type tag."""
    from .skills import PLAY_TYPES, possession_points
    if opponent_id:
        rows = db.q("SELECT * FROM events WHERE opponent_id = ? AND play_type IS NOT NULL", (opponent_id,))
    elif player_id:
        rows = db.q("SELECT * FROM events WHERE player_id = ? AND play_type IS NOT NULL", (player_id,))
    else:
        rows = db.q("SELECT e.* FROM events e JOIN players p ON p.id = e.player_id "
                    "WHERE p.team_id = ? AND e.play_type IS NOT NULL", (team_id,))
    agg: dict[str, list[int]] = {}
    for e in rows:
        pts = possession_points(e)
        if pts is None or e["play_type"] not in PLAY_TYPES:
            continue
        a = agg.setdefault(e["play_type"], [0, 0, 0])  # points, possessions, turnovers
        a[0] += pts
        a[1] += 1
        a[2] += int(e["type"] == "turnover")
    total = sum(v[1] for v in agg.values()) or 1
    out = []
    for pt, (pts, n, to) in agg.items():
        ppp = pts / n
        out.append({"play_type": pt, "name": PLAY_TYPES[pt], "possessions": n, "frequency": round(n / total, 3),
                    "ppp": round(ppp, 3), "turnover_rate": round(to / n, 3), "reliable": n >= min_n})
    out.sort(key=lambda r: -r["possessions"])
    reliable = [r for r in out if r["reliable"]]
    overall = sum(v[0] for v in agg.values()) / total if agg else None
    return {"overall_ppp": None if overall is None else round(overall, 3), "possessions": sum(v[1] for v in agg.values()),
            "play_types": out,
            "best": max(reliable, key=lambda r: r["ppp"])["play_type"] if reliable else None,
            "worst": min(reliable, key=lambda r: r["ppp"])["play_type"] if reliable else None}


# ------------------------------------------------------------------ clips & playlists
def _dims_filter(dimension: str | None):
    from .skills import event_to_observations
    def ok(e, outcome):
        obs = event_to_observations(e)
        if dimension:
            obs = [o for o in obs if o[0] == dimension]
            if not obs:
                return False
        if outcome is not None:
            return any(r == outcome for _, r in obs) if obs else False
        return True
    return ok


def clips(db: DB, team_id: int, player_id: int | None = None, dimension: str | None = None,
          outcome: bool | None = None, play_type: str | None = None, opponent_id: int | None = None,
          limit: int = 30) -> list[dict]:
    """Events that have video: every number in HoopLab can open its clips."""
    sql = ("SELECT e.*, s.title AS session_title, s.date AS session_date, p.name AS player FROM events e "
           "JOIN sessions s ON s.id = e.session_id LEFT JOIN players p ON p.id = e.player_id "
           "WHERE s.team_id = ? AND s.video_path IS NOT NULL AND e.t_start IS NOT NULL")
    args: list = [team_id]
    if player_id:
        sql += " AND e.player_id = ?"
        args.append(player_id)
    if opponent_id:
        sql += " AND e.opponent_id = ?"
        args.append(opponent_id)
    if play_type:
        sql += " AND e.play_type = ?"
        args.append(play_type)
    sql += " ORDER BY s.date DESC, e.t_start"
    keep = _dims_filter(dimension)
    out = []
    for e in db.q(sql, args):
        if keep(e, outcome):
            out.append({"event_id": e["id"], "session_id": e["session_id"], "session": e["session_title"],
                        "date": e["session_date"][:10], "player": e["player"], "type": e["type"],
                        "outcome": e["outcome"], "zone": e["zone"], "play_type": e["play_type"],
                        "t_start": e["t_start"], "t_end": e["t_end"],
                        "video_url": f"/api/sessions/{e['session_id']}/video"})
            if len(out) >= limit:
                break
    return out


def build_playlist(db: DB, team_id: int, title: str, player_id: int | None = None,
                   dimension: str | None = None, outcome: bool | None = None,
                   play_type: str | None = None, note: str | None = None, limit: int = 8) -> dict | None:
    import json
    items = clips(db, team_id, player_id, dimension, outcome, play_type, limit=limit)
    if not items:
        return None
    pid = db.insert("playlists", {"team_id": team_id, "player_id": player_id, "title": title, "note": note,
                                  "items": json.dumps([c["event_id"] for c in items]), "created_at": now_iso()})
    return {"id": pid, "title": title, "note": note, "clips": items}


def get_playlist(db: DB, playlist_id: int) -> dict | None:
    import json
    pl = db.one("SELECT * FROM playlists WHERE id = ?", (playlist_id,))
    if not pl:
        return None
    ids = json.loads(pl["items"])
    all_clips = {c["event_id"]: c for c in clips(db, pl["team_id"], limit=10_000)}
    pl["clips"] = [all_clips[i] for i in ids if i in all_clips]
    pl.pop("items")
    return pl
