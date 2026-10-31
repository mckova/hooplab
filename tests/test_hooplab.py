import io
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from hooplab import drills as dr
from hooplab import insights
from hooplab.db import DB
from hooplab.seed import ROSTER, seed
from hooplab.skills import BASELINE, build_profile
from hooplab.vision import geometry as g
from hooplab.vision.analysis import AnalysisConfig, TrackSet, analyze, possession
from hooplab.vision.synth import Scene, demo_possessions


# ------------------------------------------------------------------ geometry
def test_homography_recovers_court_points():
    img = [(100, 100), (1220, 100), (1220, 700), (100, 700)]
    court = [(0, 0), (28, 0), (28, 15), (0, 15)]
    h = g.homography(img, court)
    x, y = g.project(h, (660, 400))
    assert abs(x - 14) < 1e-6 and abs(y - 7.5) < 1e-6


def test_court_zones():
    assert g.court_zone((26.0, 7.5)) == "rim"
    assert g.court_zone((23.0, 7.5)) == "mid"
    assert g.court_zone((19.0, 13.0)) == "three"


# ------------------------------------------------------------------ video analysis
@pytest.fixture(scope="module")
def demo_analysis():
    return analyze(TrackSet.from_json(demo_possessions({"1": 1, "2": 2, "3": 3, "4": 4, "5": 5})))


def test_pipeline_detects_the_scripted_sequence(demo_analysis):
    ev = demo_analysis["events"]
    kinds = [(e["type"], e.get("track"), e.get("outcome")) for e in ev if e["type"] != "sprint"]
    assert ("pass", "1", True) in kinds and ("pass", "2", True) in kinds
    shots = [e for e in ev if e["type"] == "shot"]
    assert [(s["track"], s["outcome"], s["zone"]) for s in shots] == [("3", True, "three"), ("4", False, "mid")]
    # the pass right before the made three is the assist
    assert next(e for e in ev if e["type"] == "pass" and e["to_track"] == "3").get("assist") is True
    # defensive rebound after the miss + the lost board charged to a team-1 player
    rb = [e for e in ev if e["type"] == "rebound"]
    assert rb[0]["track"] == "15" and rb[0]["outcome"] and not rb[0]["offensive"]
    assert rb[1]["outcome"] is False and rb[1]["track"] in {"1", "2", "3", "4", "5"}
    # steal by 1 = turnover by 11
    assert ("turnover", "11", False) in kinds and ("steal", "1", True) in kinds


def test_no_pass_or_turnover_across_a_shot(demo_analysis):
    ev = demo_analysis["events"]
    # 4 shoots, 15 rebounds: must not be counted as a turnover by 4
    assert not any(e["type"] == "turnover" and e["track"] == "4" for e in ev)


def test_sprint_back_classification(demo_analysis):
    sprint = {e["track"]: e["outcome"] for e in demo_analysis["events"] if e["type"] == "sprint"}
    assert sprint["12"] and sprint["13"] and not sprint["14"] and not sprint["15"]
    assert demo_analysis["movement"]["12"]["top_speed_kmh"] > 10


def test_ball_flying_over_a_player_is_not_possession():
    s = Scene({"1": {"team": 1, "pos": (19, 13)}, "2": {"team": 1, "pos": (24, 4)},
               "9": {"team": 2, "pos": (10, 7)}})
    s.hold(1, 0.8)
    s.shoot(1, made=True)
    holders = possession(TrackSet.from_json(s.to_json()), AnalysisConfig())
    assert "2" not in set(holders)


def test_debounce_ignores_brief_touches():
    frames = []
    for i in range(30):
        owner = "2" if 10 <= i < 12 else "1"     # 2-frame flicker to player 2
        box1, box2 = [0, 0, 30, 80], [100, 0, 130, 80]
        ball = [10, 30, 20, 40] if owner == "1" else [110, 30, 120, 40]
        frames.append({"players": {"1": {"bbox": box1, "team": 1}, "2": {"bbox": box2, "team": 1}}, "ball": ball})
    ts = TrackSet(frames=frames)
    holders = possession(ts, AnalysisConfig(max_relative_ball_speed=99))
    assert "2" not in set(holders)


