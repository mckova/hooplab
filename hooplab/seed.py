"""Demo data: a youth team with hidden 'true' skills, 10 weeks of simulated
games/practices, two scouted opponents and some coach feedback. The engine only
sees the events, so the demo also shows the model recovering the hidden skills."""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from .db import DB, now_iso
from .skills import BASELINE

# Play-type mix by zone and how efficient each play type is (relative), plus
# per-player tendencies. Tags are drawn from a separate RNG so they never change
# the simulated outcomes: P(type | made) ~ mix*eff, P(type | missed) ~ mix*(1-eff).
PLAY_MIX = {
    "rim": {"pick_and_roll": 3, "cut": 2, "transition": 2, "post_up": 1, "putback": 1, "isolation": 1},
    "mid": {"pick_and_roll": 3, "isolation": 2, "post_up": 2, "off_screen": 1, "handoff": 1},
    "three": {"spot_up": 4, "pick_and_roll": 2, "off_screen": 2, "handoff": 1, "transition": 1},
    "turnover": {"pick_and_roll": 3, "isolation": 2, "post_up": 1, "handoff": 1, "transition": 1, "cut": 1},
}
PLAY_EFF = {"pick_and_roll": .50, "cut": .66, "transition": .60, "post_up": .44, "putback": .58,
            "isolation": .38, "off_screen": .48, "handoff": .47, "spot_up": .52}
TENDENCY = {  # jersey number -> {play_type: (mix multiplier, efficiency shift)}
    3: {"pick_and_roll": (2.0, .10), "isolation": (0.6, -.08)},
    7: {"spot_up": (1.6, .10), "off_screen": (1.8, .08)},
    10: {"cut": (2.0, .08), "isolation": (1.5, -.12)},
    14: {"post_up": (1.6, -.10), "putback": (2.0, .05)},
    21: {"post_up": (2.0, .10), "putback": (2.0, .06), "pick_and_roll": (1.4, .06)},
    5: {"pick_and_roll": (1.5, -.05), "handoff": (1.5, .04)},
    11: {"isolation": (1.8, -.05), "transition": (1.5, .06)},
    33: {"spot_up": (1.3, -.10), "cut": (1.5, .04)},
}
OPP_TENDENCY = {  # opponent index -> play-type profile
    0: {"transition": (3.0, .12), "pick_and_roll": (1.2, -.04), "post_up": (0.5, -.08)},
    1: {"spot_up": (2.2, .10), "transition": (0.4, -.10), "handoff": (1.8, .05)},
}


def _tag(prng, e, tend):
    key = "turnover" if e["type"] == "turnover" else e.get("zone")
    if key not in PLAY_MIX or (e["type"] == "shot" and key == "ft"):
        return
    made = bool(e.get("outcome")) and e["type"] == "shot"
    names, weights = [], []
    for pt, w in PLAY_MIX[key].items():
        mult, shift = tend.get(pt, (1.0, 0.0))
        eff = min(.9, max(.1, PLAY_EFF[pt] + shift))
        names.append(pt)
        weights.append(w * mult * (eff if made else 1 - eff))
    e["play_type"] = prng.choices(names, weights)[0]

ROSTER = [
    # name, number, position, height, {dimension: true rate overrides}
    ("Noam Levi", 3, "PG", 182, {"playmaking": .30, "ball_security": .80, "three_point": .30, "transition": .85}),
    ("Itay Mizrahi", 7, "SG", 188, {"three_point": .43, "on_ball_defense": .44, "free_throw": .86}),
    ("Ori Ben-David", 10, "SF", 193, {"rim_finishing": .66, "three_point": .26, "help_defense": .66}),
    ("Yoav Cohen", 14, "PF", 198, {"rebounding": .60, "free_throw": .55, "midrange": .45}),
    ("Daniel Peretz", 21, "C", 205, {"rim_finishing": .70, "help_defense": .48, "transition": .45}),
    ("Eitan Shapiro", 5, "PG", 178, {"ball_security": .93, "on_ball_defense": .66, "rim_finishing": .42}),
    ("Amit Golan", 11, "SG", 186, {"midrange": .47, "transition": .55}),
    ("Lior Katz", 33, "SF", 195, {"rebounding": .30, "on_ball_defense": .62}),
]
ZONES = {"rim_finishing": "rim", "midrange": "mid", "three_point": "three", "free_throw": "ft"}
# per-game attempts by dimension (scaled by minutes)
VOLUME = {"rim_finishing": 4, "midrange": 2, "three_point": 3, "free_throw": 3, "ball_security": 18,
          "playmaking": 10, "on_ball_defense": 8, "help_defense": 5, "rebounding": 6, "transition": 3}


def _events_for(rng, pid, true, n_scale, when, improving=None, week=0):
    evs = []
    for dim, vol in VOLUME.items():
        p = true[dim]
        if improving and dim == improving:
            p = min(.95, p - 0.11 + 0.025 * week)       # visible progress over the weeks
        for _ in range(max(0, int(rng.gauss(vol * n_scale, 1)))):
            ok = rng.random() < p
            if dim in ZONES:
                e = {"type": "shot", "zone": ZONES[dim], "outcome": ok}
            elif dim == "ball_security":
                e = {"type": "touch", "outcome": True} if ok else {"type": "turnover", "outcome": False}
            elif dim == "playmaking":
                e = {"type": "creation", "outcome": ok}
            elif dim == "on_ball_defense":
                e = {"type": "defense", "outcome": ok}
            elif dim == "help_defense":
                e = {"type": "rotation", "outcome": ok}
            elif dim == "rebounding":
                e = {"type": "rebound", "outcome": ok}
            else:
                e = {"type": "sprint", "outcome": ok}
            e.update(player_id=pid, occurred_at=when, source="video")
            evs.append(e)
    return evs


