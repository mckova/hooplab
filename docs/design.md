# Design notes

HoopLab closes one loop: **film → per-player model → practice plan → homework →
re-measure**. These are the decisions that shape it.

## Data in

1. **File contract between detection and analytics.** Any tracker can feed
   HoopLab by writing the [track format](track-format.md). The bundled YOLO
   backend is optional, so the platform runs on a laptop without a GPU.
2. **Relative-velocity gate for possession.** A held ball moves *with* its
   holder. If the ball moves relative to a player faster than 0.08 box-heights
   per frame, that player cannot be holding it, so a shot arc passing over a
   forward never becomes a "pass".
3. **Shots break the possession chain.** A holder change with a shot in
   between is a rebound or inbound, never a pass or turnover. A dead ball (no
   ball seen for at least a second) resets the chain too.
4. **Shot zone from court coordinates.** The shooter's foot point at release is
   projected through a homography fitted to four court corners, giving rim / mid
   / three by FIBA distances instead of image heuristics.
5. **Events are the unit of learning.** Every detected or tagged
   event maps to a skill dimension with a success/failure outcome, so video,
   bench tagging, CSV imports, coach notes read by Claude and homework logs all
   feed one model, each at its own weight.

## The model

6. **Bayesian player model.** Beta posteriors with position-specific priors and
   a time-decay half-life. A strength or weakness is only claimed when the 80%
   interval clears the position baseline, so thin data says "not sure yet"
   instead of guessing.
7. **Trends must be significant.** A linear-probability slope test with
   |z| ≥ 2.8 (strict, because ~80 player-dimension pairs are tested at once).
8. **Coach preferences generalise through tags.** A thumbs-down on one drill
   lowers similar drills too, shrunk toward neutral so one click does not
   dominate.

## Film is the evidence

9. **Every number opens its clips.** Each event keeps a clip window
   (`t_start`, `t_end`) in its session's video. Skills, play types and
   opponent tendencies all open a clip player that plays exactly those
   possessions, one after another.
10. **Playlists ride along with homework.** When homework is assigned, HoopLab
    builds a playlist of the player's own misses in that skill: "watch these
    five possessions, then do the drill".
11. **Play types with points per possession.** Possession-ending events (shots
    and turnovers) carry a play type (pick & roll, spot-up, post-up, cut, …).
    PPP, frequency and turnover rate per play type give the team self-scout,
    a per-player view and how an opponent scores. Free throws are not
    possessions, and samples under 5 are flagged as unreliable.
12. **A one-page scouting report written by Claude, numbers by the engine.**
    The report is generated from a fact sheet (head-to-head, game plan, their
    play types, ours); the model may only quote those numbers. Without an API
    key the same facts render through a template.

## AI-native

13. **The agent operates the model, it does not replace it.** The assistant
    coach is a tool-use loop over 16 strict-schema tools (snapshot, player,
    matchup, plan, homework, log events, play types, playlists, custom drills,
    coach memory, …). Every statistic it quotes is a tool result.
14. **Structured outputs for perception.** Coach notes and film frames become
    validated `Extraction` objects (Pydantic), matched to the roster, and stored
    at reduced weight (0.7 for notes, 0.5 for film AI) so they inform but do not
    dominate tracked data.

15. **Claude inside the loop.** Every import of a game or practice
    triggers a debrief: the engine compares each player with their own
    estimate *before* that session (a z-score per skill, flagged at |z| ≥ 1.5
    with at least 4 attempts), Claude writes it up, and it lands in the coach's
    inbox. Player messages follow the same split: facts from the model,
    words from Claude, and "progress" only when a trend is significant.
16. **Ask from anywhere.** Buttons on players, plans, opponents and inbox items
    open the assistant with a short description of what the coach is looking
    at, so "is he getting better?" resolves to the right player.
17. **Prompt caching by design.** Tools and the stable instructions form a
    cached prefix; team context and coach memory come after the breakpoint, and
    the growing conversation is cached turn to turn.

## Interface

The interface is frosted glass over soft ambient light, in light and dark
modes (the first visit follows the system setting; the choice is kept per
device). One typeface, Albert Sans, at two weights. Colour has fixed jobs:
orange is the ball and nothing else on the court, our players are solid discs,
opponents are court-blue rings, mint marks stops and makes, clay marks misses
and baskets given up. The full system (colours, type, spacing, rules) is in
[DESIGN.md](../DESIGN.md).

* Every page opens with a sentence, not a label: "Scored 7 on 3 of 5
  shooting. Five players jogged back after a turnover."
* Film review is the main screen: the film with its tagged moments as
  coloured ticks on the timeline, the assistant coach's read with what to do
  next, a filterable list of moments, and the numbers under the film.
* The half-court shot chart: each zone shows the player's rate against what
  the position expects, and selecting a zone plays those shots.
* Practice plans are laid out on the clock (18:00, 18:08...), the way a coach
  writes them.
* Motion only on `transform` and `opacity`, under 250 ms, with a strong
  ease-out; dialogs and toasts enter with `@starting-style`; reduced motion
  removes movement.
* Accessible by default: real buttons for every action, labelled icon
  buttons, a dialog that traps focus and returns it, keyboard-operable table
  rows, visible focus, 44px targets on touch screens, `aria-live` status
  messages.
* Destructive actions confirm in place; no browser `prompt()` or `confirm()`.

## Validation

* Synthetic scenes (`hooplab/vision/synth.py`) render scripted possessions as
  track files; tests assert the exact passes, assist, made three, missed
  mid-range, defensive rebound, steal and sprint-backs are recovered, and that
  the demo film's play types and clip windows survive ingest.
* The demo team has hidden "true" skills and play-type tendencies. On the
  dimensions where players differ from their position's baseline, the model's
  mean absolute error is ~0.04 vs ~0.10 for the prior alone; the two injected
  improvements are detected as significant trends; and each opponent's seeded
  best play type is recovered (seeded, reproducible: `pytest`).
