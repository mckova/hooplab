"""AI-native features, tested against a scripted stand-in for the Claude client
(the real calls need credentials; the contract with the SDK is what we test)."""
import copy
import json
import os
import tempfile
from types import SimpleNamespace as NS

import pytest

from hooplab import agent as ag
from hooplab import ai, insights, perception
from hooplab.db import DB
from hooplab.seed import seed


class Block(NS):
    def model_dump(self, **_):
        return {k: v for k, v in vars(self).items()}


def text(t):
    return Block(type="text", text=t)


def tool(id_, tool_name, **inp):
    return Block(type="tool_use", id=id_, name=tool_name, input=inp)


class FakeMessages:
    def __init__(self, script=None, parsed=None):
        self.script = list(script or [])
        self.parsed = parsed
        self.calls = []

    def create(self, **kw):
        self.calls.append(copy.deepcopy(kw))
        content, stop = self.script.pop(0)
        return NS(content=content, stop_reason=stop, model=kw["model"])

    def parse(self, **kw):
        self.calls.append(kw)
        return NS(parsed_output=self.parsed, stop_reason="end_turn")


def fake_client(**kw):
    m = FakeMessages(**kw)
    return NS(beta=NS(messages=m)), m


@pytest.fixture()
def demo():
    path = tempfile.mktemp(suffix=".db")
    db = DB(path)
    tid = seed(db, weeks=4)
    yield db, tid
    ai.set_client(None)
    os.remove(path)


def test_tool_schemas_are_strict_and_complete():
    for t in ag.TOOLS:
        assert t["strict"] is True
        sch = t["input_schema"]
        assert sch["additionalProperties"] is False and set(sch["required"]) == set(sch["properties"])
        assert hasattr(ag.Agent, f"t_{t['name']}")


def test_agent_plans_with_tools_and_keeps_history(demo):
    db, tid = demo
    client, msgs = fake_client(script=[
        ([text("Let me check the team."), tool("t1", "get_team_snapshot"),
          tool("t2", "plan_practice", minutes=60, players=8, hoops=1, max_intensity="medium",
               focus=["rebounding"], opponent="Maccabi")], "tool_use"),
        ([text("Plan is ready: 60 minutes focused on the glass.")], "end_turn"),
    ])
    ai.set_client(client)
    r = ag.Agent(db, tid).chat("Plan tomorrow vs Maccabi, 60 min, 8 players, 1 hoop")
    assert r["reply"].startswith("Plan is ready")
    assert [a["kind"] for a in r["actions"]] == ["plan"]
    # request contract: latest model, effort, strict tools, refusal fallback, stable system prompt
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_config"] == {"effort": "medium"}
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    # stable instructions cached (with the tools ahead of them), team context after the breakpoint
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"} and "Hapoel Demo U18" in call["system"][1]["text"]
    assert call["cache_control"] == {"type": "ephemeral"}
    # tool results went back in one user message, matched by id
    results = msgs.calls[1]["messages"][-1]["content"]
    assert [x["tool_use_id"] for x in results] == ["t1", "t2"]
    plan = json.loads(results[1]["content"])
    assert plan["opponent"] == "Maccabi North U18" and plan["total_minutes"] <= 60
    # conversation is stored append-only and continues
    client2, msgs2 = fake_client(script=[([text("Sure.")], "end_turn")])
    ai.set_client(client2)
    ag.Agent(db, tid).chat("thanks", r["chat_id"])
    sent = msgs2.calls[0]["messages"]
    assert sent[0]["content"].startswith("Plan tomorrow") and sent[-1]["content"] == "thanks"
    assert [m["role"] for m in ag.history(db, tid, r["chat_id"])] == ["user", "assistant", "user", "assistant"]


def test_agent_logs_events_remembers_and_designs_drills(demo):
    db, tid = demo
    a = ag.Agent(db, tid)
    before = len(db.player_events(1))
    out = a.run_tool("log_events", {"session_kind": "practice", "opponent": None, "events": [
        {"player": "Noam", "type": "shot", "outcome": True, "zone": "three", "count": 4},
        {"player": "Noam", "type": "shot", "outcome": False, "zone": "three", "count": 2},
        {"player": "Ghost", "type": "turnover", "outcome": None, "zone": None, "count": 1}]})
    assert out["stored"] == 6 and out["skipped"] == ["unknown player 'Ghost'"]
    assert len(db.player_events(1)) == before + 6
    a.run_tool("remember_coach_preference", {"note": "Hates conditioning without a ball"})
    assert "Hates conditioning without a ball" in a.system_prompt()
    d = a.run_tool("design_custom_drill", {
        "name": "One-hoop rebound war", "targets": [{"dimension": "rebounding", "weight": 1.0}], "minutes": 10,
        "min_players": 4, "hoops": 1, "intensity": "high", "solo": False, "setup": "3v3 on one hoop",
        "cue": "Hit first", "metric": "Defense wins 7/10", "tags": ["rebounding"]})
    assert any(x.id == d["drill_id"] for x in insights.library(db, tid))
    assert any(x["id"] == d["drill_id"] for x in a.run_tool("list_drills", {"dimension": "rebounding"}))


