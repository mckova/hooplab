"""Claude at the centre of the coaching loop.

* After every game or practice: a debrief that compares what happened with what
  the model expected from each player, written by Claude and posted to the
  coach's inbox.
* For every player: a personal message (strength to keep using, what to work
  on, this week's homework and the film to watch), in the player's language.
* Progress over time: how each skill estimate moved week by week.

The engine computes every number; Claude writes. Without an API key the same
facts render through templates, so nothing breaks.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from . import ai
from .db import DB, now_iso
from .skills import DIMENSIONS, PLAY_TYPES, build_profile, event_to_observations, possession_points

STANDOUT_Z = 1.5
STANDOUT_MIN_N = 4


# ------------------------------------------------------------------ writing with Claude
def write(prompt: str, effort: str = "low", max_tokens: int = 6000) -> tuple[str, str]:
    """One Claude call that returns (text, model). Raises AIUnavailable or RuntimeError."""
    client = ai.get_client()
    msg = client.beta.messages.create(model=ai.MODEL, max_tokens=max_tokens, output_config={"effort": effort},
                                      messages=[{"role": "user", "content": prompt}], **ai.FALLBACK_KW)
    text = ai.text_of(msg)
    if msg.stop_reason == "refusal" or not text:
        raise RuntimeError(f"no text (stop_reason={msg.stop_reason})")
    return text, msg.model


def _write_or(template: str, prompt: str, use_ai: bool, effort: str = "low") -> dict:
    if not use_ai:
        return {"source": "template", "text": template}
    try:
        text, model = write(prompt, effort)
        return {"source": model, "text": text}
    except ai.AIUnavailable:
        return {"source": "template", "text": template}
    except Exception as exc:  # network / auth: degrade, never fail the page
        return {"source": "template", "text": template, "error": str(exc)[:200]}


def _lang(language: str) -> str:
    return "Hebrew" if language == "he" else "English"


# ------------------------------------------------------------------ progress over time
def player_history(db: DB, player_id: int, points: int = 10, step_days: int = 7) -> dict:
    """Skill estimates as the model saw them at the end of each of the last `points` weeks."""
    p = db.one("SELECT * FROM players WHERE id = ?", (player_id,))
    events = db.player_events(player_id)
    half_life = float(db.settings(p["team_id"]).get("half_life_days", 45))
    now = datetime.now(timezone.utc)
    series = {d: [] for d in DIMENSIONS}
    dates = []
    for k in range(points - 1, -1, -1):
        at = now - timedelta(days=step_days * k)
        cut = at.isoformat(timespec="seconds")
        prof = build_profile(player_id, p["position"], [e for e in events if (e["occurred_at"] or "") <= cut],
                             now=at, half_life_days=half_life)
        dates.append(at.date().isoformat())
        for d, est in prof.estimates.items():
            series[d].append(round(est.mean, 3))
    baseline = {d: round(est.baseline, 3) for d, est in prof.estimates.items()}
    # change over the last 4 weeks only: earlier points mostly show the prior giving way to data
    span = min(4, len(dates) - 1)
    change = {d: round(v[-1] - v[-1 - span], 3) for d, v in series.items()}
    return {"player": {k: p[k] for k in ("id", "name", "number", "position")}, "dates": dates,
            "series": series, "baseline": baseline, "change": change, "change_weeks": span,
            "most_improved": max(change, key=change.get), "most_declined": min(change, key=change.get)}


# ------------------------------------------------------------------ session debrief
def session_report(db: DB, session_id: int) -> dict:
    """What happened in one session vs. what the model expected from each player."""
    s = db.one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    team_id = s["team_id"]
    half_life = float(db.settings(team_id).get("half_life_days", 45))
    when = datetime.fromisoformat(s["date"])
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    evs = db.q("SELECT * FROM events WHERE session_id = ?", (session_id,))
    players = {p["id"]: p for p in db.q("SELECT * FROM players WHERE team_id = ?", (team_id,))}
    rows, standouts = [], []
    for pid, p in players.items():
        mine = [e for e in evs if e["player_id"] == pid]
        if not mine:
            continue
        before = [e for e in db.player_events(pid) if e["session_id"] != session_id]
        prof = build_profile(pid, p["position"], before, now=when, half_life_days=half_life)
        tally: dict[str, list[int]] = {}
        for e in mine:
            for dim, ok in event_to_observations(e):
                t = tally.setdefault(dim, [0, 0])
                t[0] += int(ok)
                t[1] += 1
        dims = []
        for dim, (ok, n) in tally.items():
            exp = prof.estimates[dim].mean
            rate = ok / n
            z = (rate - exp) / math.sqrt(max(exp * (1 - exp), 1e-6) / n)
            d = {"dimension": dim, "name": DIMENSIONS[dim][0], "made": ok, "n": n, "rate": round(rate, 3),
                 "expected": round(exp, 3), "z": round(z, 2)}
            dims.append(d)
            if n >= STANDOUT_MIN_N and abs(z) >= STANDOUT_Z:
                standouts.append({"player": p["name"], "player_id": pid, **d})
        rows.append({"player": p["name"], "player_id": pid, "events": len(mine),
                     "dimensions": sorted(dims, key=lambda x: -x["n"])})
    standouts.sort(key=lambda x: -abs(x["z"]))

    def shooting(events):
        out = {}
        for e in events:
            if e["type"] == "shot" and e["zone"]:
                z = out.setdefault(e["zone"], [0, 0])
                z[0] += int(bool(e["outcome"]))
                z[1] += 1
        return {k: {"made": v[0], "attempts": v[1]} for k, v in out.items()}

    def ppp(events):
        agg: dict[str, list[int]] = {}
        for e in events:
            pts = possession_points(e)
            if pts is None or not e["play_type"]:
                continue
            a = agg.setdefault(e["play_type"], [0, 0])
            a[0] += pts
            a[1] += 1
        return [{"play_type": k, "name": PLAY_TYPES.get(k, k), "possessions": n, "points": pts,
                 "ppp": round(pts / n, 2)} for k, (pts, n) in sorted(agg.items(), key=lambda kv: -kv[1][1])]

    ours = [e for e in evs if e["player_id"]]
    theirs = [e for e in evs if e["opponent_id"]]
    opp = db.one("SELECT name FROM opponents WHERE id = ?", (s["opponent_id"],)) if s["opponent_id"] else None
    return {"session": {k: s[k] for k in ("id", "kind", "title", "date")}, "opponent": opp["name"] if opp else None,
            "events": len(evs), "players": rows, "standouts": standouts[:8],
            "team": {"shooting": shooting(ours), "turnovers": sum(e["type"] == "turnover" for e in ours),
                     "play_types": ppp(ours)},
            "opponent_stats": {"shooting": shooting(theirs), "play_types": ppp(theirs)} if theirs else None}


def template_debrief(r: dict) -> str:
    out = [f"{r['events']} events from {len(r['players'])} players."]
    shots = r["team"]["shooting"]
    if shots:
        out.append("Shooting: " + ", ".join(f"{z} {v['made']}/{v['attempts']}" for z, v in shots.items())
                   + f"; {r['team']['turnovers']} turnover{'' if r['team']['turnovers'] == 1 else 's'}.")
    up = [x for x in r["standouts"] if x["z"] > 0][:3]
    down = [x for x in r["standouts"] if x["z"] < 0][:3]
    for x in up:
        out.append(f"Above expectation: {x['player']}, {x['name'].lower()} {x['made']}/{x['n']} "
                   f"(model expected {x['expected']:.0%}).")
    for x in down:
        out.append(f"Below expectation: {x['player']}, {x['name'].lower()} {x['made']}/{x['n']} "
                   f"(model expected {x['expected']:.0%}).")
    pts = [p for p in r["team"]["play_types"] if p["possessions"] >= 2]
    if pts:
        best = max(pts, key=lambda p: p["ppp"])
        out.append(f"Best action: {best['name'].lower()} ({best['points']} points on {best['possessions']} possessions).")
    if not r["standouts"]:
        out.append("Nobody was far from what the model expected; the estimates were updated.")
    return "\n".join(out)


def debrief(db: DB, session_id: int, language: str = "en", use_ai: bool = True) -> dict:
    """Write the post-session debrief and post it to the coach's inbox."""
    r = session_report(db, session_id)
    prompt = (f"You are the assistant coach. Write the post-{r['session']['kind']} debrief for the head coach in "
              f"{_lang(language)}, at most 150 words, as short lines: what stood out (who beat or missed the model's "
              "expectation and by how much), what the play types say, and one concrete thing for the next practice. "
              "Quote only numbers from the report; with fewer than 4 attempts say the sample is small.\n\n"
              "<session_report>\n" + json.dumps(r, ensure_ascii=False) + "\n</session_report>")
    out = _write_or(template_debrief(r), prompt, use_ai)
    s = db.one("SELECT team_id FROM sessions WHERE id = ?", (session_id,))
    vs = f" vs {r['opponent']}" if r["opponent"] else ""
    ref = json.dumps({"session_id": session_id})
    with db.tx() as c:   # one debrief per session: a new one replaces the old
        c.execute("DELETE FROM feed WHERE team_id = ? AND kind = 'debrief' AND ref = ?", (s["team_id"], ref))
    fid = db.insert("feed", {"team_id": s["team_id"], "kind": "debrief",
                             "title": f"Debrief: {r['session']['title'] or r['session']['kind']}{vs}",
                             "body": out["text"], "source": out["source"],
                             "ref": ref, "created_at": now_iso()})
    return {"id": fid, **out, "report": r}


