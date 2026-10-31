"""Skill model: how HoopLab turns raw basketball events into a per-player profile.

Every observable event maps to one *skill dimension* and a binary outcome
(success / failure). A player's level on a dimension is a Beta posterior whose
prior comes from the player's position, so a new player starts at the positional
baseline and moves away from it only as evidence accumulates. Older evidence is
down-weighted with an exponential half-life, which lets the profile follow a
player who is improving (or slumping) instead of averaging the whole season.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

POSITIONS = ("PG", "SG", "SF", "PF", "C")

# dimension id -> human label, group
DIMENSIONS: dict[str, tuple[str, str]] = {
    "rim_finishing": ("Finishing at the rim", "scoring"),
    "midrange": ("Mid-range shooting", "scoring"),
    "three_point": ("Three-point shooting", "scoring"),
    "free_throw": ("Free throws", "scoring"),
    "ball_security": ("Ball security", "playmaking"),
    "playmaking": ("Playmaking / creating for others", "playmaking"),
    "on_ball_defense": ("On-ball defense", "defense"),
    "help_defense": ("Help defense & rotations", "defense"),
    "rebounding": ("Rebounding", "defense"),
    "transition": ("Transition effort (sprint back / run)", "athletic"),
}

# Positional baselines (league-ish rates for a competitive amateur level) and
# how much each dimension matters for the role. Baselines double as priors.
BASELINE: dict[str, dict[str, float]] = {
    "PG": dict(rim_finishing=.52, midrange=.38, three_point=.34, free_throw=.75, ball_security=.86,
               playmaking=.22, on_ball_defense=.55, help_defense=.55, rebounding=.30, transition=.70),
    "SG": dict(rim_finishing=.54, midrange=.39, three_point=.35, free_throw=.76, ball_security=.88,
               playmaking=.15, on_ball_defense=.55, help_defense=.55, rebounding=.33, transition=.70),
    "SF": dict(rim_finishing=.56, midrange=.38, three_point=.33, free_throw=.72, ball_security=.89,
               playmaking=.12, on_ball_defense=.55, help_defense=.57, rebounding=.40, transition=.68),
    "PF": dict(rim_finishing=.60, midrange=.37, three_point=.30, free_throw=.68, ball_security=.90,
               playmaking=.09, on_ball_defense=.52, help_defense=.60, rebounding=.48, transition=.64),
    "C": dict(rim_finishing=.64, midrange=.35, three_point=.27, free_throw=.62, ball_security=.91,
              playmaking=.07, on_ball_defense=.50, help_defense=.62, rebounding=.55, transition=.60),
}
IMPORTANCE: dict[str, dict[str, float]] = {
    "PG": dict(rim_finishing=.8, midrange=.7, three_point=1.0, free_throw=.7, ball_security=1.3,
               playmaking=1.4, on_ball_defense=1.1, help_defense=.8, rebounding=.5, transition=1.0),
    "SG": dict(rim_finishing=.9, midrange=.9, three_point=1.3, free_throw=.8, ball_security=1.0,
               playmaking=.8, on_ball_defense=1.1, help_defense=.8, rebounding=.6, transition=1.0),
    "SF": dict(rim_finishing=1.0, midrange=.8, three_point=1.1, free_throw=.7, ball_security=.9,
               playmaking=.7, on_ball_defense=1.1, help_defense=1.0, rebounding=.9, transition=1.0),
    "PF": dict(rim_finishing=1.2, midrange=.7, three_point=.7, free_throw=.7, ball_security=.8,
               playmaking=.5, on_ball_defense=.9, help_defense=1.2, rebounding=1.3, transition=.9),
    "C": dict(rim_finishing=1.3, midrange=.5, three_point=.4, free_throw=.8, ball_security=.8,
              playmaking=.5, on_ball_defense=.8, help_defense=1.4, rebounding=1.5, transition=.8),
}
PRIOR_STRENGTH = 8.0      # pseudo-observations behind the positional prior
DEFAULT_HALF_LIFE_DAYS = 45.0
Z80 = 1.2816              # two-sided 80% interval


# ---------------------------------------------------------------- event mapping
def event_to_observations(event: dict) -> list[tuple[str, bool]]:
    """Map one event dict to (dimension, success) observations.

    Event shape: {"type": ..., "outcome": bool|None, "zone": ...}.
    Unknown types produce no observation (they are still stored).
    """
    t = event.get("type")
    ok = bool(event.get("outcome"))
    if t == "shot":
        zone = event.get("zone") or "mid"
        dim = {"rim": "rim_finishing", "paint": "rim_finishing", "mid": "midrange",
               "three": "three_point", "ft": "free_throw"}.get(zone, "midrange")
        return [(dim, ok)]
    if t == "free_throw":
        return [("free_throw", ok)]
    if t == "pass":
        # a completed pass is a secure touch; an assist is also a playmaking win
        obs = [("ball_security", True)]
        obs.append(("playmaking", bool(event.get("assist"))))
        return obs
    if t == "touch":             # a possession/touch that ended without losing the ball
        return [("ball_security", True)]
    if t == "creation":          # drive/pass chance: True = created a good shot for others
        return [("playmaking", ok)]
    if t == "turnover":
        return [("ball_security", False)]
    if t == "assist":
        return [("playmaking", True)]
    if t == "defense":           # on-ball possession: outcome True = stop
        return [("on_ball_defense", ok)]
    if t == "rotation":          # help/rotation assignment: True = on time
        return [("help_defense", ok)]
    if t == "steal":
        return [("on_ball_defense", True)]
    if t == "rebound":           # rebound opportunity: True = secured
        return [("rebounding", ok)]
    if t == "sprint":            # transition rep: True = got back / ran the lane
        return [("transition", ok)]
    return []


# ---------------------------------------------------------------- posterior
@dataclass
class SkillEstimate:
    dimension: str
    mean: float
    low: float
    high: float
    baseline: float
    evidence: float          # effective (decayed) observations
    importance: float

    @property
    def label(self) -> str:
        if self.low > self.baseline:
            return "strength"
        if self.high < self.baseline:
            return "weakness"
        return "neutral"

    @property
    def gap(self) -> float:
        """Signed distance from baseline, in baseline-relative units."""
        return (self.mean - self.baseline) / max(self.baseline, 0.05)

    @property
    def confidence(self) -> float:
        """0..1: how much the data (vs. the prior) drives the estimate."""
        return self.evidence / (self.evidence + PRIOR_STRENGTH)

    def to_dict(self) -> dict:
        name, group = DIMENSIONS[self.dimension]
        return {
            "dimension": self.dimension, "name": name, "group": group,
            "mean": round(self.mean, 3), "low": round(self.low, 3), "high": round(self.high, 3),
            "baseline": self.baseline, "evidence": round(self.evidence, 1),
            "confidence": round(self.confidence, 2), "label": self.label,
            "gap": round(self.gap, 3), "importance": self.importance,
        }


def _decay_weight(when: str | None, now: datetime, half_life_days: float) -> float:
    if not when or half_life_days <= 0:
        return 1.0
    try:
        ts = datetime.fromisoformat(when)
    except ValueError:
        return 1.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max((now - ts).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / half_life_days)


def beta_interval(a: float, b: float, z: float = Z80) -> tuple[float, float, float]:
    mean = a / (a + b)
    var = a * b / ((a + b) ** 2 * (a + b + 1))
    sd = math.sqrt(var)
    return mean, max(0.0, mean - z * sd), min(1.0, mean + z * sd)


@dataclass
class SkillProfile:
    player_id: int
    position: str
    estimates: dict[str, SkillEstimate] = field(default_factory=dict)

    def strengths(self) -> list[SkillEstimate]:
        s = [e for e in self.estimates.values() if e.label == "strength"]
        return sorted(s, key=lambda e: -e.gap * e.importance)

    def weaknesses(self) -> list[SkillEstimate]:
        w = [e for e in self.estimates.values() if e.label == "weakness"]
        return sorted(w, key=lambda e: e.gap * e.importance)

    def needs(self, emphasis: dict[str, float] | None = None) -> dict[str, float]:
        """Development need per dimension (>=0): how far below baseline, scaled by
        role importance, coach emphasis and confidence. Neutral dims with little
        data get a small exploration need so they are not ignored forever."""
        emphasis = emphasis or {}
        out = {}
        for d, e in self.estimates.items():
            shortfall = max(0.0, -e.gap)
            need = shortfall * e.importance * emphasis.get(d, 1.0) * (0.4 + 0.6 * e.confidence)
            if e.confidence < 0.3:
                need += 0.03 * e.importance  # "we don't know yet" -> worth observing
            out[d] = round(need, 4)
        return out


def build_profile(player_id: int, position: str, events: Iterable[dict], *,
                  now: datetime | None = None,
                  half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> SkillProfile:
    position = position if position in BASELINE else "SF"
    now = now or datetime.now(timezone.utc)
    succ = {d: 0.0 for d in DIMENSIONS}
    fail = {d: 0.0 for d in DIMENSIONS}
    for ev in events:
        w = _decay_weight(ev.get("occurred_at"), now, half_life_days) * float(ev.get("weight", 1.0))
        for dim, ok in event_to_observations(ev):
            (succ if ok else fail)[dim] += w
    prof = SkillProfile(player_id, position)
    for d in DIMENSIONS:
        base = BASELINE[position][d]
        a = base * PRIOR_STRENGTH + succ[d]
        b = (1 - base) * PRIOR_STRENGTH + fail[d]
        mean, lo, hi = beta_interval(a, b)
        prof.estimates[d] = SkillEstimate(d, mean, lo, hi, base, succ[d] + fail[d],
                                          IMPORTANCE[position][d])
    return prof


def rates_from_events(events: Iterable[dict]) -> dict[str, dict]:
    """Raw (undecayed, prior-free) success rates; used for opponent scouting."""
    succ: dict[str, int] = {}
    tot: dict[str, int] = {}
    for ev in events:
        for dim, ok in event_to_observations(ev):
            tot[dim] = tot.get(dim, 0) + 1
            succ[dim] = succ.get(dim, 0) + int(ok)
    return {d: {"rate": succ[d] / tot[d], "n": tot[d]} for d in tot}


# ---------------------------------------------------------------- play types
PLAY_TYPES = {
    "pick_and_roll": "Pick & roll", "isolation": "Isolation", "post_up": "Post-up", "spot_up": "Spot-up",
    "transition": "Transition", "cut": "Cut", "off_screen": "Off screen", "handoff": "Handoff",
    "putback": "Putback",
}


def possession_points(event: dict) -> int | None:
    """Points a possession-ending event produced (None = does not end a possession).
    Missed shots count as 0: offensive rebounds start a new tagged possession."""
    t = event.get("type")
    if t == "turnover":
        return 0
    if t == "shot" and event.get("zone") != "ft":
        if not event.get("outcome"):
            return 0
        return 3 if event.get("zone") == "three" else 2
    return None
