"""The assistant coach: a Claude agent that operates HoopLab through tools.

The coach talks to it in plain language ("we play Maccabi on Thursday, 75
minutes tomorrow, 9 players, one hoop", "Noam hit 4 of 6 threes today, Daniel
was late on help three times"). The agent reads the team model, plans,
logs what the coach reports, designs drills that the library lacks, assigns
homework and remembers how this coach likes to work. Numbers come only from
tool results; the deterministic engine stays the source of truth.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from . import ai, insights
from . import drills as dr
from .db import DB, now_iso
from .skills import DIMENSIONS, PLAY_TYPES

DIMS = list(DIMENSIONS)
EVENT_TYPES = ["shot", "turnover", "touch", "creation", "defense", "rotation", "steal", "rebound", "sprint", "assist"]
MAX_STEPS = 10


def _obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required if required is not None else list(props),
            "additionalProperties": False}


TOOLS = [
    {"name": "get_team_snapshot", "description":
        "Current model of the whole team: every player's strengths, weaknesses and weekly focus, team "
        "priorities, strengths to exploit and statistically significant trends. Call this first for any "
        "question about the team.", "input_schema": _obj({})},
    {"name": "get_player", "description":
        "Full profile of one player: all 10 skill estimates with 80% intervals, expected level for the "
        "position, trends and open homework. `name` may be a first name or jersey number.",
     "input_schema": _obj({"name": {"type": "string"}})},
    {"name": "compare_with_opponent", "description":
        "Head-to-head comparison with a scouted opponent and an evidence-backed game plan.",
     "input_schema": _obj({"opponent": {"type": "string"}})},
    {"name": "plan_practice", "description":
        "Build a practice plan that targets the team's measured needs under the given constraints. "
        "Learned coach preferences are applied automatically. Use `opponent` when preparing for a game.",
     "input_schema": _obj({
         "minutes": {"type": "integer"}, "players": {"type": "integer"}, "hoops": {"type": "integer"},
         "max_intensity": {"type": "string", "enum": ["low", "medium", "high"]},
         "focus": {"type": "array", "items": {"type": "string", "enum": DIMS}},
         "opponent": {"type": ["string", "null"]}})},
    {"name": "assign_homework", "description":
        "Assign every player two personal solo assignments for their top needs, due in `days` days.",
     "input_schema": _obj({"days": {"type": "integer"}})},
    {"name": "log_events", "description":
        "Record what the coach reports seeing (game or practice) as events in the skill model. Only log "
        "facts the coach stated; ask instead of guessing counts. Use count for repetitions. Events from the "
        "other team need `opponent` set on the call and player=null.",
     "input_schema": _obj({
         "session_kind": {"type": "string", "enum": ["practice", "game", "scrimmage"]},
         "opponent": {"type": ["string", "null"]},
         "events": {"type": "array", "items": _obj({
             "player": {"type": ["string", "null"]},
             "type": {"type": "string", "enum": EVENT_TYPES},
             "outcome": {"type": ["boolean", "null"]},
             "zone": {"type": ["string", "null"], "enum": ["rim", "mid", "three", "ft", None]},
             "count": {"type": "integer"}})}})},
    {"name": "record_drill_feedback", "description":
        "Store the coach's opinion of a drill (rating -1..1, whether it was run). Shapes future plans.",
     "input_schema": _obj({"drill_id": {"type": "string"}, "rating": {"type": "number"},
                           "ran": {"type": "boolean"}, "note": {"type": ["string", "null"]}})},
    {"name": "set_emphasis", "description":
        "Set the coach's emphasis multipliers per skill (1 = neutral, 2 = twice as important). Affects "
        "priorities, plans and homework.",
     "input_schema": _obj({"weights": {"type": "array", "items": _obj({
         "dimension": {"type": "string", "enum": DIMS}, "weight": {"type": "number"}})}})},
    {"name": "remember_coach_preference", "description":
        "Save a durable fact about how this coach works (philosophy, constraints, likes/dislikes, "
        "schedule). Saved notes are shown to you in every future conversation.",
     "input_schema": _obj({"note": {"type": "string"}})},
    {"name": "list_drills", "description": "List available drills, optionally only those targeting one skill.",
     "input_schema": _obj({"dimension": {"type": ["string", "null"], "enum": DIMS + [None]}})},
    {"name": "design_custom_drill", "description":
        "Add a new drill to this team's library when nothing suitable exists (e.g. a constraint like one "
        "hoop and 5 players, or a specific opponent action). It becomes available to plans and homework.",
     "input_schema": _obj({
         "name": {"type": "string"},
         "targets": {"type": "array", "items": _obj({"dimension": {"type": "string", "enum": DIMS},
                                                      "weight": {"type": "number"}})},
         "minutes": {"type": "integer"}, "min_players": {"type": "integer"}, "hoops": {"type": "integer"},
         "intensity": {"type": "string", "enum": ["low", "medium", "high"]}, "solo": {"type": "boolean"},
         "setup": {"type": "string"}, "cue": {"type": "string"}, "metric": {"type": "string"},
         "tags": {"type": "array", "items": {"type": "string"}}})},
    {"name": "get_play_types", "description":
        "Points per possession (PPP), frequency and turnover rate by play type (pick & roll, spot-up, post-up, "
        "...). Leave both null for our team's self-scout, set `player` for one of our players, or `opponent` "
        "for how a scouted opponent scores. reliable=false means fewer than 5 possessions.",
     "input_schema": _obj({"player": {"type": ["string", "null"]}, "opponent": {"type": ["string", "null"]}})},
    {"name": "build_playlist", "description":
        "Build a video playlist from tagged game film: e.g. one player's missed threes, our pick & roll "
        "possessions, or all of a player's turnovers. Returns the clips with their time windows. Only "
        "events from sessions with video can be clipped.",
     "input_schema": _obj({
         "title": {"type": "string"}, "player": {"type": ["string", "null"]},
         "dimension": {"type": ["string", "null"], "enum": DIMS + [None]},
         "outcome": {"type": ["boolean", "null"], "description": "true = successes, false = misses/mistakes"},
         "play_type": {"type": ["string", "null"], "enum": list(PLAY_TYPES) + [None]}})},
]
for _t in TOOLS:
    _t["strict"] = True

SYSTEM = """You are the assistant coach inside HoopLab, working for the head coach of a basketball team.

