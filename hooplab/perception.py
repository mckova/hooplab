"""Claude as HoopLab's eyes and ears.

* Coach notes in free text (Hebrew or English, voice-to-text, WhatsApp-style)
  -> structured events credited to roster players.
* Game/practice stills or frames sampled from a video -> tagged events plus
  scouting observations (Claude vision).

Output is constrained with structured outputs (a Pydantic schema), then mapped
onto the roster. Evidence from notes and film is stored at reduced weight
(0.7 / 0.5) because it is less precise than tracked or bench-tagged events.
"""
from __future__ import annotations

import base64
from typing import Literal

from pydantic import BaseModel

from . import ai

EventType = Literal["shot", "turnover", "touch", "creation", "defense", "rotation", "steal",
                    "rebound", "sprint", "assist"]


class ExtractedEvent(BaseModel):
    player_number: int | None
    player_name: str | None
    opponent: bool
    type: EventType
    outcome: bool | None
    zone: Literal["rim", "mid", "three", "ft"] | None
    count: int
    evidence: str


class Extraction(BaseModel):
    events: list[ExtractedEvent]
    observations: list[str]
    unresolved: list[str]


GUIDE = """Event types and outcomes (one event = one repetition):
- shot: outcome true = made. zone: rim (layups/dunks/close), mid, three, ft (free throw).
- turnover: lost the ball (outcome false). touch: a possession handled securely (true).
- creation: a drive/pass that created a shot for a teammate (true) or a failed attempt to (false).
- defense: on-ball possession, true = stop, false = beaten. rotation: help rotation, true = on time, false = late/missing.
- steal (true). rebound: true = secured, false = lost the board. sprint: transition effort, true = sprinted back, false = jogged.
- assist (true).
Use `count` for repeated identical events ("3 of 5 threes" = shot/three/true count 3 + shot/three/false count 2).
Only record what is stated or clearly visible; never invent numbers. Put anything you cannot map to a roster
player or an event type in `unresolved`, and tactical/scouting remarks in `observations`."""


def _roster_text(players: list[dict]) -> str:
    return "\n".join(f"#{p['number']} {p['name']} ({p['position']})" for p in players)


def _to_events(ex: Extraction, players: list[dict], weight: float, source: str) -> tuple[list[dict], list[str]]:
    by_num = {p["number"]: p["id"] for p in players if p.get("number") is not None}
    by_name = {}
    for p in players:
        for token in [p["name"].lower(), *p["name"].lower().split()]:
            by_name.setdefault(token, p["id"])
    out, unresolved = [], list(ex.unresolved)
    for e in ex.events:
        pid = None
        if not e.opponent:
            pid = by_num.get(e.player_number) if e.player_number is not None else None
            if pid is None and e.player_name:
                pid = by_name.get(e.player_name.lower().strip()) or next(
                    (v for k, v in by_name.items() if k in e.player_name.lower().split()), None)
            if pid is None:
                unresolved.append(f"no roster match: {e.player_name or e.player_number} ({e.evidence})")
                continue
        n = max(1, min(int(e.count or 1), 50))
        for _ in range(n):
            out.append({"type": e.type, "player_id": pid, "opponent": e.opponent,
                        "outcome": e.outcome if e.type not in ("turnover",) else False,
                        "zone": e.zone, "weight": weight, "source": source})
    return out, unresolved


def _parse(content, system: str) -> Extraction:
    client = ai.get_client()
    resp = client.beta.messages.parse(
        model=ai.MODEL, max_tokens=8000, system=system,
        output_config={"effort": ai.EFFORT},
        messages=[{"role": "user", "content": content}],
        output_format=Extraction, **ai.FALLBACK_KW)
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise ai.AIUnavailable(f"model did not return events (stop_reason={resp.stop_reason})")
    return resp.parsed_output


def events_from_notes(notes: str, players: list[dict], opponent_name: str | None = None) -> dict:
    system = ("You turn a basketball coach's notes into structured events for an analytics system.\n"
              + GUIDE + f"\n\nRoster:\n{_roster_text(players)}\n"
              + (f"Opponent: {opponent_name}. Events by opponent players get opponent=true.\n" if opponent_name else ""))
    ex = _parse([{"type": "text", "text": f"<coach_notes>\n{notes}\n</coach_notes>"}], system)
    events, unresolved = _to_events(ex, players, 0.7, "notes")
    return {"events": events, "observations": ex.observations, "unresolved": unresolved}


def events_from_images(images: list[tuple[bytes, str]], players: list[dict], context: str = "",
                       our_color: str | None = None) -> dict:
    """images: (bytes, media_type) pairs, in time order (e.g. 1 frame/second around a play)."""
    system = ("You are a basketball video analyst. The images are consecutive frames from one game or practice "
              "clip, in time order. Identify players by jersey number. Tag only events you can actually see "
              "happen across the frames.\n" + GUIDE + f"\n\nOur roster:\n{_roster_text(players)}\n"
              + (f"Our team wears {our_color}; the other team is the opponent (opponent=true).\n" if our_color else ""))
    content: list[dict] = []
    for i, (data, media_type) in enumerate(images[:20]):
        content.append({"type": "text", "text": f"Frame {i + 1}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                    "data": base64.standard_b64encode(data).decode()}})
    content.append({"type": "text", "text": f"Context from the coach: {context or 'none'}"})
    ex = _parse(content, system)
    events, unresolved = _to_events(ex, players, 0.5, "film-ai")
    return {"events": events, "observations": ex.observations, "unresolved": unresolved}


def sample_video_frames(path: str, every_s: float = 1.0, limit: int = 20) -> list[tuple[bytes, str]]:
    """Needs the vision extra (opencv)."""
    import cv2
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(fps * every_s))
    frames, i = [], 0
    while len(frames) < limit:
        ok, img = cap.read()
        if not ok:
            break
        if i % step == 0:
            h, w = img.shape[:2]
            if w > 1280:
                img = cv2.resize(img, (1280, int(h * 1280 / w)))
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                frames.append((buf.tobytes(), "image/jpeg"))
        i += 1
    cap.release()
    return frames
