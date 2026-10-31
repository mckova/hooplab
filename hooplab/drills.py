"""Drill library, practice-plan recommender and coach-preference learning."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace


@dataclass(frozen=True)
class Drill:
    id: str
    name: str
    targets: dict              # dimension -> weight (0..1)
    minutes: int
    min_players: int
    max_players: int = 99
    hoops: int = 1
    intensity: str = "medium"  # low | medium | high
    solo: bool = False         # can be done alone -> eligible as homework
    tags: tuple = ()
    setup: str = ""
    cue: str = ""
    metric: str = ""
    full_court: bool = False   # needs the whole floor (breaks, end-to-end slides, 5-on-5)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = list(self.tags)
        return d


D = Drill
LIBRARY: list[Drill] = [
    # ---- warm-up / general
    D("dynamic-warmup", "Dynamic warm-up + ball handling lines", {"ball_security": .3, "transition": .2}, 10, 1,
      intensity="low", tags=("warmup",), setup="Full-court lines: skips, lunges, then two-ball dribble series.",
      cue="Eyes up, low hips.", metric="No dropped balls on the two-ball series."),
    D("partner-form-shooting", "Partner form shooting", {"free_throw": .5, "midrange": .4}, 8, 2, intensity="low",
      tags=("warmup", "shooting-reps"), setup="Pairs, 5 spots inside the paint, rebounder passes.",
      cue="Same release every rep.", metric="8/10 from each spot before moving back."),
    # ---- finishing
    D("mikan-series", "Mikan + reverse Mikan series", {"rim_finishing": 1.0}, 6, 1, solo=True, intensity="medium",
      tags=("finishing", "fundamentals"), setup="Continuous layups under the rim, alternating hands.",
      cue="Off the glass, high release.", metric="20 makes in 60 s without the ball touching the floor."),
    D("contact-finishing", "Contact finishing with pads", {"rim_finishing": 1.0}, 10, 2, intensity="high",
      tags=("finishing", "physical"), setup="Coach/partner bumps with a pad on the gather; finish through contact.",
      cue="Chin the ball, absorb, go up strong.", metric="7/10 finishes through contact."),
    D("1v1-drive-from-wing", "1-on-1 from the wing (2 dribbles max)", {"rim_finishing": .6, "on_ball_defense": .6},
      12, 4, intensity="high", tags=("competitive", "1on1"),
      setup="Offense catches on the wing, max 2 dribbles; defense must keep the ball out of the middle.",
      cue="Offense: first step past the hip. Defense: beat him to the spot.", metric="Defense: 50%+ stops."),
    # ---- shooting
    D("catch-and-shoot-5-spot", "5-spot catch & shoot", {"three_point": 1.0, "midrange": .3}, 10, 1, solo=True,
      tags=("shooting-reps",), setup="5 spots around the arc, 10 shots each; with partner use passes on the move.",
      cue="Feet ready before the catch.", metric="Chart makes: target 35/50."),
    D("form-free-throws", "Free throws under fatigue", {"free_throw": 1.0}, 8, 1, solo=True,
      tags=("shooting-reps", "conditioning"), setup="Sprint baseline-to-baseline, then 2 free throws. 10 rounds.",
      cue="Same routine every time, breathe out.", metric="15/20 made."),
    D("pull-up-elbows", "Pull-up jumpers from the elbows", {"midrange": 1.0, "ball_security": .2}, 8, 1, solo=True,
      tags=("shooting-reps", "creation"), setup="Jab, one hard dribble, pull up at the elbow. Both sides, both hands.",
      cue="Stop on balance, shoulders square.", metric="12/20 made."),
    D("shooting-competition", "Team shooting race", {"three_point": .7, "midrange": .5, "free_throw": .3}, 10, 6,
      tags=("shooting-reps", "competitive"), setup="Two or three teams, one ball per team, first to 25 makes from a rotating spot.",
      cue="Shoot game shots at game speed.", metric="Winning team under 4 minutes."),
    D("closeout-shooting", "Shooting off a live closeout", {"three_point": .8, "on_ball_defense": .3}, 10, 3,
      tags=("shooting-reps", "competitive"), setup="Defender closes out; shooter shoots over a high hand or attacks the close-out with one dribble.",
      cue="Read the closeout: short = shoot, long = drive.", metric="Make 40%+ with a hand up."),
    # ---- ball handling / security / playmaking
    D("two-ball-handling", "Two-ball stationary + moving handling", {"ball_security": 1.0}, 8, 1, solo=True,
      intensity="low", tags=("fundamentals", "handling"),
      setup="Pound, alternate, crossover; then walk/jog the series.", cue="Eyes on the rim, not the ball.",
      metric="3 minutes with no lost ball."),
    D("pressure-handling-gauntlet", "Gauntlet: dribble through pressure", {"ball_security": 1.0}, 8, 3,
      intensity="high", tags=("handling", "competitive"),
      setup="Ball-handler goes the length of the court past 2 defenders swiping in zones.",
      cue="Protect with the off arm, change speed not just direction.", metric="Max 1 turnover per 5 trips."),
    D("advantage-3v2-2v1", "3-on-2 into 2-on-1 continuous", {"playmaking": .8, "ball_security": .6, "transition": .6},
      12, 5, max_players=15, intensity="high", tags=("competitive", "decision-making", "small-sided"),
      setup="Continuous full-court advantage break; shooter + passer stay back on defense.",
      cue="Make the defender commit, then make the simple pass.", metric="Score on 70% of reps, zero live-ball turnovers."),
    D("pass-and-read-shell", "Drive-and-kick 4-on-4 shell", {"playmaking": 1.0, "help_defense": .5}, 12, 8,
      tags=("decision-making", "team-offense"), setup="4-out shell: every drive must get to the paint, read help, kick or finish.",
      cue="Drive to score, pass to the open man.", metric="3+ paint touches per possession."),
    D("no-dribble-scrimmage", "No-dribble 5-on-5", {"playmaking": .9, "ball_security": .5}, 10, 10, max_players=12,
      tags=("decision-making", "small-sided"), setup="Half court, no dribbling allowed; cuts and passes only.",
      cue="Pass and cut, fill the empty spot.", metric="Fewer than 2 turnovers per 10 possessions."),
    D("wall-passing", "Wall passing series", {"playmaking": .6, "ball_security": .6}, 6, 1, solo=True,
      intensity="low", tags=("fundamentals",), setup="Chest, bounce, one-hand push and wrap passes against a wall target.",
      cue="Step into the pass, thumbs down on release.", metric="100 passes hitting the target box."),
    # ---- defense
    D("zig-zag-defense", "Zig-zag slides", {"on_ball_defense": 1.0, "transition": .3}, 8, 2, solo=False,
      intensity="medium", tags=("defense", "fundamentals"),
      setup="Defender slides baseline to baseline cutting off a zig-zag dribbler.",
      cue="Beat the ball to the spot, don't reach.", metric="Turn the dribbler 3 times per half court."),
    D("defensive-slides-solo", "Defensive slide + closeout ladder", {"on_ball_defense": .9}, 8, 1, solo=True,
      intensity="high", tags=("defense", "conditioning"),
      setup="Lane slides, drop-step, sprint-closeout to a cone; 6 x 30 s.", cue="Stay low, hands active.",
      metric="Complete 6 sets without standing up."),
    D("shell-defense", "Shell defense 4-on-4 (help & recover)", {"help_defense": 1.0, "on_ball_defense": .4}, 12, 8,
      tags=("defense", "team-defense"), setup="Ball moves around the perimeter; defenders jump to help / deny / closeout on each pass.",
      cue="Ball, you, man: see both.", metric="Every rotation on time for 5 straight passes."),
    D("help-and-recover-2v2", "2-on-2 help and recover", {"help_defense": .9, "on_ball_defense": .5}, 10, 4,
      tags=("defense", "competitive"), setup="Ball drives baseline; helper stunts and recovers to the shooter.",
      cue="Stunt, don't commit, sprint back.", metric="Allow under 1 point per possession."),
    D("charge-drill", "Taking the charge", {"help_defense": .7}, 6, 2, intensity="medium",
      tags=("defense", "physical"), setup="Help defender rotates outside the restricted arc and absorbs contact.",
      cue="Feet set, chest up, fall back safely.", metric="Set feet before the driver's gather 8/10."),
    D("film-rotations", "Film homework: help rotations", {"help_defense": .8, "on_ball_defense": .3}, 15, 1,
      hoops=0, intensity="low", solo=True, tags=("film",),
      setup="Watch 10 tagged defensive possessions from the last game; pause at each drive and say where help should come from.",
      cue="Where is the ball, where is my man, where is the rim?", metric="Correct call on 8/10 clips (checked with coach)."),
    # ---- rebounding
    D("box-out-circle", "Box-out circle", {"rebounding": 1.0}, 6, 2, intensity="high",
      tags=("rebounding", "physical"), setup="Ball in a circle; defender keeps offensive player out of it for 3 s.",
      cue="Find, hit, get the ball.", metric="Hold position 3 s on 8/10 reps."),
    D("3v3-rebound-war", "3-on-3 rebound war", {"rebounding": 1.0, "help_defense": .2}, 10, 6,
      intensity="high", tags=("rebounding", "competitive", "small-sided"),
      setup="Coach shoots; team that secures it scores a point, offense stays on until it gets 3 boards.",
      cue="Everybody hits somebody.", metric="Defense wins 70% of boards."),
    D("tip-and-outlet", "Tip drill + outlet pass", {"rebounding": .7, "transition": .4}, 6, 1, solo=True,
      tags=("rebounding",), setup="Tip the ball off the glass 10 times, then rebound and outlet.",
      cue="Two hands, chin it, pivot out.", metric="10 tips without the ball dropping."),
    # ---- transition / conditioning
    D("sprint-back-recovery", "Sprint-back recovery (turnover drill)", {"transition": 1.0, "help_defense": .3}, 8, 6,
      intensity="high", tags=("conditioning", "transition", "competitive"),
      setup="Coach blows the whistle and flips the ball to the other team; last player back runs.",
      cue="Sprint to the paint first, then find a man.", metric="All 5 behind the ball within 4 s."),
    D("11-man-break", "11-man fast break", {"transition": .9, "rim_finishing": .4, "playmaking": .3}, 10, 11,
      max_players=15, intensity="high", tags=("conditioning", "transition"),
      setup="Continuous 3-on-2 with outlets on both sides.", cue="Fill the lanes wide, run ahead of the ball.",
      metric="Score within 6 s on 60% of reps."),
    D("suicide-ladders", "Conditioning ladders with a ball", {"transition": .8, "ball_security": .2}, 6, 1, solo=True,
      intensity="high", tags=("conditioning",), setup="Line drills dribbling, alternating hands each line.",
      cue="Touch every line, change hands at the turn.", metric="Under 32 s per ladder."),
    # ---- team / game
    D("controlled-scrimmage", "Controlled scrimmage with emphasis scoring", {"playmaking": .4, "help_defense": .4,
      "rebounding": .3, "transition": .3}, 15, 10, intensity="high", tags=("competitive", "game-like"),
      setup="5-on-5; bonus points for the week's emphasis (e.g. a stop + defensive rebound).",
      cue="Play the emphasis, not just the score.", metric="Emphasis bonus earned on 50% of possessions."),
    D("late-game-situations", "Late-game situations", {"free_throw": .4, "ball_security": .4, "playmaking": .3},
      10, 10, tags=("game-like", "competitive"), setup="Up/down 3 with 40 s left: fouling, timeouts, sideline out-of-bounds plays.",
      cue="Know the score, know the clock.", metric="Execute the correct decision in each scenario."),
]
FULL_COURT = {"dynamic-warmup", "advantage-3v2-2v1", "zig-zag-defense", "sprint-back-recovery", "11-man-break",
              "no-dribble-scrimmage", "controlled-scrimmage", "suicide-ladders"}
LIBRARY = [replace(d, full_court=True) if d.id in FULL_COURT else d for d in LIBRARY]
BY_ID = {d.id: d for d in LIBRARY}
INTENSITY = {"low": 0, "medium": 1, "high": 2}


# ------------------------------------------------------------ preference model
def preference_weights(feedback: list[dict], lib: list[Drill] | None = None) -> dict[str, float]:
    """Learn a multiplier per drill from the coach's feedback history.

    Each feedback row: {"drill_id", "rating" in [-1, 1], "ran": bool}. Ratings
    are generalised through tags (a coach who dislikes one rebounding-war style
    drill probably dislikes similar ones), then shrunk toward 0 with a pseudo-
    count so a single rating moves the needle but does not dominate.
    """
    lib = lib or LIBRARY
    by_id = {d.id: d for d in lib}
    drill_sum: dict[str, float] = {}
    drill_n: dict[str, int] = {}
    tag_sum: dict[str, float] = {}
    tag_n: dict[str, int] = {}
    for f in feedback:
        did = f.get("drill_id")
        if did not in by_id:
            continue
        r = float(f.get("rating") or 0.0) + (0.3 if f.get("ran") else 0.0)
        drill_sum[did] = drill_sum.get(did, 0.0) + r
        drill_n[did] = drill_n.get(did, 0) + 1
        for t in by_id[did].tags:
            tag_sum[t] = tag_sum.get(t, 0.0) + r
            tag_n[t] = tag_n.get(t, 0) + 1
    out = {}
    for d in lib:
        da = drill_sum.get(d.id, 0.0) / (drill_n.get(d.id, 0) + 1.0)
        tags = [tag_sum.get(t, 0.0) / (tag_n.get(t, 0) + 2.0) for t in d.tags]
        ta = sum(tags) / len(tags) if tags else 0.0
        out[d.id] = round(math.exp(0.9 * da + 0.5 * ta), 3)
    return out


# ------------------------------------------------------------ recommender
@dataclass
class PlanRequest:
    minutes: int = 90
    players: int = 12
    hoops: int = 2
    max_intensity: str = "high"      # e.g. "medium" the day before a game
    focus: list = field(default_factory=list)   # dimensions the coach wants emphasised
    exclude: list = field(default_factory=list)
    include_warmup: bool = True
    full_court: bool = True          # False = half court / a single gym corner


def _eligible(d: Drill, req: PlanRequest) -> bool:
    return (d.min_players <= req.players and d.hoops <= max(req.hoops, 1)
            and INTENSITY[d.intensity] <= INTENSITY[req.max_intensity]
            and (req.full_court or not d.full_court)
            and d.id not in req.exclude)


def plan_practice(team_need: dict[str, float], req: PlanRequest,
                  prefs: dict[str, float] | None = None,
                  who_needs: dict[str, list[str]] | None = None,
                  lib: list[Drill] | None = None) -> dict:
    """Greedy, time-budgeted plan. Each pick maximises (need covered x coach
    preference) per minute; the need it covers is then discounted so the plan
    spreads across the team's top problems instead of repeating one theme."""
    prefs = prefs or {}
    need = dict(team_need)
    for f in req.focus:
        need[f] = need.get(f, 0.0) + max(need.values() or [0.1]) * 0.8 + 0.05
    remaining = req.minutes
    blocks, used = [], set()
    pool = [d for d in (lib or LIBRARY) if _eligible(d, req) and "film" not in d.tags]

    def add(d: Drill, why: str):
        nonlocal remaining
        blocks.append({"drill": d.to_dict(), "minutes": d.minutes, "why": why,
                       "focus_players": [] if "warmup" in d.tags else
                       sorted({p for dim in d.targets for p in (who_needs or {}).get(dim, [])[:3]}),
                       "preference": prefs.get(d.id, 1.0)})
        used.add(d.id)
        remaining -= d.minutes
        for dim, w in d.targets.items():
            if dim in need:
                need[dim] *= (1 - 0.55 * w)

    if req.include_warmup:
        warm = [d for d in pool if "warmup" in d.tags and d.minutes <= remaining]
        if warm:
            w = max(warm, key=lambda d: prefs.get(d.id, 1.0))
            add(w, "Warm-up")
    while remaining >= 6:
        best, best_score = None, 0.0
        for d in pool:
            if d.id in used or d.minutes > remaining or "warmup" in d.tags:
                continue
            cover = sum(need.get(dim, 0.0) * w for dim, w in d.targets.items())
            score = cover * prefs.get(d.id, 1.0) / math.sqrt(d.minutes)
            if score > best_score:
                best, best_score = d, score
        if best is None or best_score < 1e-4:
            break
        top = sorted(((need.get(dim, 0) * w, dim) for dim, w in best.targets.items()), reverse=True)[:2]
        why = "Targets " + " + ".join(dim.replace("_", " ") for _, dim in top if _ > 0)
        add(best, why)
    return {"blocks": blocks, "total_minutes": req.minutes - remaining, "unfilled_minutes": remaining}


def homework_for(dimension: str, prefs: dict[str, float] | None = None, exclude=(),
                 lib: list[Drill] | None = None) -> Drill | None:
    prefs = prefs or {}
    lib = lib or LIBRARY
    cands = [d for d in lib if d.solo and d.targets.get(dimension, 0) >= 0.5 and d.id not in exclude]
    if not cands:
        cands = [d for d in lib if d.solo and dimension in d.targets and d.id not in exclude]
    if not cands:
        return None
    return max(cands, key=lambda d: d.targets[dimension] * prefs.get(d.id, 1.0))


def drill_from_dict(d: dict) -> Drill:
    return Drill(id=d["id"], name=d["name"], targets=dict(d["targets"]), minutes=int(d["minutes"]),
                 min_players=int(d["min_players"]), max_players=int(d.get("max_players") or 99),
                 hoops=int(d.get("hoops", 1)), intensity=d.get("intensity", "medium"), solo=bool(d.get("solo")),
                 tags=tuple(d.get("tags") or ()) + ("custom",), setup=d.get("setup", ""), cue=d.get("cue", ""),
                 metric=d.get("metric", ""), full_court=bool(d.get("full_court")))
