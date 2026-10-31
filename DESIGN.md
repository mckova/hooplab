---
version: alpha
name: HoopLab
description: The coach's board. A light, dense working surface for a basketball coach, drawn in ink with one orange for our team and our actions.
colors:
  canvas: "#f4f4f0"
  rail: "#e9eae4"
  surface: "#fcfcfa"
  ink: "#14171c"
  ink-soft: "#575d66"
  ink-faint: "#8a9098"
  line: "#dcded7"
  line-strong: "#bfc2b9"
  accent: "#b8430f"
  accent-ink: "#fff8f2"
  accent-wash: "#f7e6da"
  good: "#1d7a47"
  bad: "#b42318"
typography:
  body:
    fontFamily: Archivo
    fontSize: 16px
    lineHeight: 1.55
    fontWeight: 400
  hebrew:
    fontFamily: Rubik
  page-title:
    fontFamily: Archivo
    fontSize: 40px
    lineHeight: 1.02
    fontWeight: 760
    letterSpacing: -0.012em
  section-title:
    fontFamily: Archivo
    fontSize: 21px
    lineHeight: 1.15
    fontWeight: 700
  jersey:
    fontFamily: Archivo
    fontSize: 80px
    lineHeight: 0.8
    fontWeight: 780
    letterSpacing: -0.02em
rounded:
  ctl: 4px
  surface: 6px
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
the bench. It reads like the coach's whiteboard: off-white board, marker ink,
one orange. Dials: density 2 of 3 (a working tool, many numbers per screen),
energy 2, rhythm 2, motion 1 (motion explains a change, it never decorates).

The interface is light only. Coaches read it in bright gyms and on printed
scouting reports, and a light ground prints as it looks on screen.

## Colors

- `accent` means our team and the primary action, nothing else. Opponents are
  drawn in `ink`. One filled accent button per screen.
- `good` and `bad` only carry a number's direction against what is expected.
  They never decorate.
- `ink-faint` is for marks (ticks, axes), never for text.
- Surfaces are separated by hairlines in `line`, not by shadows or tinted
  cards. Elevation is reserved for the dialog and the toast.

## Typography

- Archivo everywhere. Headings, jersey numbers and table numerals use its
  width axis at 72% for a condensed scoreboard cut; body text stays at normal
  width. Hebrew falls back to Rubik.
- All numbers are tabular so columns line up.
- Headings name their subject ("Shot chart", "Keys to the game"). No eyebrows
  or labels above headings.

## Layout

- A fixed left rail holds the team and the sections; under 900px it becomes a
  top bar with the sections in one scrolling row.
- Lists are rows with hairlines, not grids of cards. Wide tables sit in their
  own horizontal scroll container.
- Practice plans are set on the clock (18:00, 18:08), as the coach writes them.
- Names are never truncated; they wrap.

## Shapes

- Controls use `rounded.ctl`, surfaces `rounded.surface`. Nothing is pill
  shaped except the player disc on the court diagrams.

## Components

- Shot chart: a half court whose zones are tinted green or red by the gap
  against the positional expectation. Each zone is a button that plays those
  shots.
- Skill row: estimate dot, likely range band, and a tick for what the
  position expects. Never a filled progress bar.
- Text written by Claude ends with a one-line provenance note saying whether
  Claude wrote it or it was drafted from the numbers.

## Do's and Don'ts

- Do keep body and input text at 16px and give every control a 44px target on
  touch screens.
- Do respect reduced motion; animate only `transform` and `opacity`, under
  250 ms, with the ease-out curve.
- Don't use em dashes, emoji, sparkle icons, gradients or "AI" badges.
- Don't put more than one middle dot in a line of text.
