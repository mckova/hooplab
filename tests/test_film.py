"""Film features: play types and points per possession, clip windows, playlists,
the shared ingest path, the rendered demo film and the scouting report."""
import os
import shutil
import sqlite3
import tempfile

import pytest

from hooplab import insights, llm
from hooplab.db import DB
from hooplab.ingest import ingest_tracks
from hooplab.seed import seed
from hooplab.skills import possession_points
from hooplab.vision.analysis import TrackSet, analyze
from hooplab.vision.synth import demo_film

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_possession_points():
    assert possession_points({"type": "shot", "zone": "three", "outcome": True}) == 3
    assert possession_points({"type": "shot", "zone": "rim", "outcome": True}) == 2
    assert possession_points({"type": "shot", "zone": "mid", "outcome": False}) == 0
    assert possession_points({"type": "turnover"}) == 0
    assert possession_points({"type": "shot", "zone": "ft", "outcome": True}) is None
    assert possession_points({"type": "pass", "outcome": True}) is None


def test_demo_film_events_carry_play_types_and_clip_windows():
    events = analyze(TrackSet.from_json(demo_film({str(i): i for i in range(1, 6)})))["events"]
    shots = [e for e in events if e["type"] == "shot"]
    assert {e["play_type"] for e in shots} >= {"pick_and_roll", "spot_up", "cut", "post_up"}
    assert all(0 <= e["t_start"] < e["t_end"] for e in events)
    tos = [e for e in events if e["type"] == "turnover"]
    assert len(tos) == 1 and tos[0]["play_type"] == "isolation"   # no fake turnovers across dead balls


def _db():
    path = tempfile.mktemp(suffix=".db")
    return DB(path), path


def test_play_type_report_counts_ppp():
    db, path = _db()
    tid = db.insert("teams", {"name": "T", "created_at": "2026-01-01"})
    pid = db.insert("players", {"team_id": tid, "name": "A", "number": 1, "position": "PG"})
    sid = db.insert("sessions", {"team_id": tid, "kind": "game", "date": "2026-01-01T00:00:00"})
    evs = ([{"type": "shot", "zone": "three", "outcome": True, "play_type": "spot_up"}] * 2
           + [{"type": "shot", "zone": "three", "outcome": False, "play_type": "spot_up"}] * 3
           + [{"type": "turnover", "outcome": False, "play_type": "isolation"}] * 5
           + [{"type": "shot", "zone": "ft", "outcome": True, "play_type": "isolation"}])  # FT: not a possession
    db.add_events(sid, [{**e, "player_id": pid} for e in evs], "2026-01-01T00:00:00")
    r = insights.play_type_report(db, tid)
    by = {x["play_type"]: x for x in r["play_types"]}
    assert by["spot_up"]["ppp"] == pytest.approx(6 / 5) and by["isolation"]["ppp"] == 0
    assert by["isolation"]["turnover_rate"] == 1 and r["possessions"] == 10
    assert r["best"] == "spot_up" and r["worst"] == "isolation"
    assert r["overall_ppp"] == pytest.approx(0.6)
    os.remove(path)


def test_migration_adds_film_columns_to_old_databases():
    path = tempfile.mktemp(suffix=".db")
    DB(path).conn.close()
    c = sqlite3.connect(path)          # turn it into a pre-film database
    for col in ("play_type", "t_start", "t_end"):
        c.execute(f"ALTER TABLE events DROP COLUMN {col}")
    c.execute("ALTER TABLE homework DROP COLUMN playlist_id")
    c.commit()
    c.close()
    db = DB(path)
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(events)")}
    assert {"play_type", "t_start", "t_end"} <= cols
    assert "playlist_id" in {r["name"] for r in db.conn.execute("PRAGMA table_info(homework)")}
    os.remove(path)


