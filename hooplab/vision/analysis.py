"""From object tracks to basketball events.

Input is a *track file* (see `docs/track-format.md`): per frame, player boxes
with track ids and team, a ball box and optionally a hoop box. Any detector can
produce it (the optional YOLO backend does). Everything here is deterministic
geometry so it can be unit-tested with synthetic tracks.

Pipeline:  possession -> passes / turnovers / steals -> shots (attempt, make,
zone, shooter) -> assists & rebounds -> movement (speed, distance, sprint-backs)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import geometry as g


@dataclass
class AnalysisConfig:
    fps: float = 25.0
    hold_containment: float = 0.55   # ball mostly inside a player box -> held
    hold_reach: float = 0.45         # max hand-to-ball distance, in player-box heights
    min_hold_frames: int = 6         # possession must persist this long to count
    max_relative_ball_speed: float = 0.08  # per frame, in player-box heights
    dead_ball_s: float = 1.0         # ball unseen this long = stoppage, possession chain restarts
    shot_cooldown_s: float = 1.5
    assist_window_s: float = 4.0
    sprint_window_s: float = 3.0
    sprint_speed_ms: float = 3.5     # avg m/s after a turnover that counts as sprinting back


@dataclass
class TrackSet:
    frames: list[dict]
    fps: float = 25.0
    court_h: object = None            # 3x3 homography image->court, optional
    roster_map: dict = field(default_factory=dict)  # track id -> roster player id
    start_time_s: float = 0.0
    annotations: list = field(default_factory=list)  # coach tags: [{t_start, t_end, play_type}]

    @classmethod
    def from_json(cls, data: dict) -> "TrackSet":
        h = None
        cp = data.get("court_points")
        if cp:
            h = g.homography(cp["image"], cp["court"])
        return cls(frames=data["frames"], fps=float(data.get("fps", 25)), court_h=h,
                   roster_map={str(k): v for k, v in (data.get("roster_map") or {}).items()},
                   annotations=list(data.get("annotations") or []))

    def to_court(self, p):
        return g.project(self.court_h, p) if self.court_h is not None else None


# --------------------------------------------------------------- possession
def _hands_point(box, ball_c):
    """Closest point to the ball within the player's 'reach' area (upper 2/3)."""
    x1, y1, x2, y2 = box
    top = y1
    bottom = y1 + (y2 - y1) * 0.75
    return (min(max(ball_c[0], x1), x2), min(max(ball_c[1], top), bottom))


def raw_holder(frame: dict, cfg: AnalysisConfig, prev: dict | None = None):
    """Who has the ball in this frame. A ball that moves *relative to* a player
    (i.e. is in flight over them in the 2-D image) is never held by that player:
    a held ball travels with its holder."""
    ball = frame.get("ball")
    players = frame.get("players") or {}
    if not ball or not players:
        return None
    bc = g.center(ball)
    pball = prev.get("ball") if prev else None
    pplayers = (prev.get("players") or {}) if prev else {}
    best, best_score = None, None
    for tid, p in players.items():
        box = p["bbox"]
        h = max(box[3] - box[1], 1.0)
        pp = pplayers.get(tid)
        if pball and pp:
            pbc, pc, c_now = g.center(pball), g.center(pp["bbox"]), g.center(box)
            rel = g.dist((bc[0] - pbc[0], bc[1] - pbc[1]), (c_now[0] - pc[0], c_now[1] - pc[1]))
            if rel / h > cfg.max_relative_ball_speed:
                continue
        c = g.containment(box, ball)
        if c >= cfg.hold_containment:
            score = -c                       # containment beats distance
        else:
            d = g.dist(_hands_point(box, bc), bc) / h
            if d > cfg.hold_reach:
                continue
            score = d
        if best_score is None or score < best_score:
            best, best_score = str(tid), score
    return best


def possession(ts: TrackSet, cfg: AnalysisConfig) -> list:
    """Per-frame holder id (or None), debounced: a new holder must be seen for
    `min_hold_frames` consecutive frames before possession switches."""
    raw = [raw_holder(f, cfg, ts.frames[i - 1] if i else None) for i, f in enumerate(ts.frames)]
    out: list = [None] * len(raw)
    current, cand, run = None, None, 0
    for i, r in enumerate(raw):
        if r is None:
            cand, run = None, 0
            out[i] = None
            continue
        if r == current:
            cand, run = None, 0
            out[i] = current
            continue
        if r == cand:
            run += 1
        else:
            cand, run = r, 1
        if run >= cfg.min_hold_frames:
            current = cand
            for j in range(i - run + 1, i + 1):
                out[j] = current
            cand, run = None, 0
        else:
            out[i] = None
    return out


