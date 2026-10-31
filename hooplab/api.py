"""HTTP API + static UI. Run: `uvicorn hooplab.api:app --reload`."""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import ai, coach_ai, ingest, insights, llm, offline, perception
from . import drills as dr
from .agent import Agent, history
from .db import DB, now_iso
from .seed import seed
from .skills import DIMENSIONS, PLAY_TYPES, POSITIONS
from .vision.backends import YoloTrackBackend, vision_available

STATIC = Path(__file__).parent / "static"
DATA_DIR = Path(os.environ.get("HOOPLAB_DATA", "./hooplab-data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
db = DB(os.environ.get("HOOPLAB_DB", str(DATA_DIR / "hooplab.db")))
app = FastAPI(title="HoopLab", version="0.1.0",
              description="AI assistant coach: learns your players from game & practice data.")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _get(table: str, row_id: int) -> dict:
    row = db.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    if not row:
        raise HTTPException(404, f"{table[:-1]} {row_id} not found")
    return row


# ------------------------------------------------------------------ schemas
class TeamIn(BaseModel):
    name: str
    level: str | None = None
    coach: str | None = None


class PlayerIn(BaseModel):
    name: str
    number: int | None = None
    position: Literal["PG", "SG", "SF", "PF", "C"]
    height_cm: int | None = None
    hand: Literal["R", "L"] | None = None
    notes: str | None = None


class PlayerPatch(BaseModel):
    name: str | None = None
    number: int | None = None
    position: Literal["PG", "SG", "SF", "PF", "C"] | None = None
    height_cm: int | None = None
    notes: str | None = None


class SessionIn(BaseModel):
    kind: Literal["game", "practice", "scrimmage"]
    date: str = Field(default_factory=now_iso)
    title: str | None = None
    opponent_id: int | None = None


class EventIn(BaseModel):
    type: Literal["shot", "free_throw", "pass", "assist", "turnover", "touch", "creation", "defense",
                  "rotation", "steal", "rebound", "sprint"]
    player_id: int | None = None
    opponent: bool = False          # event by the opponent (scouting)
    outcome: bool | None = None
    zone: Literal["rim", "paint", "mid", "three", "ft"] | None = None
    assist: bool = False
    occurred_at: str | None = None
    play_type: Literal[tuple(PLAY_TYPES)] | None = None  # type: ignore[valid-type]
    t_start: float | None = Field(default=None, ge=0)   # clip window in the session video (seconds)
    t_end: float | None = Field(default=None, ge=0)


class OpponentIn(BaseModel):
    name: str
    notes: str | None = None
    scouting: dict[str, float] = Field(default_factory=dict)


class PlanIn(BaseModel):
    minutes: int = Field(90, ge=15, le=240)
    players: int = Field(12, ge=1, le=30)
    hoops: int = Field(2, ge=0, le=12)
    max_intensity: Literal["low", "medium", "high"] = "high"
    full_court: bool = True
    focus: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    opponent_id: int | None = None


class FeedbackIn(BaseModel):
    drill_id: str
    rating: float = Field(0, ge=-1, le=1)
    ran: bool = False
    note: str | None = None


class SettingsIn(BaseModel):
    emphasis: dict[str, float] | None = None
    half_life_days: float | None = Field(None, gt=0, le=365)
    language: Literal["en", "he"] | None = None   # language for AI-written debriefs and messages


class HomeworkDone(BaseModel):
    made: int | None = Field(None, ge=0)
    attempts: int | None = Field(None, ge=0, le=500)


class TracksIn(BaseModel):
    tracks: dict
    our_team: int = 1               # which team label in the tracks is ours


# ------------------------------------------------------------------ meta
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "video_processing": vision_available(), "ai": ai.available(), "model": ai.MODEL}


@app.get("/api/meta")
def meta():
    return {"dimensions": {k: {"name": v[0], "group": v[1]} for k, v in DIMENSIONS.items()},
            "positions": POSITIONS, "play_types": PLAY_TYPES}


@app.post("/api/demo")
def demo():
    return {"team_id": seed(db, video_dir=str(DATA_DIR / "videos"))}


# ------------------------------------------------------------------ teams & players
@app.get("/api/teams")
def teams():
    return db.q("SELECT t.*, (SELECT COUNT(*) FROM players p WHERE p.team_id = t.id) AS players "
                "FROM teams t ORDER BY id DESC")


@app.post("/api/teams", status_code=201)
def create_team(t: TeamIn):
    return _get("teams", db.insert("teams", {**t.model_dump(), "created_at": now_iso()}))


@app.delete("/api/teams/{team_id}", status_code=204)
def delete_team(team_id: int):
    _get("teams", team_id)
    db.delete("teams", team_id)


@app.get("/api/teams/{team_id}/players")
def players(team_id: int):
    _get("teams", team_id)
    return db.q("SELECT * FROM players WHERE team_id = ? ORDER BY number", (team_id,))


@app.post("/api/teams/{team_id}/players", status_code=201)
def add_player(team_id: int, p: PlayerIn):
    _get("teams", team_id)
    return _get("players", db.insert("players", {**p.model_dump(), "team_id": team_id}))


@app.patch("/api/players/{player_id}")
def patch_player(player_id: int, p: PlayerPatch):
    _get("players", player_id)
    db.update("players", player_id, p.model_dump(exclude_none=True))
    return _get("players", player_id)


@app.delete("/api/players/{player_id}", status_code=204)
def delete_player(player_id: int):
    _get("players", player_id)
    db.delete("players", player_id)


@app.get("/api/players/{player_id}")
def player_detail(player_id: int):
    p = _get("players", player_id)
    snap = insights.team_snapshot(db, p["team_id"])
    card = next(c for c in snap["players"] if c["player"]["id"] == player_id)
    card["homework"] = db.q("SELECT * FROM homework WHERE player_id = ? ORDER BY id DESC LIMIT 10", (player_id,))
    card["recent_trends"] = [t for t in snap["trends"] if t["player"] == p["name"]]
    return card


# ------------------------------------------------------------------ sessions & data in
@app.get("/api/teams/{team_id}/sessions")
def sessions(team_id: int):
    return db.q("SELECT s.id, s.kind, s.title, s.date, s.status, s.opponent_id, "
                "(s.video_path IS NOT NULL) AS has_video, "
                "(SELECT COUNT(*) FROM events e WHERE e.session_id = s.id) AS events "
                "FROM sessions s WHERE team_id = ? ORDER BY date DESC", (team_id,))


@app.post("/api/teams/{team_id}/sessions", status_code=201)
def create_session(team_id: int, s: SessionIn):
    _get("teams", team_id)
    if s.opponent_id:
        _get("opponents", s.opponent_id)
    return _get("sessions", db.insert("sessions", {**s.model_dump(), "team_id": team_id}))


def _lang_of(team_id: int) -> str:
    return db.settings(team_id).get("language", "en")


def _debrief_now(session_id: int) -> None:
    """Post-session debrief into the coach's inbox (runs after the response is sent)."""
    try:
        s = _get("sessions", session_id)
        coach_ai.debrief(db, session_id, _lang_of(s["team_id"]))
    except Exception:  # a debrief must never break ingest
        pass


def _store_events(session: dict, events: list[dict], source: str) -> int:
    try:
        return ingest.store_events(db, session, events, source)
    except ingest.IngestError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/sessions/{session_id}/events", status_code=201)
def add_events(session_id: int, events: list[EventIn]):
    s = _get("sessions", session_id)
    team_players = {r["id"] for r in db.q("SELECT id FROM players WHERE team_id = ?", (s["team_id"],))}
    for e in events:
        if not e.opponent and e.player_id not in team_players:
            raise HTTPException(422, f"player {e.player_id} is not on this team")
    return {"stored": _store_events(s, [e.model_dump() for e in events], "manual")}


@app.post("/api/sessions/{session_id}/events.csv", status_code=201)
async def add_events_csv(session_id: int, bg: BackgroundTasks, file: UploadFile = File(...)):
    """CSV columns: player_number|player_id, type, outcome(1/0), zone, assist, opponent(1/0),
    optional play_type, t_start, t_end."""
    s = _get("sessions", session_id)
    by_num = {r["number"]: r["id"] for r in db.q("SELECT id, number FROM players WHERE team_id = ?",
                                                 (s["team_id"],))}
    text = (await file.read()).decode("utf-8-sig")
    rows = []
    for i, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            opp = r.get("opponent", "0").strip() in ("1", "true", "yes")
            pid = None
            if not opp:
                pid = int(r["player_id"]) if r.get("player_id") else by_num[int(r["player_number"])]
            ev = EventIn(type=r["type"].strip(), player_id=pid, opponent=opp,
                         outcome=(r.get("outcome", "").strip() in ("1", "true", "made", "yes"))
                         if r.get("outcome", "").strip() != "" else None,
                         zone=(r.get("zone") or None), assist=r.get("assist", "0").strip() in ("1", "true"),
                         play_type=(r.get("play_type") or "").strip() or None,
                         t_start=float(r["t_start"]) if (r.get("t_start") or "").strip() else None,
                         t_end=float(r["t_end"]) if (r.get("t_end") or "").strip() else None)
        except (KeyError, ValueError, ValidationError) as exc:
            raise HTTPException(422, f"CSV line {i}: {exc}") from exc
        rows.append(ev.model_dump())
    stored = _store_events(s, rows, "csv")
    bg.add_task(_debrief_now, session_id)
    return {"stored": stored}


def _ingest_tracks(session: dict, tracks: dict, our_team: int) -> dict:
    return ingest.ingest_tracks(db, session, tracks, our_team)


@app.post("/api/sessions/{session_id}/tracks")
def add_tracks(session_id: int, body: TracksIn, bg: BackgroundTasks):
    """Ingest a track file (from the YOLO backend or any external tracker)."""
    s = _get("sessions", session_id)
    try:
        out = _ingest_tracks(s, body.tracks, body.our_team)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"bad track file: {exc}") from exc
    bg.add_task(_debrief_now, session_id)
    return out