How you work:
- Ground every claim in tool results. Quote numbers as the tools give them (e.g. "41% vs 34% expected for a SG")
  and say when evidence is thin; never invent statistics, players or opponents.
- Act, don't just advise: when the coach asks for a plan, homework, or reports what happened, call the tools
  that do it. When a report is ambiguous (who, how many), ask one short question instead of guessing.
- Write like a sharp assistant coach: short, concrete, basketball language. Lead with the answer.
- Reply in the language the coach writes in (Hebrew or English).
- If the drill library lacks what the situation needs, design a custom drill, then use it.
- When the coach states a lasting preference, save it with remember_coach_preference.
- Use play types (get_play_types) to say what works: run more of what scores, fix or drop what doesn't.
- When film exists, back a point with a playlist (build_playlist) so the coach and players can watch it."""


class Agent:
    def __init__(self, db: DB, team_id: int):
        self.db = db
        self.team_id = team_id
        self.actions: list[dict] = []

    # ------------------------------------------------------------- helpers
    def _players(self):
        return self.db.q("SELECT * FROM players WHERE team_id = ?", (self.team_id,))

    def _find_player(self, name: str | None):
        if not name:
            return None
        n = name.strip().lower().lstrip("#")
        for p in self._players():
            if n == str(p["number"]) or n == p["name"].lower() or n in p["name"].lower().split():
                return p
        for p in self._players():
            if n in p["name"].lower():
                return p
        return None

    def _find_opponent(self, name: str | None):
        if not name:
            return None
        rows = self.db.q("SELECT * FROM opponents WHERE team_id = ?", (self.team_id,))
        n = name.lower()
        return next((o for o in rows if n in o["name"].lower() or o["name"].lower() in n), None)

    def system_prompt(self) -> str:
        team = self.db.one("SELECT * FROM teams WHERE id = ?", (self.team_id,))
        memory = self.db.settings(self.team_id).get("coach_memory", [])
        s = SYSTEM + f"\n\nTeam: {team['name']} ({team.get('level') or 'level not set'})."
        if memory:
            s += "\n\nWhat you know about this coach:\n" + "\n".join(f"- {m}" for m in memory)
        return s

    # ------------------------------------------------------------- tools
    def run_tool(self, name: str, args: dict):
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            raise ValueError(f"unknown tool {name}")
        return fn(**args)

    def t_get_team_snapshot(self):
        s = insights.team_snapshot(self.db, self.team_id)
        return {
            "players": [{"name": c["player"]["name"], "number": c["player"]["number"],
                         "position": c["player"]["position"], "events": c["events"],
                         "strengths": [f"{x['name']} {x['mean']:.0%} (exp {x['baseline']:.0%})" for x in c["strengths"]],
                         "weaknesses": [f"{x['name']} {x['mean']:.0%} (exp {x['baseline']:.0%})" for x in c["weaknesses"]],
                         "focus": c["focus"]} for c in s["players"]],
            "priorities": s["priorities"], "exploit": s["exploit"], "trends": s["trends"],
            "data_coverage": s["data_coverage"],
            "opponents": [o["name"] for o in self.db.q("SELECT name FROM opponents WHERE team_id = ?", (self.team_id,))],
        }

    def t_get_player(self, name):
        p = self._find_player(name)
        if not p:
            return {"error": f"no player matching '{name}'", "roster": [x["name"] for x in self._players()]}
        s = insights.team_snapshot(self.db, self.team_id)
        c = next(c for c in s["players"] if c["player"]["id"] == p["id"])
        return {"player": {k: p[k] for k in ("name", "number", "position", "height_cm")}, "events": c["events"],
                "skills": {d: {k: e[k] for k in ("mean", "low", "high", "baseline", "label", "evidence")}
                           for d, e in c["skills"].items()},
                "trends": [t for t in s["trends"] if t["player"] == p["name"]],
                "homework": self.db.q("SELECT drill_id, dimension, status, made, attempts, due FROM homework "
                                      "WHERE player_id = ? ORDER BY id DESC LIMIT 4", (p["id"],))}

    def t_compare_with_opponent(self, opponent):
        o = self._find_opponent(opponent)
        if not o:
            return {"error": f"no scouted opponent matching '{opponent}'",
                    "known": [x["name"] for x in self.db.q("SELECT name FROM opponents WHERE team_id = ?", (self.team_id,))]}
        return insights.matchup(self.db, self.team_id, o["id"])

    def t_get_play_types(self, player, opponent):
        if opponent:
            o = self._find_opponent(opponent)
            if not o:
                return {"error": f"no scouted opponent matching '{opponent}'"}
            return {"opponent": o["name"], **insights.play_type_report(self.db, self.team_id, opponent_id=o["id"])}
        if player:
            p = self._find_player(player)
            if not p:
                return {"error": f"no player matching '{player}'"}
            return {"player": p["name"], **insights.play_type_report(self.db, self.team_id, player_id=p["id"])}
        return {"team": True, **insights.play_type_report(self.db, self.team_id)}

    def t_build_playlist(self, title, player, dimension, outcome, play_type):
        p = self._find_player(player) if player else None
        if player and not p:
            return {"error": f"no player matching '{player}'"}
        pl = insights.build_playlist(self.db, self.team_id, title, p["id"] if p else None, dimension, outcome,
                                     play_type, note="Built by the assistant coach")
        if not pl:
            return {"error": "no clips match: these events have no linked video yet"}
        self.actions.append({"kind": "playlist", "playlist_id": pl["id"]})
        return {"playlist_id": pl["id"], "title": pl["title"], "clips": len(pl["clips"]),
                "first": pl["clips"][:5]}

    def t_plan_practice(self, minutes, players, hoops, max_intensity, focus, opponent):
        o = self._find_opponent(opponent)
        req = dr.PlanRequest(minutes=max(15, min(minutes, 240)), players=max(1, players), hoops=max(0, hoops),
                             max_intensity=max_intensity, focus=focus)
        plan = insights.practice_plan(self.db, self.team_id, req, o["id"] if o else None)
        plan["id"] = self.db.insert("plans", {"team_id": self.team_id, "created_at": now_iso(),
                                              "request": json.dumps(req.__dict__), "plan": json.dumps(plan)})
        self.actions.append({"kind": "plan", "plan_id": plan["id"]})
        return {"plan_id": plan["id"], "opponent": o["name"] if o else None,
                "blocks": [{"minutes": b["minutes"], "drill_id": b["drill"]["id"], "drill": b["drill"]["name"],
                            "why": b["why"], "watch": b["focus_players"], "setup": b["drill"]["setup"],
                            "success": b["drill"]["metric"]} for b in plan["blocks"]],
                "total_minutes": plan["total_minutes"]}

    def t_assign_homework(self, days):
        hw = insights.assign_homework(self.db, self.team_id, max(1, min(days, 30)))
        self.actions.append({"kind": "homework", "count": len(hw)})
        return [{"player": h["player"], "drill": h["drill"]["name"], "target": h["target"],
                 "reason": h["reason"], "due": h["due"]} for h in hw]

    def t_log_events(self, session_kind, opponent, events):
        o = self._find_opponent(opponent) if opponent else None
        if opponent and not o:
            oid = self.db.insert("opponents", {"team_id": self.team_id, "name": opponent, "scouting": "{}"})
            o = {"id": oid, "name": opponent}
        today = datetime.now(timezone.utc).date().isoformat()
        sess = self.db.one("SELECT * FROM sessions WHERE team_id = ? AND kind = ? AND substr(date,1,10) = ? "
                           "AND (opponent_id IS ? OR opponent_id = ?) ORDER BY id DESC",
                           (self.team_id, session_kind, today, o["id"] if o else None, o["id"] if o else None))
        sid = sess["id"] if sess else self.db.insert("sessions", {
            "team_id": self.team_id, "kind": session_kind, "date": now_iso(), "status": "logged by assistant",
            "title": f"{session_kind.title()} (assistant log)", "opponent_id": o["id"] if o else None})
        rows, skipped = [], []
        for e in events:
            is_opp = e["player"] is None
            p = None if is_opp else self._find_player(e["player"])
            if not is_opp and not p:
                skipped.append(f"unknown player '{e['player']}'")
                continue
            if is_opp and not o:
                skipped.append("opponent event without an opponent name")
                continue
            etype, zone = e["type"], e["zone"]
            for _ in range(max(1, min(e["count"], 50))):
                rows.append({"type": etype, "player_id": p["id"] if p else None,
                             "opponent_id": o["id"] if is_opp else None,
                             "outcome": False if etype == "turnover" else e["outcome"], "zone": zone,
                             "weight": 0.7, "source": "assistant"})
        n = self.db.add_events(sid, rows, now_iso(), source="assistant") if rows else 0
        self.actions.append({"kind": "events", "stored": n, "session_id": sid})
        return {"stored": n, "session_id": sid, "skipped": skipped}

    def t_record_drill_feedback(self, drill_id, rating, ran, note):
        if drill_id not in {d.id for d in insights.library(self.db, self.team_id)}:
            return {"error": "unknown drill_id; use list_drills"}
        self.db.insert("drill_feedback", {"team_id": self.team_id, "drill_id": drill_id,
                                          "rating": max(-1.0, min(1.0, rating)), "ran": int(ran), "note": note,
                                          "created_at": now_iso()})
        self.actions.append({"kind": "feedback", "drill_id": drill_id})
        return {"ok": True}

    def t_set_emphasis(self, weights):
        cur = self.db.settings(self.team_id).get("emphasis", {})
        for w in weights:
            cur[w["dimension"]] = max(0.0, min(3.0, w["weight"]))
        self.db.set_setting(self.team_id, "emphasis", cur)
        self.actions.append({"kind": "emphasis"})
        return {"emphasis": cur}

    def t_remember_coach_preference(self, note):
        mem = self.db.settings(self.team_id).get("coach_memory", [])
        if note not in mem:
            mem = (mem + [note.strip()[:300]])[-30:]
            self.db.set_setting(self.team_id, "coach_memory", mem)
        self.actions.append({"kind": "memory"})
        return {"saved": True, "total_notes": len(mem)}

    def t_list_drills(self, dimension):
        lib = insights.library(self.db, self.team_id)
        rows = [d for d in lib if dimension is None or d.targets.get(dimension, 0) >= 0.4]
        return [{"id": d.id, "name": d.name, "targets": d.targets, "minutes": d.minutes, "min_players": d.min_players,
                 "intensity": d.intensity, "solo": d.solo, "custom": "custom" in d.tags} for d in rows]

    def t_design_custom_drill(self, name, targets, minutes, min_players, hoops, intensity, solo, setup, cue,
                              metric, tags):
        did = "custom-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
        drill = {"id": did, "name": name, "targets": {t["dimension"]: max(0.1, min(1.0, t["weight"])) for t in targets},
                 "minutes": max(3, min(minutes, 40)), "min_players": max(1, min_players), "hoops": max(0, hoops),
                 "intensity": intensity, "solo": solo, "setup": setup, "cue": cue, "metric": metric,
                 "tags": [t for t in tags if t][:5]}
        if not drill["targets"]:
            return {"error": "a drill needs at least one target skill"}
        with self.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO custom_drills (id, team_id, drill, created_at) VALUES (?,?,?,?)",
                      (did, self.team_id, json.dumps(drill), now_iso()))
        self.actions.append({"kind": "custom_drill", "drill_id": did})
        return {"drill_id": did, "saved": True}

    # ------------------------------------------------------------- loop
    def chat(self, message: str, chat_id: int | None = None) -> dict:
        client = ai.get_client()
        row = self.db.one("SELECT * FROM chats WHERE id = ? AND team_id = ?", (chat_id, self.team_id)) if chat_id else None
        if not row:
            chat_id = self.db.insert("chats", {"team_id": self.team_id, "messages": "[]",
                                               "created_at": now_iso(), "updated_at": now_iso()})
            messages = []
        else:
            messages = json.loads(row["messages"])
        messages.append({"role": "user", "content": message})
        reply, stop = "", None
        for _ in range(MAX_STEPS):
            resp = client.beta.messages.create(
                model=ai.MODEL, max_tokens=16000, system=self.system_prompt(), tools=TOOLS,
                output_config={"effort": ai.EFFORT}, messages=messages, **ai.FALLBACK_KW)
            stop = resp.stop_reason
            messages.append({"role": "assistant", "content": [ai.dump_block(b) for b in resp.content]})
            if stop == "pause_turn":
                continue
            if stop != "tool_use":
                reply = ai.text_of(resp)
                break
            results = []
            for b in resp.content:
                if getattr(b, "type", "") != "tool_use":
                    continue
                try:
                    out = self.run_tool(b.name, dict(b.input))
                    results.append({"type": "tool_result", "tool_use_id": b.id,
                                    "content": json.dumps(out, ensure_ascii=False, default=str)})
                except Exception as exc:  # tool errors go back to the model, not the coach
                    results.append({"type": "tool_result", "tool_use_id": b.id,
                                    "content": f"Error: {exc}", "is_error": True})
            messages.append({"role": "user", "content": results})
        else:
            reply = "I stopped after too many steps; please narrow the request."
        if stop == "refusal" and not reply:
            reply = "I can't help with that request."
        self.db.update("chats", chat_id, {"messages": json.dumps(messages, ensure_ascii=False),
                                          "updated_at": now_iso()})
        return {"chat_id": chat_id, "reply": reply, "actions": self.actions, "stop_reason": stop}


def history(db: DB, team_id: int, chat_id: int) -> list[dict]:
    """User-visible transcript (text only) of a stored conversation."""
    row = db.one("SELECT messages FROM chats WHERE id = ? AND team_id = ?", (chat_id, team_id))
    out = []
    for m in json.loads(row["messages"]) if row else []:
        if isinstance(m["content"], str):
            out.append({"role": m["role"], "text": m["content"]})
        elif m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in m["content"] if b.get("type") == "text").strip()
            if text and out and out[-1]["role"] == "assistant":
                out[-1]["text"] += "\n\n" + text      # several steps of one turn -> one bubble
            elif text:
                out.append({"role": "assistant", "text": text})
    return out