def team_of(ts: TrackSet, tid, frame_idx: int):
    for i in range(frame_idx, -1, -1):
        p = (ts.frames[i].get("players") or {}).get(tid)
        if p and p.get("team") is not None:
            return p["team"]
    return None


# --------------------------------------------------------------- events
def _t(ts: TrackSet, i: int) -> float:
    return ts.start_time_s + i / ts.fps


def possession_events(ts: TrackSet, holders: list, shot_frames=(), dead_ball_s: float = 1.0) -> list[dict]:
    """Passes (same team change), turnovers + steals (other team gains the ball).
    A change of holder with a shot in between is a rebound/inbound, not a pass."""
    evs = []
    shot_frames = sorted(shot_frames)
    prev, prev_i = None, None
    dead = int(dead_ball_s * ts.fps)
    unseen = 0
    for i, h in enumerate(holders):
        unseen = unseen + 1 if not ts.frames[i].get("ball") else 0
        if unseen >= dead:          # ball out of view long enough: dead ball, chain restarts
            prev, prev_i = None, None
        if h is None:
            continue
        shot_between = prev_i is not None and any(prev_i < s <= i for s in shot_frames)
        if prev is not None and h != prev and not shot_between:
            ta, tb = team_of(ts, prev, prev_i), team_of(ts, h, i)
            if ta is not None and ta == tb:
                evs.append({"type": "pass", "track": prev, "to_track": h, "outcome": True,
                            "frame": i, "t": _t(ts, i), "team": ta})
            elif ta is not None and tb is not None:
                evs.append({"type": "turnover", "track": prev, "outcome": False,
                            "frame": i, "t": _t(ts, i), "team": ta})
                evs.append({"type": "steal", "track": h, "outcome": True,
                            "frame": i, "t": _t(ts, i), "team": tb})
        prev, prev_i = h, i
    return evs


def shot_events(ts: TrackSet, holders: list, cfg: AnalysisConfig) -> list[dict]:
    """Detect attempts from the ball trajectory around the hoop box.

    An attempt = the ball enters the window above the rim and then drops below
    rim height. It is *made* when the descending segment crosses rim height
    inside the rim's horizontal span (linear interpolation between the two
    frames that straddle the rim)."""
    evs = []
    cooldown = int(cfg.shot_cooldown_s * ts.fps)
    last_shot = -10 ** 9
    state, enter_i, above = "idle", None, None
    for i, f in enumerate(ts.frames):
        hoop, ball = f.get("hoop"), f.get("ball")
        if not hoop or not ball:
            continue
        hx1, hy1, hx2, hy2 = hoop
        hw, hh = hx2 - hx1, hy2 - hy1
        rim_y = hy1 + 0.25 * hh
        bx, by = g.center(ball)
        in_window = (hx1 - 2.5 * hw <= bx <= hx2 + 2.5 * hw) and (rim_y - 4 * hh <= by < rim_y)
        if state == "idle" and in_window and i - last_shot > cooldown:
            state, enter_i, above = "rising", i, (bx, by)
            continue
        if state == "rising":
            if by < rim_y:
                above = (bx, by)
                if i - enter_i > 3 * ts.fps:     # ball parked above rim: not a shot
                    state = "idle"
                continue
            # crossed below rim height: decide made / missed
            ax, ay = above
            frac = (rim_y - ay) / max(by - ay, 1e-6)
            cross_x = ax + frac * (bx - ax)
            made = hx1 + 0.1 * hw <= cross_x <= hx2 - 0.1 * hw
            shooter, s_i = None, None
            for j in range(enter_i, max(-1, enter_i - int(2 * ts.fps)), -1):
                if holders[j] is not None:
                    shooter, s_i = holders[j], j
                    break
            ev = {"type": "shot", "track": shooter, "outcome": made, "frame": i,
                  "t": _t(ts, i), "release_frame": s_i,
                  "team": team_of(ts, shooter, s_i) if shooter else None}
            if shooter is not None and ts.court_h is not None:
                p = ts.frames[s_i]["players"][shooter]["bbox"]
                court_xy = ts.to_court(g.foot(p))
                ev["zone"] = g.court_zone(court_xy)
                ev["court_xy"] = [round(float(court_xy[0]), 2), round(float(court_xy[1]), 2)]
            evs.append(ev)
            last_shot, state = i, "idle"
    return evs


def link_assists(events: list[dict], cfg: AnalysisConfig) -> None:
    passes = [e for e in events if e["type"] == "pass"]
    for s in (e for e in events if e["type"] == "shot" and e["outcome"]):
        cands = [p for p in passes if p["to_track"] == s["track"]
                 and 0 <= s["t"] - p["t"] <= cfg.assist_window_s]
        if cands:
            cands[-1]["assist"] = True