def _process_video(session_id: int, path: str, court_points, roster_map, our_team):
    try:
        tracks = YoloTrackBackend().process(path, court_points, roster_map)
        _ingest_tracks(_get("sessions", session_id), tracks, our_team)
        _debrief_now(session_id)
    except Exception as exc:
        db.update("sessions", session_id, {"status": f"failed: {str(exc)[:120]}"})


@app.post("/api/sessions/{session_id}/video", status_code=202)
async def upload_video(session_id: int, bg: BackgroundTasks, file: UploadFile = File(...),
                       court_points: str | None = None, roster_map: str | None = None, our_team: int = 1):
    s = _get("sessions", session_id)
    vdir = DATA_DIR / "videos"
    vdir.mkdir(exist_ok=True)
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    fd, path = tempfile.mkstemp(suffix=suffix, dir=vdir)
    with os.fdopen(fd, "wb") as out:
        shutil.copyfileobj(file.file, out)
    db.update("sessions", session_id, {"video_path": path})
    if not vision_available():
        db.update("sessions", session_id, {"status": "video stored - awaiting tracks"})
        return {"status": "stored", "detail": "Video processing is not installed on this server "
                "(pip install hooplab[vision]). Upload a track file or tag events instead."}
    db.update("sessions", session_id, {"status": "processing"})
    bg.add_task(_process_video, s["id"], path, json.loads(court_points) if court_points else None,
                json.loads(roster_map) if roster_map else None, our_team)
    return {"status": "processing"}


