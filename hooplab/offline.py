"""The assistant without a Claude key.

Every number HoopLab shows is computed by the deterministic engine, so the assistant can still answer from
it: it routes the coach's message to the same tools the Claude agent uses and writes the result as plain
sentences. Tag notes are read with a small rule parser instead of Claude. Both paths say so in the UI."""
from __future__ import annotations

import json
import re

from . import insights
from .agent import Agent
from .db import DB, now_iso
from .llm import template_briefing

ZONES = {"three": "three", "threes": "three", "3s": "three", "rim": "rim", "layup": "rim", "layups": "rim",
         "mid": "mid", "midrange": "mid", "mid-range": "mid", "free": "ft", "ft": "ft"}
NUM = {"once": 1, "twice": 2, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def reply(db: DB, team_id: int, message: str, chat_id: int | None, context: str | None) -> dict:
    ag = Agent(db, team_id)
    low = message.lower()
    player = next((p for p in ag._players() if any(t in low.split() or t in low for t in
                   [p["name"].lower(), *[x for x in p["name"].lower().split() if len(x) > 2]])), None)
    opp = next((o for o in db.q("SELECT * FROM opponents WHERE team_id = ?", (team_id,))
                if o["name"].lower() in low or o["name"].lower().split()[0] in low), None)
    if _has(low, "homework", "שיעורי בית", "שיעורי-בית"):
        hw = ag.t_assign_homework(7)
        by = {}
        for h in hw:
            by.setdefault(h["player"], []).append(h["drill"])
        text = "Assigned this week's homework, two items for each player:\n" + "\n".join(
            f"{p}: {', '.join(d)}" for p, d in by.items())
    elif _has(low, "practice", "plan", "אימון", "תכין"):
        mins = next((int(m) for m in re.findall(r"(\d+)\s*(?:min|minutes|דק)", low)), 75)
        pl = ag.t_plan_practice(mins, 10, 2, "high", [], opp["name"] if opp else None, full_court="half" not in low)
        clock = 0
        lines = []
        for b in pl["blocks"]:
            lines.append(f"{clock:>3} min  {b['drill']} ({b['minutes']} min): {b['why']}")
            clock += b["minutes"]
        text = (f"Practice plan, {pl['total_minutes']} minutes" + (f" for {pl['opponent']}" if pl["opponent"] else "") + ":\n"
                + "\n".join(lines))
    elif player and not _has(low, "scout"):
        g = ag.t_get_player(player["name"])
        sk = sorted(g["skills"].items(), key=lambda kv: kv[1]["mean"] - kv[1]["baseline"])
        from .skills import DIMENSIONS
        nm = lambda d: DIMENSIONS[d][0].lower()  # noqa: E731
        worst, best = sk[0], sk[-1]
        text = (f"{player['name']} (#{player['number']}, {player['position']}), {g['events']} tagged events.\n"
                f"Best against what the position expects: {nm(best[0])} {best[1]['mean']:.0%} (expected {best[1]['baseline']:.0%}).\n"
                f"Furthest below: {nm(worst[0])} {worst[1]['mean']:.0%} (expected {worst[1]['baseline']:.0%}).")
        if g["trends"]:
            t = g["trends"][0]
            text += f"\nTrend: {t['name'].lower()} {t['before']:.0%} to {t['recent']:.0%} over the last three weeks."
    elif opp or _has(low, "opponent", "scout", "game plan"):
        if not opp:
            opp = db.q("SELECT * FROM opponents WHERE team_id = ?", (team_id,))[0:1] or [None]
            opp = opp[0]
        m = insights.matchup(db, team_id, opp["id"]) if opp else None
        text = (f"Keys against {opp['name']}:\n" + "\n".join(f"{i + 1}. {g['insight']} ({g['evidence']})"
                for i, g in enumerate(m["game_plan"][:5]))) if m and m["game_plan"] else "No opponent to scout yet."
    elif _has(low, "play type", "self-scout", "what works", "pick and roll"):
        r = insights.play_type_report(db, team_id)
        best = next((x for x in r["play_types"] if x["play_type"] == r["best"]), None)
        worst = next((x for x in r["play_types"] if x["play_type"] == r["worst"]), None)
        text = (f"{r['possessions']} tagged possessions, {r['overall_ppp']:.2f} points per possession overall.\n"
                + (f"Best: {best['name']} at {best['ppp']:.2f}.\n" if best else "")
                + (f"Worst: {worst['name']} at {worst['ppp']:.2f}. Run it less, or fix it in practice." if worst else ""))
    else:
        text = template_briefing(insights.team_snapshot(db, team_id))
    text += "\n\nThis is the offline assistant: it answers from HoopLab's numbers. Connect Claude for open conversation."
    row = db.one("SELECT * FROM chats WHERE id = ? AND team_id = ?", (chat_id, team_id)) if chat_id else None
    msgs = json.loads(row["messages"]) if row else []
    if not row:
        chat_id = db.insert("chats", {"team_id": team_id, "messages": "[]", "created_at": now_iso(), "updated_at": now_iso()})
    msgs += [{"role": "user", "content": message}, {"role": "assistant", "content": text}]
    db.update("chats", chat_id, {"messages": json.dumps(msgs, ensure_ascii=False), "updated_at": now_iso()})
    return {"chat_id": chat_id, "reply": text, "actions": ag.actions, "stop_reason": "offline"}


def events_from_notes(notes: str, players: list[dict]) -> dict:
    """'Noam 3 of 5 from three', 'Ori had two turnovers', 'Ori did not sprint back twice' -> events."""
    people = {}
    for p in players:
        for t in [p["name"].lower(), *p["name"].lower().split()]:
            if len(t) > 2:
                people.setdefault(t, p["id"])
    names = "|".join(sorted(map(re.escape, people), key=len, reverse=True)) or "$^"
    events, observations, unresolved = [], [], []
    for sent in re.split(r"[.;\n]+", notes):
        s = sent.strip().lower()
        if not s:
            continue
        who = re.search(rf"\b({names})\b", s)
        pid = people[who.group(1)] if who else None
        done = False
        m = re.search(r"(\d+)\s*(?:of|/|out of)\s*(\d+)\s*(?:from\s+|at\s+)?([a-z\-3]+)?", s)
        if m and pid:
            made, att, z = int(m.group(1)), int(m.group(2)), ZONES.get((m.group(3) or "").strip(), "mid")
            if made <= att:
                for k in range(att):
                    events.append({"type": "shot", "player_id": pid, "opponent": False, "outcome": k < made,
                                   "zone": z, "weight": 0.7, "source": "notes"})
                done = True
        m = re.search(r"(\d+|once|twice|one|two|three|four|five)?\s*turnovers?", s)
        if m and pid:
            n = NUM.get(m.group(1) or "", None) or (int(m.group(1)) if (m.group(1) or "").isdigit() else 1)
            events += [{"type": "turnover", "player_id": pid, "opponent": False, "outcome": False, "zone": None,
                        "weight": 0.7, "source": "notes"}] * n
            done = True
        if re.search(r"(did not|didn't|never|late).{0,12}(sprint|get back|got back)", s) and pid:
            m = re.search(r"\b(\d+|once|twice|two|three|four|five)\b\s*(?:times)?", s)
            n = NUM.get(m.group(1), None) or (int(m.group(1)) if m and m.group(1).isdigit() else 1) if m else 1
            events += [{"type": "sprint", "player_id": pid, "opponent": False, "outcome": False, "zone": None,
                        "weight": 0.7, "source": "notes"}] * n
            done = True
        if not done:
            (observations if who is None and len(s) > 20 else unresolved).append(sent.strip())
    return {"events": events, "observations": observations, "unresolved": unresolved}