def rebound_events(ts: TrackSet, holders: list, shots: list[dict]) -> list[dict]:
    """After a miss: the next holder secures the board; the nearest opponent to
    the ball at that moment is charged with a lost rebound opportunity."""
    evs = []
    for s in shots:
        if s["outcome"]:
            continue
        for i in range(s["frame"], len(holders)):
            h = holders[i]
            if h is None:
                continue
            team = team_of(ts, h, i)
            evs.append({"type": "rebound", "track": h, "outcome": True, "frame": i,
                        "t": _t(ts, i), "team": team,
                        "offensive": team is not None and team == s.get("team")})
            ball = ts.frames[i].get("ball")
            if ball:
                bc = g.center(ball)
                rivals = [(g.dist(g.center(p["bbox"]), bc), tid, p.get("team"))
                          for tid, p in ts.frames[i]["players"].items()
                          if p.get("team") is not None and p.get("team") != team]
                if rivals:
                    _, tid, rteam = min(rivals)
                    evs.append({"type": "rebound", "track": tid, "outcome": False,
                                "frame": i, "t": _t(ts, i), "team": rteam})
            break
    return evs


def movement(ts: TrackSet) -> dict[str, list]:
    """Per-track court positions (m) by frame index; needs a homography."""
    pos: dict[str, list] = {}
    if ts.court_h is None:
        return pos
    for i, f in enumerate(ts.frames):
        for tid, p in (f.get("players") or {}).items():
            pos.setdefault(str(tid), []).append((i, ts.to_court(g.foot(p["bbox"]))))
    return pos


def movement_stats(ts: TrackSet, pos: dict[str, list]) -> dict[str, dict]:
    out = {}
    for tid, seq in pos.items():
        dist_m, top = 0.0, 0.0
        for (i0, p0), (i1, p1) in zip(seq, seq[1:]):
            d = g.dist(p0, p1)
            dt = (i1 - i0) / ts.fps
            if dt <= 0 or d / dt > 11.0:        # > ~40 km/h: tracking glitch
                continue
            dist_m += d
            top = max(top, d / dt)
        out[tid] = {"distance_m": round(dist_m, 1), "top_speed_kmh": round(top * 3.6, 1)}
    return out


def sprint_events(ts: TrackSet, pos: dict[str, list], turnovers: list[dict],
                  cfg: AnalysisConfig) -> list[dict]:
    """After a turnover, did each player of the team that lost the ball sprint back?"""
    evs = []
    win = int(cfg.sprint_window_s * ts.fps)
    for to in turnovers:
        team = to.get("team")
        f0 = to["frame"]
        for tid, p in (ts.frames[f0].get("players") or {}).items():
            if p.get("team") != team or tid not in pos:
                continue
            seg = [(i, xy) for i, xy in pos[tid] if f0 <= i <= f0 + win]
            if len(seg) < 2:
                continue
            d = sum(g.dist(a[1], b[1]) for a, b in zip(seg, seg[1:]))
            speed = d / ((seg[-1][0] - seg[0][0]) / ts.fps)
            evs.append({"type": "sprint", "track": tid, "outcome": speed >= cfg.sprint_speed_ms,
                        "team": team, "frame": f0, "t": _t(ts, f0), "speed_ms": round(speed, 2)})
    return evs


def analyze(ts: TrackSet, cfg: AnalysisConfig | None = None) -> dict:
    cfg = cfg or AnalysisConfig(fps=ts.fps)
    holders = possession(ts, cfg)
    shots = shot_events(ts, holders, cfg)
    events = possession_events(ts, holders, [s["frame"] for s in shots], cfg.dead_ball_s) + shots
    link_assists(events, cfg)
    events += rebound_events(ts, holders, shots)
    pos = movement(ts)
    events += sprint_events(ts, pos, [e for e in events if e["type"] == "turnover"], cfg)
    for e in events:
        e["player_id"] = ts.roster_map.get(str(e.get("track")))
        e["t_start"] = round(max(0.0, e["t"] - 3.0), 2)
        e["t_end"] = round(e["t"] + 1.5, 2)
        for a in ts.annotations:
            if a["t_start"] <= e["t"] <= a["t_end"] and a.get("play_type"):
                e["play_type"] = a["play_type"]
    events.sort(key=lambda e: e["frame"])
    held = [h for h in holders if h is not None]
    team_poss: dict = {}
    for i, h in enumerate(holders):
        if h is not None:
            t = team_of(ts, h, i)
            team_poss[t] = team_poss.get(t, 0) + 1
    return {
        "events": events,
        "movement": movement_stats(ts, pos),
        "possession_share": {str(k): round(v / max(len(held), 1), 3) for k, v in team_poss.items()},
        "frames": len(ts.frames),
    }
