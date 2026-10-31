"""The coaching loop around the model: debriefs, inbox, progress, player messages,
roster import, practice conditions and the assistant's screen context."""
import copy
import io
import os
import tempfile
from types import SimpleNamespace as NS

import pytest

from hooplab import agent as ag
from hooplab import ai, coach_ai, insights
from hooplab import drills as dr
from hooplab.db import DB
from hooplab.seed import seed


@pytest.fixture(scope="module")
def demo():
    path = tempfile.mktemp(suffix=".db")
    db = DB(path)
    tid = seed(db)
    yield db, tid
    ai.set_client(None)
    os.remove(path)


def _last_game(db, tid):
    return db.one("SELECT * FROM sessions WHERE team_id = ? AND kind = 'game' ORDER BY date DESC", (tid,))


def test_session_report_flags_players_against_their_own_expectation(demo):
    db, tid = demo
    r = coach_ai.session_report(db, _last_game(db, tid)["id"])
    assert r["players"] and r["team"]["shooting"]
    for s in r["standouts"]:
        assert s["n"] >= coach_ai.STANDOUT_MIN_N and abs(s["z"]) >= coach_ai.STANDOUT_Z
        assert 0 < s["expected"] < 1     # expectation comes from the model *before* this session


def test_debrief_goes_to_inbox_and_template_quotes_report_numbers(demo):
    db, tid = demo
    sid = _last_game(db, tid)["id"]
    d = coach_ai.debrief(db, sid, use_ai=False)
    assert d["source"] == "template"
    for s in d["report"]["standouts"][:3]:
        assert f"{s['made']}/{s['n']}" in d["text"]
    kinds = [i["kind"] for i in coach_ai.inbox(db, tid, insights.team_snapshot(db, tid))]
    assert "debrief" in kinds and "trend" in kinds


def test_debrief_uses_claude_when_available(demo):
    db, tid = demo
    calls = []

    def create(**kw):
        calls.append(kw)
        return NS(content=[NS(type="text", text="Great energy. Noam 12/12 ball security.")],
                  stop_reason="end_turn", model=kw["model"])
    ai.set_client(NS(beta=NS(messages=NS(create=create))))
    try:
        d = coach_ai.debrief(db, _last_game(db, tid)["id"], language="he")
    finally:
        ai.set_client(None)
    assert d["source"] == "claude-opus-5-5" and d["text"].startswith("Great energy")
    prompt = calls[0]["messages"][0]["content"]
    assert "Hebrew" in prompt and "<session_report>" in prompt and calls[0]["fallbacks"] == "default"


def test_progress_series_and_player_message(demo):
    db, tid = demo
    snap = insights.team_snapshot(db, tid)
    noam = next(c for c in snap["players"] if c["player"]["name"] == "Noam Levi")
    h = coach_ai.player_history(db, noam["player"]["id"])
    bs = h["series"]["ball_security"]
    assert len(bs) == 10 and bs[-1] > bs[0]           # the injected improvement shows over time
    insights.assign_homework(db, tid)
    m = coach_ai.player_message(db, noam, use_ai=False, trends=snap["trends"])
    assert m["text"].startswith("Hi Noam") and "Ball security" in [t["skill"] for t in m["facts"]["significant_trends"]]
    assert all(h["drill"] in m["text"] for h in m["facts"]["homework"])


def test_half_court_plan_has_no_full_court_drills(demo):
    db, tid = demo
    plan = insights.practice_plan(db, tid, dr.PlanRequest(minutes=90, players=12, hoops=2, full_court=False))
    ids = {b["drill"]["id"] for b in plan["blocks"]}
    assert ids and not ids & dr.FULL_COURT


def test_agent_screen_context_and_new_tools(demo):
    db, tid = demo
    a = ag.Agent(db, tid)
    assert a.run_tool("get_session_report", {"session": None})["players"]
    assert a.run_tool("get_progress", {"name": "Noam"})["series"]
    assert isinstance(a.run_tool("get_inbox", {}), list)
    sent = []

    def create(**kw):
        sent.append(copy.deepcopy(kw))
        return NS(content=[NS(type="text", text="He is improving.", model_dump=lambda **_: {"type": "text", "text": "He is improving."})],
                  stop_reason="end_turn", model=kw["model"])
    ai.set_client(NS(beta=NS(messages=NS(create=create))))
    try:
        r = a.chat("Is he getting better?", context="Player card: Noam Levi (#3, PG)")
    finally:
        ai.set_client(None)
    first = sent[0]["messages"][-1]["content"]
    assert "Noam Levi" in first[0]["text"] and first[1]["text"] == "Is he getting better?"
    assert ag.history(db, tid, r["chat_id"])[0] == {"role": "user", "text": "Is he getting better?"}


@pytest.fixture(scope="module")
def client():
    os.environ["HOOPLAB_DATA"] = tempfile.mkdtemp()
    os.environ.pop("HOOPLAB_DB", None)
    import importlib

    from fastapi.testclient import TestClient

    import hooplab.api as api
    importlib.reload(api)
    return TestClient(api.app)


def test_api_roster_import_inbox_and_auto_debrief(client):
    tid = client.post("/api/teams", json={"name": "Import U14"}).json()["id"]
    csv = b"name,number,position,height_cm\nA One,1,pg,170\nB Two,2,C,190\n"
    assert client.post(f"/api/teams/{tid}/players.csv", files={"file": ("r.csv", io.BytesIO(csv))}).json() == \
        {"added": 2, "updated": 0}
    again = b"name,number,position\nA One Jr,1,SG\n"
    assert client.post(f"/api/teams/{tid}/players.csv", files={"file": ("r.csv", io.BytesIO(again))}).json()["updated"] == 1
    bad = b"name,number,position\nX,3,QB\n"
    assert client.post(f"/api/teams/{tid}/players.csv", files={"file": ("r.csv", io.BytesIO(bad))}).status_code == 422
    sid = client.post(f"/api/teams/{tid}/sessions", json={"kind": "game", "title": "Opener"}).json()["id"]
    ev = b"player_number,type,outcome,zone\n" + b"1,shot,1,three\n" * 5 + b"2,turnover,0,\n"
    client.post(f"/api/sessions/{sid}/events.csv", files={"file": ("e.csv", io.BytesIO(ev))})
    inbox = client.get(f"/api/teams/{tid}/inbox").json()
    assert inbox[0]["kind"] == "debrief" and "Opener" in inbox[0]["title"]   # posted automatically after import
    pid = client.get(f"/api/teams/{tid}/players").json()[0]["id"]
    assert len(client.get(f"/api/players/{pid}/history?weeks=4").json()["dates"]) == 4
    assert client.get(f"/api/players/{pid}/message").json()["source"] == "template"
    assert client.put(f"/api/teams/{tid}/settings", json={"language": "he"}).json()["language"] == "he"


def test_parallel_requests_share_the_database_safely(client):
    """The UI loads several panels at once; the shared SQLite connection must serialise them."""
    from concurrent.futures import ThreadPoolExecutor
    tid = client.post("/api/demo").json()["team_id"]
    urls = [f"/api/teams/{tid}/snapshot", f"/api/teams/{tid}/inbox", f"/api/teams/{tid}/play-types",
            f"/api/teams/{tid}/briefing"] * 3
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda u: client.get(u).status_code, urls))
    assert codes == [200] * len(urls)