def test_ingest_stores_clip_windows_and_playlists_need_video():
    db, path = _db()
    tid = seed(db, weeks=2)
    pids = [p["id"] for p in db.q("SELECT id FROM players WHERE team_id = ? ORDER BY id", (tid,))]
    opp = db.q("SELECT id FROM opponents WHERE team_id = ?", (tid,))[0]["id"]
    sid = db.insert("sessions", {"team_id": tid, "kind": "game", "date": "2026-10-01T00:00:00", "opponent_id": opp})
    s = db.one("SELECT * FROM sessions WHERE id = ?", (sid,))
    summary = ingest_tracks(db, s, demo_film({str(i + 1): pids[i] for i in range(5)}))
    assert summary["events_stored"] > 10
    rows = db.q("SELECT * FROM events WHERE session_id = ?", (sid,))
    assert all(r["t_start"] is not None for r in rows)
    assert any(r["opponent_id"] == opp for r in rows)                       # opponent events kept for scouting
    assert insights.clips(db, tid) == []                                    # no video linked yet
    db.update("sessions", sid, {"video_path": "/tmp/x.mp4"})
    noam_tos = insights.clips(db, tid, player_id=pids[0], dimension="ball_security", outcome=False)
    assert len(noam_tos) == 1 and noam_tos[0]["play_type"] == "isolation"
    pl = insights.build_playlist(db, tid, "PnR", play_type="pick_and_roll")
    assert pl and all(c["play_type"] == "pick_and_roll" for c in insights.get_playlist(db, pl["id"])["clips"])
    os.remove(path)


@pytest.fixture(scope="module")
def film_client():
    os.environ["HOOPLAB_DATA"] = tempfile.mkdtemp()
    os.environ.pop("HOOPLAB_DB", None)
    import importlib

    from fastapi.testclient import TestClient

    import hooplab.api as api
    importlib.reload(api)
    c = TestClient(api.app)
    return c, c.post("/api/demo").json()["team_id"]


def test_api_play_types_and_scouting_report(film_client):
    c, tid = film_client
    r = c.get(f"/api/teams/{tid}/play-types").json()
    assert r["possessions"] > 200 and r["best"] and r["overall_ppp"] > 0
    opp = c.get(f"/api/teams/{tid}/opponents").json()[0]
    o = c.get(f"/api/opponents/{opp['id']}/play-types").json()
    assert o["best"] == "transition"        # seeded tendency: Maccabi North runs
    o2 = c.get(f"/api/teams/{tid}/opponents").json()[1]
    assert c.get(f"/api/opponents/{o2['id']}/play-types").json()["best"] == "spot_up"   # Elitzur Coast shoots
    rep = c.get(f"/api/opponents/{opp['id']}/scouting-report").json()
    assert rep["source"] == "template" and "Transition" in rep["text"] and rep["facts"]["their_play_types"]
    assert c.get(f"/api/teams/{tid}/clips?play_type=nope").status_code == 422


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_demo_film_is_rendered_and_every_clip_plays(film_client):
    c, tid = film_client
    clips = c.get(f"/api/teams/{tid}/clips").json()
    assert len(clips) >= 15
    v = c.get(clips[0]["video_url"])
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4" and len(v.content) > 10_000
    sid = clips[0]["session_id"]                       # the film review asks for one session's moments
    one = c.get(f"/api/teams/{tid}/clips?session_id={sid}&limit=300").json()
    assert one and all(x["session_id"] == sid for x in one)
    assert c.get(f"/api/teams/{tid}/clips?session_id=999999").json() == []
    pl = c.post(f"/api/teams/{tid}/playlists", json={"title": "Made shots", "dimension": "rim_finishing",
                                                     "outcome": True}).json()
    got = c.get(f"/api/playlists/{pl['id']}").json()
    assert got["clips"] and all(x["type"] == "shot" and x["outcome"] for x in got["clips"])
    hw = c.post(f"/api/teams/{tid}/homework/assign").json()
    assert any(h["playlist_id"] for h in hw)
    sessions = c.get(f"/api/teams/{tid}/sessions").json()
    assert sum(s["has_video"] for s in sessions) == 1


def test_template_scouting_handles_thin_data():
    facts = {"opponent": "X", "notes": None, "comparison": [], "game_plan": [], "their_play_types": [],
             "their_overall_ppp": None, "our_play_types": [], "our_overall_ppp": None}
    assert llm.template_scouting(facts).startswith("# Scouting report: X")
