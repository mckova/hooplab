"""Synthetic track generator: scripted basketball sequences rendered as the same
track-file JSON a real detector produces. Used by tests and the demo, so the
whole video -> events -> insights path runs without GPUs or footage."""
from __future__ import annotations

import math
import random

SCALE = 40.0          # px per metre
ORIGIN = (100.0, 100.0)
HOOP_COURT = (26.425, 7.5)
HOOP_LIFT = 160.0     # px the rim sits above its floor point in the image


def to_img(xy):
    return (ORIGIN[0] + xy[0] * SCALE, ORIGIN[1] + xy[1] * SCALE)


def court_points() -> dict:
    corners = [(0, 0), (28, 0), (28, 15), (0, 15)]
    return {"image": [list(to_img(c)) for c in corners], "court": [list(c) for c in corners]}


def _hoop_box():
    x, y = to_img(HOOP_COURT)
    return [x - 12, y - HOOP_LIFT, x + 12, y - HOOP_LIFT + 10]


def _player_box(xy):
    fx, fy = to_img(xy)
    return [fx - 15, fy - 80, fx + 15, fy]


def _ball_at_hands(xy):
    fx, fy = to_img(xy)
    cx, cy = fx + 8, fy - 50
    return [cx - 5, cy - 5, cx + 5, cy + 5]


class Scene:
    def __init__(self, players: dict, fps: int = 25, seed: int = 0):
        """players: {track_id: {"team": 1|2, "pos": (x, y) metres}}"""
        self.fps = fps
        self.players = {str(k): {"team": v["team"], "pos": tuple(v["pos"])} for k, v in players.items()}
        self.frames: list[dict] = []
        self.rng = random.Random(seed)
        self.holder: str | None = None

    # -- low level
    def _emit(self, ball_box):
        self.frames.append({
            "players": {t: {"bbox": [round(v, 1) for v in _player_box(p["pos"])], "team": p["team"]}
                        for t, p in self.players.items()},
            "ball": [round(v, 1) for v in ball_box] if ball_box else None,
            "hoop": _hoop_box(),
        })

    def _step_moves(self, moves: dict, frac: float, starts: dict):
        for t, target in moves.items():
            s = starts[t]
            self.players[t]["pos"] = (s[0] + (target[0] - s[0]) * frac, s[1] + (target[1] - s[1]) * frac)

    # -- script verbs
    def hold(self, tid, seconds: float, moves: dict | None = None):
        tid = str(tid)
        self.holder = tid
        n = max(1, int(seconds * self.fps))
        moves = {str(k): v for k, v in (moves or {}).items()}
        starts = {t: self.players[t]["pos"] for t in moves}
        for i in range(n):
            self._step_moves(moves, (i + 1) / n, starts)
            self._emit(_ball_at_hands(self.players[tid]["pos"]))

    def pass_to(self, src, dst, seconds: float = 0.6):
        a = _ball_at_hands(self.players[str(src)]["pos"])
        b = _ball_at_hands(self.players[str(dst)]["pos"])
        n = max(2, int(seconds * self.fps))
        for i in range(1, n):
            f = i / n
            self._emit([a[k] + (b[k] - a[k]) * f for k in range(4)])
        self.hold(dst, 0.5)

    def shoot(self, tid, made: bool, rebounder=None, seconds: float = 1.2):
        """Parabolic flight from hands to the rim; misses clip the rim edge and
        fall off to the side, then `rebounder` (if any) collects the ball."""
        x0, y0 = _center(_ball_at_hands(self.players[str(tid)]["pos"]))
        hb = _hoop_box()
        rim_x = (hb[0] + hb[2]) / 2 + (0 if made else 22)   # misses hit the far rim edge
        rim_y = hb[1] + 2.5
        n = max(8, int(seconds * self.fps))
        ctrl_y = min(y0, rim_y) - 200                       # arc control point
        k = int(n * 0.8)
        for i in range(1, k + 1):                           # flight: bezier hand -> rim
            v = i / k
            x = x0 + (rim_x - x0) * v
            y = (1 - v) ** 2 * y0 + 2 * (1 - v) * v * ctrl_y + v ** 2 * (rim_y - 8)
            self._emit([x - 5, y - 5, x + 5, y + 5])
        drift = 0 if made else 6
        for i in range(1, n - k + 1):                       # drop through / off the rim
            x = rim_x + drift * i
            y = rim_y - 8 + 9 * i
            self._emit([x - 5, y - 5, x + 5, y + 5])
        # loose ball for a moment
        for _ in range(int(0.3 * self.fps)):
            self._emit(None)
        if rebounder is not None:
            self.hold(rebounder, 0.6)

    def steal(self, thief, seconds: float = 0.4):
        """Thief pokes the ball loose and takes it."""
        n = max(1, int(seconds * self.fps))
        for _ in range(n):
            self._emit(None)
        self.hold(thief, 0.6)

    def run(self, moves: dict, seconds: float, with_ball=None):
        moves = {str(k): v for k, v in moves.items()}
        starts = {t: self.players[t]["pos"] for t in moves}
        n = max(1, int(seconds * self.fps))
        for i in range(n):
            self._step_moves(moves, (i + 1) / n, starts)
            ball = _ball_at_hands(self.players[str(with_ball)]["pos"]) if with_ball else None
            self._emit(ball)

    def to_json(self, roster_map: dict | None = None) -> dict:
        return {"fps": self.fps, "court_points": court_points(), "frames": self.frames,
                "roster_map": roster_map or {}}