# ------------------------------------------------------------------ inbox
def inbox(db: DB, team_id: int, snapshot: dict | None = None, limit: int = 12) -> list[dict]:
    """What needs the coach's attention: debriefs plus live alerts from the model."""
    items = []
    for f in db.q("SELECT * FROM feed WHERE team_id = ? ORDER BY id DESC LIMIT ?", (team_id, limit)):
        items.append({"kind": f["kind"], "title": f["title"], "body": f["body"], "source": f["source"],
                      "ref": json.loads(f["ref"] or "{}"), "at": f["created_at"]})
    if snapshot:
        for t in snapshot["trends"][:4]:
            word = "improving" if t["trend"] > 0 else "slipping"
            items.append({"kind": "trend", "title": f"{t['player']} is {word}: {t['name'].lower()}",
                          "body": f"{t['before']:.0%} → {t['recent']:.0%} over the last 3 weeks (significant, z={t['z']}).",
                          "ref": {"player": t["player"]}, "source": "model"})
        thin = snapshot["data_coverage"]["players_with_little_data"]
        if thin:
            items.append({"kind": "data", "title": "Little data on " + ", ".join(thin),
                          "body": "Tag a few of their possessions or film a practice so the model can say more.",
                          "ref": {}, "source": "model"})
    today = datetime.now(timezone.utc).date().isoformat()
    late = db.q("SELECT h.*, p.name FROM homework h JOIN players p ON p.id = h.player_id "
                "WHERE p.team_id = ? AND h.status = 'assigned' AND h.due < ?", (team_id, today))
    if late:
        names = sorted({h["name"] for h in late})
        items.append({"kind": "homework", "title": f"{len(late)} homework items overdue",
                      "body": "Waiting on: " + ", ".join(names) + ". Log results so the model can learn from them.",
                      "ref": {}, "source": "model"})
    return items