# ------------------------------------------------------------------ skill model
def test_prior_dominates_with_no_data_and_data_dominates_with_lots():
    empty = build_profile(1, "C", [])
    assert empty.estimates["three_point"].mean == pytest.approx(BASELINE["C"]["three_point"])
    assert empty.estimates["three_point"].label == "neutral"
    hot = [{"type": "shot", "zone": "three", "outcome": i % 2 == 0} for i in range(400)]
    p = build_profile(1, "C", hot)
    assert p.estimates["three_point"].mean == pytest.approx(0.5, abs=0.02)
    assert p.estimates["three_point"].label == "strength"


def test_recent_evidence_counts_more():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    old = (now - timedelta(days=120)).isoformat()
    new = (now - timedelta(days=1)).isoformat()
    evs = [{"type": "shot", "zone": "ft", "outcome": False, "occurred_at": old} for _ in range(60)]
    evs += [{"type": "shot", "zone": "ft", "outcome": True, "occurred_at": new} for _ in range(30)]
    decayed = build_profile(1, "PG", evs, now=now, half_life_days=30).estimates["free_throw"].mean
    flat = build_profile(1, "PG", evs, now=now, half_life_days=0).estimates["free_throw"].mean
    assert decayed > 0.7 > flat


# ------------------------------------------------------------------ insights on the demo team
@pytest.fixture(scope="module")
def demo_db():
    path = tempfile.mktemp(suffix=".db")
    db = DB(path)
    tid = seed(db)
    yield db, tid
    os.remove(path)


def test_model_recovers_hidden_traits(demo_db):
    db, tid = demo_db
    snap = insights.team_snapshot(db, tid)
    truth = db.settings(tid)["truth"]
    overrides = {i + 1: o for i, (*_, o) in enumerate(ROSTER)}
    err_model, err_prior = [], []
    for c in snap["players"]:
        pid = c["player"]["id"]
        for dim in overrides[pid]:
            err_model.append(abs(c["skills"][dim]["mean"] - truth[str(pid)][dim]))
            err_prior.append(abs(c["skills"][dim]["baseline"] - truth[str(pid)][dim]))
    assert sum(err_model) / len(err_model) < 0.6 * sum(err_prior) / len(err_prior)


def test_snapshot_finds_injected_improvement(demo_db):
    db, tid = demo_db
    snap = insights.team_snapshot(db, tid)
    found = {(t["player"], t["dimension"]) for t in snap["trends"]}
    assert ("Noam Levi", "ball_security") in found
    assert all(abs(t["z"]) >= 2.8 for t in snap["trends"])


def test_matchup_game_plan_uses_scouting(demo_db):
    db, tid = demo_db
    m = insights.matchup(db, tid, 1)
    text = " ".join(g_["insight"] for g_ in m["game_plan"])
    assert "glass" in text                     # Maccabi North can't rebound
    assert "free-throw" in text                # from manual scouting rating
    assert {r["dimension"] for r in m["comparison"]} >= {"rebounding", "free_throw"}


def test_practice_plan_respects_constraints(demo_db):
    db, tid = demo_db
    plan = insights.practice_plan(db, tid, dr.PlanRequest(minutes=60, players=6, hoops=1, max_intensity="medium"))
    assert plan["total_minutes"] <= 60
    for b in plan["blocks"]:
        d = dr.BY_ID[b["drill"]["id"]]
        assert d.min_players <= 6 and d.intensity in ("low", "medium") and d.hoops <= 1
    assert len({b["drill"]["id"] for b in plan["blocks"]}) == len(plan["blocks"])


def test_coach_feedback_shifts_recommendations():
    need = {"rebounding": 0.2, "help_defense": 0.05}
    req = dr.PlanRequest(minutes=30, players=10, include_warmup=False)
    before = [b["drill"]["id"] for b in dr.plan_practice(need, req)["blocks"]]
    fb = [{"drill_id": before[0], "rating": -1, "ran": False}] * 3
    after = [b["drill"]["id"] for b in dr.plan_practice(need, req, dr.preference_weights(fb))["blocks"]]
    assert after[0] != before[0]