# ------------------------------------------------------------------ insights
@app.get("/api/teams/{team_id}/snapshot")
def snapshot(team_id: int):
    _get("teams", team_id)
    return insights.team_snapshot(db, team_id)


@app.get("/api/teams/{team_id}/briefing")
def briefing(team_id: int, lang: Literal["en", "he"] = "en"):
    _get("teams", team_id)
    return llm.briefing(insights.team_snapshot(db, team_id), lang)


@app.put("/api/teams/{team_id}/settings")
def put_settings(team_id: int, s: SettingsIn):
    _get("teams", team_id)
    if s.emphasis is not None:
        bad = set(s.emphasis) - set(DIMENSIONS)
        if bad:
            raise HTTPException(422, f"unknown dimensions: {sorted(bad)}")
        db.set_setting(team_id, "emphasis", s.emphasis)
    if s.half_life_days is not None:
        db.set_setting(team_id, "half_life_days", s.half_life_days)
    if s.language is not None:
        db.set_setting(team_id, "language", s.language)
    return {k: v for k, v in db.settings(team_id).items() if k != "truth"}


@app.get("/api/teams/{team_id}/settings")
def get_settings(team_id: int):
    _get("teams", team_id)
    return {k: v for k, v in db.settings(team_id).items() if k != "truth"}


@app.get("/api/drills")
def drills(team_id: int | None = None):
    lib = insights.library(db, team_id) if team_id else dr.LIBRARY
    return [d.to_dict() for d in lib]