# ------------------------------------------------------------------ message to a player
def player_facts(db: DB, card: dict, trends: list[dict] | None = None) -> dict:
    pid = card["player"]["id"]
    hw = db.q("SELECT * FROM homework WHERE player_id = ? AND status = 'assigned' ORDER BY id", (pid,))
    from .insights import library
    by_id = {d.id: d for d in library(db, card["player"]["team_id"])}
    return {
        "player": card["player"]["name"], "number": card["player"]["number"], "position": card["player"]["position"],
        "strengths": [(s["name"], s["mean"], s["baseline"]) for s in card["strengths"]],
        "work_on": [(DIMENSIONS[d][0], card["skills"][d]["mean"], card["skills"][d]["baseline"]) for d in card["focus"]],
        # only statistically significant trends count as "progress" (small samples swing)
        "significant_trends": [{"skill": t["name"], "before": t["before"], "recent": t["recent"]}
                               for t in (trends or []) if t["player"] == card["player"]["name"]],
        "homework": [{"drill": by_id[h["drill_id"]].name if h["drill_id"] in by_id else h["drill_id"],
                      "setup": by_id[h["drill_id"]].setup if h["drill_id"] in by_id else "",
                      "target": h["target"], "due": h["due"], "has_film": bool(h["playlist_id"])} for h in hw],
    }


def template_player_message(f: dict) -> str:
    first = f["player"].split()[0]
    out = [f"Hi {first},"]
    if f["strengths"]:
        n, m, _ = f["strengths"][0]
        out.append(f"Keep using your {n.lower()}: you're at {m:.0%}, one of the team's weapons.")
    if f["work_on"]:
        out.append("This week we work on " + " and ".join(w[0].lower() for w in f["work_on"]) + ".")
    for h in f["homework"]:
        film = " Watch your clips first." if h["has_film"] else ""
        out.append(f"- {h['drill']}: {h['target']} (by {h['due']}).{film}")
    up = [t for t in f["significant_trends"] if t["recent"] > t["before"]]
    if up:
        t = up[0]
        out.append(f"Real progress in {t['skill'].lower()}: {t['before']:.0%} → {t['recent']:.0%} in the last 3 weeks. Keep going.")
    out.append("Coach")
    return "\n".join(out)


def player_message(db: DB, card: dict, language: str = "en", use_ai: bool = True,
                   trends: list[dict] | None = None) -> dict:
    f = player_facts(db, card, trends)
    prompt = (f"Write a short personal message from the coach to a youth basketball player, in {_lang(language)}, "
              "at most 90 words, warm and direct, ready to send on WhatsApp: one strength to keep using, what we work "
              "on this week and why, the homework with its target and due date (mention the film to watch first "
              "when has_film is true), and one line of encouragement, quoting significant_trends when there is an improvement. "
              "Use only the facts given; no invented numbers.\n\n<facts>\n"
              + json.dumps(f, ensure_ascii=False) + "\n</facts>")
    return {**_write_or(template_player_message(f), prompt, use_ai), "facts": f}