def test_homework_targets_needs_and_logs_results(demo_db):
    db, tid = demo_db
    hw = insights.assign_homework(db, tid)
    assert hw and all(dr.BY_ID[h["drill"]["id"]].solo for h in hw)
    assert len({h["player_id"] for h in hw}) >= 6
    shot_hw = next((h for h in hw if h["dimension"] in ("three_point", "free_throw", "midrange", "rim_finishing")), None)
    if shot_hw:
        before = len(db.player_events(shot_hw["player_id"]))
        insights.complete_homework(db, shot_hw["id"], 30, 50)
        evs = db.player_events(shot_hw["player_id"])
        assert len(evs) == before + 50 and evs[-1]["weight"] == pytest.approx(0.3)


# ------------------------------------------------------------------ API
@pytest.fixture(scope="module")
def client():
    os.environ["HOOPLAB_DATA"] = tempfile.mkdtemp()
    os.environ.pop("HOOPLAB_DB", None)
    from fastapi.testclient import TestClient
    import importlib
    import hooplab.api as api
    importlib.reload(api)
    return TestClient(api.app)


def test_api_end_to_end(client):
    team = client.post("/api/teams", json={"name": "Test U16"}).json()
    tid = team["id"]
    pids = [client.post(f"/api/teams/{tid}/players", json={"name": f"P{i}", "number": i, "position": pos}).json()["id"]
            for i, pos in enumerate(["PG", "SG", "SF", "PF", "C"], start=1)]
    opp = client.get(f"/api/teams/{tid}/opponents").json()
    assert opp == []
    oid = client.post(f"/api/teams/{tid}/opponents", json={"name": "Rivals"}).json()["opponent"]["id"]
    sid = client.post(f"/api/teams/{tid}/sessions", json={"kind": "game", "opponent_id": oid}).json()["id"]

    tracks = demo_possessions({str(i): pid for i, pid in enumerate(pids, start=1)})
    r = client.post(f"/api/sessions/{sid}/tracks", json={"tracks": tracks, "our_team": 1}).json()
    assert r["events_detected"] > 10 and r["events_stored"] > 10

    csv_body = "player_number,type,outcome,zone,assist,opponent\n1,shot,1,three,0,0\n,rebound,0,,0,1\n"
    r = client.post(f"/api/sessions/{sid}/events.csv", files={"file": ("e.csv", io.BytesIO(csv_body.encode()), "text/csv")})
    assert r.status_code == 201 and r.json()["stored"] == 2

    bad = client.post(f"/api/sessions/{sid}/events", json=[{"type": "shot", "player_id": 9999, "outcome": True}])
    assert bad.status_code == 422

    snap = client.get(f"/api/teams/{tid}/snapshot").json()
    assert len(snap["players"]) == 5
    assert client.get(f"/api/teams/{tid}/briefing").json()["text"]
    plan = client.post(f"/api/teams/{tid}/plan", json={"minutes": 45, "players": 5, "hoops": 1}).json()
    assert plan["blocks"] and plan["total_minutes"] <= 45
    fb = client.post(f"/api/teams/{tid}/feedback", json={"drill_id": plan["blocks"][1]["drill"]["id"], "rating": 1, "ran": True})
    assert fb.status_code == 201
    hw = client.post(f"/api/teams/{tid}/homework/assign").json()
    assert isinstance(hw, list)
    m = client.get(f"/api/opponents/{oid}/matchup").json()
    assert m["opponent"]["name"] == "Rivals"
    assert client.put(f"/api/teams/{tid}/settings", json={"emphasis": {"bogus": 2}}).status_code == 422
    assert client.put(f"/api/teams/{tid}/settings", json={"emphasis": {"rebounding": 2}}).json()["emphasis"]


def test_video_upload_without_vision_extra_is_stored_not_failed(client):
    tid = client.post("/api/teams", json={"name": "V"}).json()["id"]
    sid = client.post(f"/api/teams/{tid}/sessions", json={"kind": "practice"}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/video", files={"file": ("clip.mp4", io.BytesIO(b"\x00" * 64), "video/mp4")})
    assert r.status_code == 202
    from hooplab.vision.backends import vision_available
    if not vision_available():
        assert r.json()["status"] == "stored"