@app.post("/api/teams/{team_id}/plan")
def plan(team_id: int, body: PlanIn):
    _get("teams", team_id)
    if body.opponent_id:
        _get("opponents", body.opponent_id)
    req = dr.PlanRequest(**body.model_dump(exclude={"opponent_id"}))
    result = insights.practice_plan(db, team_id, req, body.opponent_id)
    result["id"] = db.insert("plans", {"team_id": team_id, "created_at": now_iso(),
                                       "request": body.model_dump_json(), "plan": json.dumps(result)})
    return result


@app.post("/api/teams/{team_id}/feedback", status_code=201)
def feedback(team_id: int, f: FeedbackIn):
    _get("teams", team_id)
    lib = insights.library(db, team_id)
    if f.drill_id not in {d.id for d in lib}:
        raise HTTPException(422, "unknown drill")
    db.insert("drill_feedback", {**f.model_dump(), "team_id": team_id, "created_at": now_iso()})
    fb = db.q("SELECT drill_id, rating, ran FROM drill_feedback WHERE team_id = ?", (team_id,))
    return {"preferences": dr.preference_weights(fb, lib)}


@app.post("/api/teams/{team_id}/homework/assign")
def homework_assign(team_id: int, days: int = 7):
    _get("teams", team_id)
    return insights.assign_homework(db, team_id, days)


@app.get("/api/teams/{team_id}/homework")
def homework_list(team_id: int):
    rows = db.q("SELECT h.*, p.name AS player FROM homework h JOIN players p ON p.id = h.player_id "
                "WHERE p.team_id = ? ORDER BY h.status, p.number", (team_id,))
    by_id = {d.id: d for d in insights.library(db, team_id)}
    for r in rows:
        r["drill"] = by_id[r["drill_id"]].to_dict() if r["drill_id"] in by_id else None
    return rows


@app.post("/api/homework/{homework_id}/complete")
def homework_complete(homework_id: int, body: HomeworkDone):
    _get("homework", homework_id)
    return insights.complete_homework(db, homework_id, body.made, body.attempts)


@app.get("/api/teams/{team_id}/opponents")
def opponents(team_id: int):
    return db.q("SELECT id, name, notes FROM opponents WHERE team_id = ?", (team_id,))


@app.post("/api/teams/{team_id}/opponents", status_code=201)
def add_opponent(team_id: int, o: OpponentIn):
    _get("teams", team_id)
    oid = db.insert("opponents", {"team_id": team_id, "name": o.name, "notes": o.notes,
                                  "scouting": json.dumps(o.scouting)})
    return insights.opponent_profile(db, oid)


@app.get("/api/opponents/{opponent_id}/matchup")
def opponent_matchup(opponent_id: int):
    o = _get("opponents", opponent_id)
    return insights.matchup(db, o["team_id"], opponent_id)


# ------------------------------------------------------------------ film: clips, playlists, play types
class PlaylistIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    player_id: int | None = None
    dimension: str | None = None
    outcome: bool | None = None
    play_type: str | None = None
    note: str | None = None
    limit: int = Field(default=8, ge=1, le=50)


def _check_filters(dimension: str | None, play_type: str | None):
    if dimension and dimension not in DIMENSIONS:
        raise HTTPException(422, f"unknown dimension {dimension}")
    if play_type and play_type not in PLAY_TYPES:
        raise HTTPException(422, f"unknown play type {play_type}")


@app.get("/api/sessions/{session_id}/video")
def session_video(session_id: int):
    s = _get("sessions", session_id)
    if not s["video_path"] or not Path(s["video_path"]).is_file():
        raise HTTPException(404, "this session has no video")
    return FileResponse(s["video_path"], media_type="video/mp4")


@app.get("/api/teams/{team_id}/clips")
def team_clips(team_id: int, player_id: int | None = None, dimension: str | None = None,
               outcome: bool | None = None, play_type: str | None = None, opponent_id: int | None = None,
               session_id: int | None = None, limit: int = 30):
    """Every number opens its film: the possessions behind a stat, as clip windows."""
    _get("teams", team_id)
    _check_filters(dimension, play_type)
    return insights.clips(db, team_id, player_id, dimension, outcome, play_type, opponent_id, min(limit, 300),
                          session_id=session_id)