def test_unknown_player_and_tool_errors_are_returned_to_model(demo):
    db, tid = demo
    client, msgs = fake_client(script=[
        ([tool("x", "get_player", name="Kobe")], "tool_use"),
        ([text("There is no Kobe on your roster.")], "end_turn")])
    ai.set_client(client)
    r = ag.Agent(db, tid).chat("How is Kobe doing?")
    res = json.loads(msgs.calls[1]["messages"][-1]["content"][0]["content"])
    assert "error" in res and "Noam Levi" in res["roster"]
    assert "Kobe" in r["reply"]


def test_notes_extraction_maps_roster_and_counts(demo):
    db, tid = demo
    ex = perception.Extraction(events=[
        perception.ExtractedEvent(player_number=3, player_name=None, opponent=False, type="shot", outcome=True,
                                  zone="three", count=3, evidence="Noam 3/5"),
        perception.ExtractedEvent(player_number=None, player_name="Daniel", opponent=False, type="rotation",
                                  outcome=False, zone=None, count=2, evidence="late help x2"),
        perception.ExtractedEvent(player_number=None, player_name=None, opponent=True, type="rebound",
                                  outcome=True, zone=None, count=1, evidence="their #12 boards"),
        perception.ExtractedEvent(player_number=99, player_name="Unknown", opponent=False, type="steal",
                                  outcome=True, zone=None, count=1, evidence="?"),
    ], observations=["Their #12 dominates the offensive glass"], unresolved=[])
    client, msgs = fake_client(parsed=ex)
    ai.set_client(client)
    players = db.q("SELECT * FROM players WHERE team_id = ?", (tid,))
    r = perception.events_from_notes("Noam 3/5 from three...", players, "Maccabi North U18")
    kinds = [(e["type"], e["player_id"], e["opponent"]) for e in r["events"]]
    assert kinds.count(("shot", 1, False)) == 3 and kinds.count(("rotation", 5, False)) == 2
    assert ("rebound", None, True) in kinds and all(e["weight"] == 0.7 for e in r["events"])
    assert r["unresolved"] and r["observations"]
    assert msgs.calls[0]["output_format"] is perception.Extraction


def test_api_reports_ai_unavailable_cleanly(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    ai.set_client(None)
    os.environ["HOOPLAB_DATA"] = tempfile.mkdtemp()
    import importlib

    from fastapi.testclient import TestClient

    import hooplab.api as api
    importlib.reload(api)
    c = TestClient(api.app)
    tid = c.post("/api/teams", json={"name": "T"}).json()["id"]
    r = c.post(f"/api/teams/{tid}/chat", json={"message": "hi"})     # no key: the offline assistant answers
    assert r.status_code == 200 and r.json()["stop_reason"] == "offline" and "offline assistant" in r.json()["reply"]
    assert c.get("/api/health").json()["ai"] is False
    assert c.get(f"/api/teams/{tid}/briefing").json()["source"] == "template"


def test_agent_self_scout_and_playlist_tools(demo):
    db, tid = demo
    a = ag.Agent(db, tid)
    r = a.run_tool("get_play_types", {"player": None, "opponent": None})
    assert r["team"] and r["play_types"]
    r = a.run_tool("get_play_types", {"player": None, "opponent": "maccabi"})
    assert r["opponent"].startswith("Maccabi")
    r = a.run_tool("build_playlist", {"title": "t", "player": "Noam", "dimension": None, "outcome": None,
                                      "play_type": None})
    assert "error" in r   # no film in this seed: the tool says so instead of inventing clips
    names = {t["name"] for t in ag.TOOLS}
    assert {"get_play_types", "build_playlist"} <= names


def test_offline_assistant_and_notes_work_without_a_key(demo):
    from hooplab import offline
    db, tid = demo
    r = offline.reply(db, tid, "Plan tomorrow: 60 minutes, half court", None, None)
    assert "Practice plan, " in r["reply"] and r["chat_id"]
    r2 = offline.reply(db, tid, "How is Noam doing?", r["chat_id"], None)
    assert "Noam Levi" in r2["reply"] and r2["chat_id"] == r["chat_id"]
    assert [m["role"] for m in ag.history(db, tid, r["chat_id"])] == ["user", "assistant", "user", "assistant"]
    assert "homework" in offline.reply(db, tid, "assign homework", None, None)["reply"].lower()
    players = db.q("SELECT * FROM players WHERE team_id = ?", (tid,))
    out = offline.events_from_notes("Noam 3 of 5 from three. Ori had two turnovers. Ori did not sprint back twice.", players)
    kinds = [(e["type"], e["outcome"]) for e in out["events"]]
    assert kinds.count(("shot", True)) == 3 and kinds.count(("shot", False)) == 2
    assert kinds.count(("turnover", False)) == 2 and kinds.count(("sprint", False)) == 2
