"""Shared write path for events: used by the API, the AI perception routes and the demo seed."""
from __future__ import annotations

import json

from .db import DB
from .vision.analysis import TrackSet, analyze

EVENT_KEYS = ("type", "outcome", "zone", "assist", "play_type", "t_start", "t_end")


class IngestError(ValueError):
    pass


def store_events(db: DB, session: dict, events: list[dict], source: str) -> int:
    rows = []
    for e in events:
        e = dict(e)
        if e.pop("opponent", False):
            if not session["opponent_id"]:
                raise IngestError("opponent events need a session with an opponent")
            e["opponent_id"] = session["opponent_id"]
            e["player_id"] = None
        if e.get("type") == "free_throw":
            e["type"], e["zone"] = "shot", "ft"
        rows.append(e)
    return db.add_events(session["id"], rows, session["date"], source=source)


def ingest_tracks(db: DB, session: dict, tracks: dict, our_team: int = 1) -> dict:
    """Track file -> detected events (with clip windows and play types) -> stored events."""
    result = analyze(TrackSet.from_json(tracks))
    evs = []
    for e in result["events"]:
        row = {k: e.get(k) for k in EVENT_KEYS}
        if e.get("player_id") is not None:
            evs.append({**row, "player_id": e["player_id"]})
        elif e.get("team") is not None and e["team"] != our_team and session["opponent_id"]:
            evs.append({**row, "opponent": True})
    stored = store_events(db, session, evs, "video")
    summary = {k: v for k, v in result.items() if k != "events"}
    summary["events_detected"] = len(result["events"])
    summary["events_stored"] = stored
    db.update("sessions", session["id"], {"status": "analyzed", "analysis": json.dumps(summary)})
    return summary
