---
version: beta
name: HoopLab
description: Frosted glass over soft ambient light, light and dark. A film-first working tool for a basketball coach, where colour on the court always means the same thing.
colors:
  light:
    canvas: "#e9ebef"
    surface: "rgb(255 255 255 / .62)"
    surface-strong: "rgb(255 255 255 / .92)"
    ink: "rgb(16 18 22 / .94)"
    ink-soft: "rgb(16 18 22 / .60)"
    ink-faint: "rgb(16 18 22 / .34)"
    line: "rgb(16 18 22 / .08)"
    accent: "#e8661c"
    good: "#1f8f66"
    bad: "#cf4634"
    us: "#16191e"
    them: "#4c6bc0"
    ball: "#f07c2c"
    floor: "#fbfbfc"
  dark:
    canvas: "#0e1013"
    surface: "rgb(255 255 255 / .065)"
    surface-strong: "rgb(255 255 255 / .13)"
    ink: "rgb(255 255 255 / .95)"
    ink-soft: "rgb(255 255 255 / .62)"
    ink-faint: "rgb(255 255 255 / .34)"
    line: "rgb(255 255 255 / .08)"
    accent: "#ff8a4c"
    good: "#7ed3b0"
    bad: "#f07a6a"
    us: "#eef0f4"
    them: "#7f9de6"
    ball: "#f07c2c"
    floor: "#14171c"
typography:
  body:
    fontFamily: Albert Sans
    fontSize: 16px
    lineHeight: 1.5
    fontWeight: 400
  hebrew:
    fontFamily: Rubik
  headline:
    fontFamily: Albert Sans
    fontSize: 44px
    lineHeight: 1.05
    fontWeight: 500
    letterSpacing: -0.028em
  section-title:
    fontFamily: Albert Sans
    fontSize: 17px
    lineHeight: 1.25
    fontWeight: 500
  stat:
    fontFamily: Albert Sans
    fontSize: 30px
    fontWeight: 400
    letterSpacing: -0.02em
rounded:
  ctl: 12px
  row: 14px
  bar: 20px
  surface: 24px
spacing:
  s1: 4px
  s2: 8px
  s3: 12px
  s4: 16px
  s5: 20px
  s6: 24px
  s8: 32px
  s10: 40px
  s12: 48px
  s16: 64px
  s20: 80px
---

## Overview

HoopLab is the tool a basketball coach keeps open between practices and on
the bench. Film review is the centre of it: what happened, shown on the film,
with the assistant's read beside it. Dials: density 2 of 3, energy 2,
rhythm 2, motion 1 (motion explains a change, it never decorates).

## Material

- Every panel is the same frosted glass: `surface` with a 28px backdrop blur,
  a 1px inner edge and a soft shadow, radius `surface`.
- Colour lives in the ambient light behind the glass (a warm and a cool
  radial glow on `canvas`), never in the panels themselves.
- Light and dark are equal citizens. The first visit follows the system
  setting; the coach's choice is kept on the device.
- Panels never nest: a panel inside a panel loses its glass.

## Colors

Colours have one job each, everywhere, including the court and the film.

- `ball` is the ball. Nothing else on a court drawing is orange.
- `us` is our team: solid discs with the jersey number knocked out.
- `them` is the opponent: rings in court blue with the number in blue.
- `good` (mint) marks stops, makes and a number above expectation; `bad`
  (clay) marks misses, baskets given up and a number below expectation.
- `accent` (ember) is the selected item, the primary action and the one
  phrase in a headline that matters. One filled accent button per screen.
- There are no black buttons. Secondary actions are text with an accent arrow.

## Typography

- Albert Sans at 400 and 500 only (600 for the wordmark). Hebrew falls back
  to Rubik.
- Each page opens with a headline sentence, not a label: "Scored 7 on 3 of 5
  shooting. Five players jogged back after a turnover." Above it, a quiet
  kicker says which game, team or player it is about.
- Numbers are tabular. Stats are large and light; their labels are small and
  faint.

## Layout

- A glass top bar: wordmark, sections as text, the ask bar, the team, and a
  More menu (language, appearance, new team, demo). Under 900px the sections
  move to their own scrolling row.
- Film review: film on the left with its control bar floating over it, the
  assistant coach card and the list of moments on the right, numbers under
  the film. On a phone the controls sit under the film.
- Lists are rows with hairlines; the selected row becomes a raised glass row.
- Practice plans are set on the clock (18:00, 18:08), as the coach writes
  them. Names are never truncated; they wrap.

## Components

- Timeline: thin rule, one tick per tagged moment in `good` or `bad`, faint
  ticks every two seconds, a white playhead. It is a keyboard slider.
- Shot chart: a half court on `floor`, zones tinted `good` or `bad` by the gap
  against the positional expectation. Each zone plays its shots.
- Skill row: estimate dot, likely range band, and a tick for what the
  position expects. Never a filled progress bar.
- Text written by Claude ends with a one-line note saying whether Claude wrote
  it or it was drafted from the numbers.

## Do's and Don'ts

- Do keep body and input text at 16px and give every control a 44px target on
  touch screens.
- Do respect reduced motion; animate only `transform` and `opacity`, under
  250 ms, with the ease-out curve.
- Don't use em dashes, emoji, sparkle icons, avatars or "AI" badges.
- Don't colour a team with the ball's orange, and don't put more than one
  middle dot in a line of text.