@app.post("/api/teams/{team_id}/playlists", status_code=201)
def create_playlist(team_id: int, body: PlaylistIn):
    _get("teams", team_id)
    _check_filters(body.dimension, body.play_type)
    pl = insights.build_playlist(db, team_id, body.title, body.player_id, body.dimension, body.outcome,
                                 body.play_type, body.note, body.limit)
    if not pl:
        raise HTTPException(404, "no clips match: link video to a session first")
    return pl


@app.get("/api/teams/{team_id}/playlists")
def playlists(team_id: int):
    return db.q("SELECT id, title, player_id, note, created_at FROM playlists WHERE team_id = ? "
                "ORDER BY id DESC LIMIT 50", (team_id,))


@app.get("/api/playlists/{playlist_id}")
def playlist(playlist_id: int):
    pl = insights.get_playlist(db, playlist_id)
    if not pl:
        raise HTTPException(404, "playlist not found")
    return pl


@app.get("/api/teams/{team_id}/play-types")
def play_types(team_id: int, player_id: int | None = None):
    """Points per possession by play type (team or one player): the self-scout."""
    _get("teams", team_id)
    if player_id and _get("players", player_id)["team_id"] != team_id:
        raise HTTPException(422, "player is not on this team")
    return insights.play_type_report(db, team_id, player_id=player_id)


@app.get("/api/opponents/{opponent_id}/play-types")
def opponent_play_types(opponent_id: int):
    o = _get("opponents", opponent_id)
    return insights.play_type_report(db, o["team_id"], opponent_id=opponent_id)


@app.get("/api/opponents/{opponent_id}/scouting-report")
def scouting_report(opponent_id: int, lang: Literal["en", "he"] = "en"):
    """One-page scouting report: Claude writes it, every number comes from the engine."""
    o = _get("opponents", opponent_id)
    facts = llm.scouting_facts(insights.matchup(db, o["team_id"], opponent_id),
                               insights.play_type_report(db, o["team_id"], opponent_id=opponent_id),
                               insights.play_type_report(db, o["team_id"]))
    return {**llm.scouting_report(facts, lang), "facts": facts}


# ------------------------------------------------------------------ coach loop: debriefs, inbox, progress, players
@app.get("/api/sessions/{session_id}/report")
def session_report(session_id: int):
    """Deterministic: what happened vs. what the model expected from each player."""
    _get("sessions", session_id)
    return coach_ai.session_report(db, session_id)


@app.post("/api/sessions/{session_id}/debrief", status_code=201)
def session_debrief(session_id: int, lang: Literal["en", "he"] | None = None):
    """Claude writes the post-session debrief (template without a key) and posts it to the inbox."""
    s = _get("sessions", session_id)
    return coach_ai.debrief(db, session_id, lang or _lang_of(s["team_id"]))


@app.get("/api/teams/{team_id}/inbox")
def team_inbox(team_id: int):
    _get("teams", team_id)
    return coach_ai.inbox(db, team_id, insights.team_snapshot(db, team_id))


@app.get("/api/players/{player_id}/history")
def player_history(player_id: int, weeks: int = 10):
    _get("players", player_id)
    return coach_ai.player_history(db, player_id, points=max(2, min(weeks, 52)))


@app.get("/api/players/{player_id}/message")
def player_message(player_id: int, lang: Literal["en", "he"] | None = None):
    """A personal message to the player, ready to send: written by Claude from the model's facts."""
    p = _get("players", player_id)
    snap = insights.team_snapshot(db, p["team_id"])
    card = next(c for c in snap["players"] if c["player"]["id"] == player_id)
    return coach_ai.player_message(db, card, lang or _lang_of(p["team_id"]), trends=snap["trends"])


@app.post("/api/teams/{team_id}/players.csv", status_code=201)
async def import_roster(team_id: int, file: UploadFile = File(...)):
    """Roster import. CSV columns: name, number, position (PG/SG/SF/PF/C), optional height_cm, hand, notes.
    Existing players (same number) are updated, new ones added."""
    _get("teams", team_id)
    text = (await file.read()).decode("utf-8-sig")
    existing = {r["number"]: r["id"] for r in db.q("SELECT id, number FROM players WHERE team_id = ?", (team_id,))}
    added = updated = 0
    for i, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            p = PlayerIn(name=r["name"].strip(), number=int(r["number"]) if (r.get("number") or "").strip() else None,
                         position=r["position"].strip().upper(),
                         height_cm=int(r["height_cm"]) if (r.get("height_cm") or "").strip() else None,
                         hand=(r.get("hand") or "").strip().upper() or None, notes=(r.get("notes") or "").strip() or None)
        except (KeyError, ValueError, ValidationError) as exc:
            raise HTTPException(422, f"roster line {i}: {exc}") from exc
        if p.number is not None and p.number in existing:
            db.update("players", existing[p.number], p.model_dump())
            updated += 1
        else:
            db.insert("players", {**p.model_dump(), "team_id": team_id})
            added += 1
    return {"added": added, "updated": updated}