def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def demo_possessions(roster_map: dict | None = None, seed: int = 7) -> dict:
    """A short half-court sequence: ball movement, a made three with an assist,
    a missed jumper + defensive rebound, a steal and the sprint-back after it."""
    players = {
        "1": {"team": 1, "pos": (16, 7.5)}, "2": {"team": 1, "pos": (19, 2)},
        "3": {"team": 1, "pos": (19, 13)}, "4": {"team": 1, "pos": (24, 4)},
        "5": {"team": 1, "pos": (24.5, 10)},
        "11": {"team": 2, "pos": (17.5, 7.5)}, "12": {"team": 2, "pos": (20.5, 3)},
        "13": {"team": 2, "pos": (20.5, 12)}, "14": {"team": 2, "pos": (24.8, 5)},
        "15": {"team": 2, "pos": (25.2, 9.5)},
    }
    s = Scene(players, seed=seed)
    s.hold(1, 1.0)
    s.pass_to(1, 2)
    s.hold(2, 0.5)
    s.pass_to(2, 3)
    s.shoot(3, made=True, rebounder=None)
    s.run({}, 0.5)
    # second possession: miss + defensive rebound by 15
    s.hold(1, 0.8)
    s.pass_to(1, 4)
    s.shoot(4, made=False, rebounder=15)
    # team 2 gives it back: 15 -> 11 pass, 11 drives, 1 steals it
    s.pass_to(15, 11)
    s.players["1"]["pos"] = (s.players["11"]["pos"][0] + 0.3, s.players["11"]["pos"][1])
    s.steal(1)
    # sprint back after the turnover: 12,13 sprint, 14,15 jog
    s.run({"12": (6, 4), "13": (6, 11), "14": (24, 6.5), "15": (24.6, 9)}, 3.0, with_ball=1)
    return s.to_json(roster_map)


def demo_film(roster_map: dict | None = None, seed: int = 11) -> dict:
    """~40 s of half-court possessions with play-type annotations, for the demo
    team's game film. Team 1 attacks the right basket."""
    base = {
        "1": (16, 7.5), "2": (19, 2), "3": (19, 13), "4": (23.5, 3.5), "5": (24.5, 10),
        "11": (17.5, 7.5), "12": (20.5, 3), "13": (20.5, 12), "14": (24.8, 5), "15": (25.2, 9.5),
    }
    players = {k: {"team": 1 if int(k) < 10 else 2, "pos": v} for k, v in base.items()}
    s = Scene(players, seed=seed)
    notes = []

    def reset():                      # dead ball between possessions
        s.run({}, 1.2)
        for k, v in base.items():
            s.players[k]["pos"] = v
        s.run({}, 0.4)

    def mark(play_type, f0):
        notes.append({"t_start": round(f0 / s.fps, 2), "t_end": round(len(s.frames) / s.fps, 2),
                      "play_type": play_type})

    # 1) pick & roll: 1 uses the screen, hits the rolling 5 for a layup
    f0 = len(s.frames)
    s.hold(1, 0.8, moves={"1": (20, 6.5), "5": (20.5, 7.2)})
    s.run({"5": (25.6, 8.2)}, 0.8, with_ball=1)
    s.pass_to(1, 5)
    s.shoot(5, made=True)
    mark("pick_and_roll", f0)
    reset()
    # 2) spot-up three: 3 misses, 15 rebounds
    f0 = len(s.frames)
    s.hold(1, 0.8)
    s.pass_to(1, 3)
    s.shoot(3, made=False, rebounder=15)
    mark("spot_up", f0)
    reset()
    # 3) isolation: 1 drives and is stripped by 11
    f0 = len(s.frames)
    s.hold(1, 1.0, moves={"1": (20.5, 7.5), "11": (21.0, 7.5)})
    s.players["11"]["pos"] = (s.players["1"]["pos"][0] + 0.3, s.players["1"]["pos"][1])
    s.steal(11)
    s.run({"12": (6, 4), "13": (6, 11), "11": (8, 7.5), "2": (7, 3), "3": (7, 12), "4": (12, 5), "5": (23, 9)},
          3.0, with_ball=11)
    mark("isolation", f0)
    reset()
    # 4) cut: 2 back-cuts for a layup from 1
    f0 = len(s.frames)
    s.hold(1, 0.8, moves={"2": (25.4, 6.4)})
    s.pass_to(1, 2)
    s.shoot(2, made=True)
    mark("cut", f0)
    reset()
    # 5) post-up: 4 misses over 14, 5 can't hold the board (15 gets it)
    f0 = len(s.frames)
    s.hold(1, 0.6)
    s.pass_to(1, 4)
    s.hold(4, 0.8, moves={"4": (24.8, 6.0)})
    s.shoot(4, made=False, rebounder=15)
    mark("post_up", f0)
    reset()
    # 6) spot-up again: 2 makes a three
    f0 = len(s.frames)
    s.hold(1, 0.6)
    s.pass_to(1, 2)
    s.shoot(2, made=True)
    mark("spot_up", f0)
    out = s.to_json(roster_map)
    out["annotations"] = notes
    return out