def seed(db: DB, seed_value: int = 1, weeks: int = 10, video_dir: str | None = None) -> int:
    rng = random.Random(seed_value)
    prng = random.Random(seed_value + 7919)
    team_id = db.insert("teams", {"name": "Hapoel Demo U18", "level": "U18 national league",
                                  "coach": "Coach May", "created_at": now_iso()})
    truth, numbers = {}, {}
    for name, num, pos, h, over in ROSTER:
        pid = db.insert("players", {"team_id": team_id, "name": name, "number": num, "position": pos,
                                    "height_cm": h, "hand": "R"})
        t = dict(BASELINE[pos])
        t.update(over)
        truth[pid] = t
        numbers[pid] = num
    opp1 = db.insert("opponents", {"team_id": team_id, "name": "Maccabi North U18",
                                   "notes": "Athletic, presses full court",
                                   "scouting": json.dumps({"transition": .74, "free_throw": .58})})
    opp2 = db.insert("opponents", {"team_id": team_id, "name": "Elitzur Coast U18",
                                   "notes": "Slow tempo, shooters", "scouting": json.dumps({})})
    opp_true = {opp1: {"on_ball_defense": .62, "help_defense": .46, "rebounding": .33, "ball_security": .82,
                       "three_point": .29, "rim_finishing": .58, "playmaking": .14},
                opp2: {"on_ball_defense": .47, "help_defense": .58, "rebounding": .46, "ball_security": .90,
                       "three_point": .41, "rim_finishing": .51, "playmaking": .20, "transition": .55}}
    start = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    pids = list(truth)
    improving = {pids[0]: "ball_security", pids[1]: "on_ball_defense"}  # simulated progress
    for w in range(weeks):
        for kind, day, scale in (("practice", 1, 0.6), ("practice", 3, 0.6), ("game", 5, 1.0)):
            when = (start + timedelta(weeks=w, days=day)).isoformat(timespec="seconds")
            opp = (opp1 if w % 2 == 0 else opp2) if kind == "game" else None
            sid = db.insert("sessions", {"team_id": team_id, "kind": kind, "date": when, "opponent_id": opp,
                                         "title": f"{kind.title()} week {w + 1}", "status": "analyzed"})
            evs = []
            for pid in pids:
                minutes = rng.uniform(0.5, 1.0) if kind == "game" else 1.0
                pe = _events_for(rng, pid, truth[pid], scale * minutes, when, improving.get(pid), w)
                if kind == "game":
                    for e in pe:
                        _tag(prng, e, TENDENCY.get(numbers[pid], {}))
                evs += pe
            if opp:
                for dim, p in opp_true[opp].items():
                    for _ in range(VOLUME[dim] * 2):
                        ok = rng.random() < p
                        e = {"type": {"rim_finishing": "shot", "three_point": "shot", "on_ball_defense": "defense",
                                      "help_defense": "rotation", "rebounding": "rebound", "ball_security": "turnover",
                                      "playmaking": "creation", "transition": "sprint"}[dim],
                             "zone": ZONES.get(dim), "outcome": ok, "opponent_id": opp, "occurred_at": when}
                        if dim == "ball_security":
                            e["type"] = "touch" if ok else "turnover"
                        _tag(prng, e, OPP_TENDENCY[[opp1, opp2].index(opp)])
                        evs.append(e)
            db.add_events(sid, evs, when, source="video")
    for drill_id, rating, ran in (("3v3-rebound-war", 1, 1), ("advantage-3v2-2v1", 1, 1),
                                  ("no-dribble-scrimmage", -1, 0), ("suicide-ladders", -1, 0),
                                  ("shell-defense", .5, 1)):
        db.insert("drill_feedback", {"team_id": team_id, "drill_id": drill_id, "rating": rating, "ran": ran,
                                     "created_at": now_iso()})
    db.set_setting(team_id, "truth", {str(k): v for k, v in truth.items()})
    from .coach_ai import debrief
    last_game = db.one("SELECT id FROM sessions WHERE team_id = ? AND kind = 'game' ORDER BY date DESC", (team_id,))
    debrief(db, last_game["id"], use_ai=False)   # the inbox starts with last game's debrief
    if video_dir:
        _seed_film(db, team_id, opp1, pids, numbers, video_dir, start + timedelta(weeks=weeks, days=-1))
    return team_id


def _seed_film(db: DB, team_id: int, opp: int, pids: list[int], numbers: dict, video_dir: str, when) -> None:
    """A short rendered game film whose events link to clips (needs ffmpeg + Pillow)."""
    import os
    import shutil

    from .ingest import ingest_tracks
    from .vision.render import render_mp4
    from .vision.synth import demo_film
    if not shutil.which("ffmpeg"):
        return
    roster_map = {str(i + 1): pids[i] for i in range(5)}
    tracks = demo_film(roster_map)
    os.makedirs(video_dir, exist_ok=True)
    path = os.path.join(video_dir, f"demo-film-team{team_id}.mp4")
    labels = {str(i + 1): f"#{numbers[pids[i]]}" for i in range(5)}
    try:
        render_mp4(tracks, path, labels=labels)
    except Exception:  # rendering is a demo nicety; never break the seed
        return
    date = when.isoformat(timespec="seconds")
    sid = db.insert("sessions", {"team_id": team_id, "kind": "game", "date": date, "opponent_id": opp,
                                 "title": "Film: Maccabi North (first quarter)", "status": "analyzed",
                                 "video_path": path})
    ingest_tracks(db, db.one("SELECT * FROM sessions WHERE id = ?", (sid,)), tracks, our_team=1)
    from .coach_ai import debrief
    debrief(db, sid, use_ai=False)