# ------------------------------------------------------------------ AI-native
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    chat_id: int | None = None
    context: str | None = Field(None, max_length=2000)   # what the coach is looking at ("player: Noam Levi")


class NotesIn(BaseModel):
    notes: str = Field(min_length=3, max_length=20000)


def _ai_guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except ai.AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/teams/{team_id}/chat")
def chat(team_id: int, body: ChatIn):
    """Talk to the assistant-coach agent (Claude + HoopLab tools)."""
    _get("teams", team_id)
    try:
        return Agent(db, team_id).chat(body.message, body.chat_id, body.context)
    except ai.AIUnavailable:          # no key: answer from the deterministic engine instead
        return offline.reply(db, team_id, body.message, body.chat_id, body.context)


@app.get("/api/teams/{team_id}/chats")
def chats(team_id: int):
    return db.q("SELECT id, created_at, updated_at FROM chats WHERE team_id = ? ORDER BY id DESC LIMIT 20",
                (team_id,))


@app.get("/api/teams/{team_id}/chats/{chat_id}")
def chat_history(team_id: int, chat_id: int):
    return history(db, team_id, chat_id)


def _session_players(session: dict):
    players = db.q("SELECT * FROM players WHERE team_id = ?", (session["team_id"],))
    opp = db.one("SELECT name FROM opponents WHERE id = ?", (session["opponent_id"],)) if session["opponent_id"] else None
    return players, opp["name"] if opp else None


def _store_ai(session: dict, result: dict, source: str) -> dict:
    evs = result["events"]
    for e in evs:
        if e.get("opponent") and not session["opponent_id"]:
            e["opponent"] = False
            e["skip"] = True
    keep = [e for e in evs if not e.pop("skip", False)]
    stored = _store_events(session, keep, source) if keep else 0
    return {"stored": stored, "observations": result["observations"], "unresolved": result["unresolved"]}


@app.post("/api/sessions/{session_id}/notes", status_code=201)
def notes(session_id: int, body: NotesIn, bg: BackgroundTasks):
    """Free-text coach notes (any language) -> events, via Claude structured outputs."""
    s = _get("sessions", session_id)
    players, opp = _session_players(s)
    try:
        result = perception.events_from_notes(body.notes, players, opp)
    except ai.AIUnavailable:
        result = offline.events_from_notes(body.notes, players)
    out = _store_ai(s, result, "notes")
    if out["stored"]:
        bg.add_task(_debrief_now, session_id)
    return out


@app.post("/api/sessions/{session_id}/film", status_code=201)
async def film(session_id: int, bg: BackgroundTasks, files: list[UploadFile] = File(...), context: str = "",
               our_color: str | None = None):
    """Frames (images) or a short clip -> events + scouting notes, via Claude vision."""
    s = _get("sessions", session_id)
    images: list[tuple[bytes, str]] = []
    for f in files:
        data = await f.read()
        ctype = (f.content_type or "").lower()
        if ctype in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            images.append((data, ctype))
        elif ctype.startswith("video/"):
            if not vision_available():
                raise HTTPException(422, "send frames as images, or install hooplab[vision] to sample video")
            with tempfile.NamedTemporaryFile(suffix=Path(f.filename or "v.mp4").suffix) as tmp:
                tmp.write(data)
                tmp.flush()
                images += perception.sample_video_frames(tmp.name)
        else:
            raise HTTPException(422, f"unsupported file type {ctype or f.filename}")
    if not images:
        raise HTTPException(422, "no frames")
    players, _ = _session_players(s)
    result = _ai_guard(perception.events_from_images, images, players, context, our_color)
    out = _store_ai(s, result, "film-ai")
    if out["stored"]:
        bg.add_task(_debrief_now, session_id)
    return out
