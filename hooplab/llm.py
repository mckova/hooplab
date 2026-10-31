"""Weekly coach briefing written by Claude from the structured team model.
Falls back to a template when Claude is not configured, so pages never break."""
from __future__ import annotations

import json

from . import ai

MODEL = ai.MODEL


def template_briefing(snap: dict) -> str:
    lines = [f"Team snapshot for {snap['team']['name']}"]
    if snap["priorities"]:
        lines.append("Team priorities: " + ", ".join(p["name"] for p in snap["priorities"][:3]) + ".")
    for x in snap["exploit"][:3]:
        lines.append(f"Use {x['player']}: {x['name'].lower()} at {x['mean']:.0%} (expected {x['baseline']:.0%}).")
    for c in snap["players"]:
        if c["weaknesses"]:
            w = c["weaknesses"][0]
            lines.append(f"{c['player']['name']}: work on {w['name'].lower()} ({w['mean']:.0%} vs {w['baseline']:.0%}).")
    for t in snap["trends"][:3]:
        arrow = "up" if t["trend"] > 0 else "down"
        lines.append(f"Trend: {t['player']} {t['name'].lower()} {arrow}: {t['before']:.0%} -> {t['recent']:.0%} in the last 3 weeks.")
    if snap["data_coverage"]["players_with_little_data"]:
        lines.append("Little data yet on: " + ", ".join(snap["data_coverage"]["players_with_little_data"]) + ".")
    return "\n".join(lines)


def briefing(snap: dict, language: str = "en") -> dict:
    try:
        client = ai.get_client()
    except ai.AIUnavailable:
        return {"source": "template", "text": template_briefing(snap)}
    compact = {
        "team": snap["team"]["name"], "priorities": snap["priorities"], "exploit": snap["exploit"],
        "trends": snap["trends"],
        "players": [{"name": c["player"]["name"], "position": c["player"]["position"],
                     "strengths": [(s["name"], s["mean"], s["baseline"]) for s in c["strengths"]],
                     "weaknesses": [(w["name"], w["mean"], w["baseline"]) for w in c["weaknesses"]],
                     "events": c["events"]} for c in snap["players"]],
    }
    lang = "Hebrew" if language == "he" else "English"
    prompt = (f"Write the head coach's weekly briefing in {lang}, at most 180 words: 1) state of the team, "
              "2) what to exploit and with whom, 3) who works on what. Use only the numbers in the data and say "
              "where data is thin.\n\n<team_model>\n" + json.dumps(compact, ensure_ascii=False) + "\n</team_model>")
    try:
        msg = client.beta.messages.create(model=ai.MODEL, max_tokens=4000, output_config={"effort": "low"},
                                          messages=[{"role": "user", "content": prompt}], **ai.FALLBACK_KW)
        text = ai.text_of(msg)
        if msg.stop_reason == "refusal" or not text:
            raise RuntimeError(f"no text (stop_reason={msg.stop_reason})")
        return {"source": msg.model, "text": text}
    except Exception as exc:  # network / auth: degrade, don't fail the page
        return {"source": "template", "text": template_briefing(snap), "error": str(exc)[:200]}


# ------------------------------------------------------------------ opponent scouting report
def scouting_facts(matchup: dict, theirs: dict, ours: dict) -> dict:
    """Everything the one-page report may say, as numbers from the engine."""
    return {
        "opponent": (matchup.get("opponent") or {}).get("name"),
        "notes": (matchup.get("opponent") or {}).get("notes"),
        "comparison": matchup["comparison"], "game_plan": matchup["game_plan"],
        "their_play_types": theirs["play_types"], "their_overall_ppp": theirs["overall_ppp"],
        "our_play_types": ours["play_types"], "our_overall_ppp": ours["overall_ppp"],
    }


def template_scouting(f: dict) -> str:
    out = [f"# Scouting report: {f['opponent']}"]
    if f.get("notes"):
        out.append(f"_{f['notes']}_")
    tp = [r for r in f["their_play_types"] if r["reliable"]]
    if tp:
        out.append("\n## How they score")
        for r in tp[:4]:
            out.append(f"- **{r['name']}**: {r['frequency']:.0%} of possessions, {r['ppp']:.2f} points per possession")
        top = max(tp, key=lambda r: r["ppp"] * r["frequency"])
        out.append(f"\nTake away **{top['name'].lower()}** first.")
    if f["game_plan"]:
        out.append("\n## Game plan")
        for g in f["game_plan"][:4]:
            out.append(f"- {g['insight']} Evidence: {g['evidence']}.")
    op = [r for r in f["our_play_types"] if r["reliable"]]
    if op:
        best = max(op, key=lambda r: r["ppp"])
        out.append(f"\n## Our best weapon\n- **{best['name']}** at {best['ppp']:.2f} PPP over {best['possessions']} possessions.")
    edges = sorted([r for r in f["comparison"] if r["edge"] is not None], key=lambda r: r["edge"])
    if edges:
        out.append("\n## Edges")
        out.append(f"- Biggest edge for us: {edges[-1]['name']}, {edges[-1]['us']:.0%} against {edges[-1]['them']:.0%}.")
        out.append(f"- Biggest edge for them: {edges[0]['name']}, {edges[0]['them']:.0%} against {edges[0]['us']:.0%}.")
    return "\n".join(out)


def scouting_report(facts: dict, language: str = "en") -> dict:
    """One-page opponent report: Claude writes it, the engine owns every number."""
    try:
        client = ai.get_client()
    except ai.AIUnavailable:
        return {"source": "template", "text": template_scouting(facts)}
    lang = "Hebrew" if language == "he" else "English"
    prompt = (f"Write a one-page opponent scouting report in {lang} (Markdown, at most 300 words) for a "
              "youth basketball head coach. Sections: How they score (by play type), What to take away, "
              "How we attack them (our best play types and the game plan), Matchup edges, 3 keys to the game. "
              "Use only numbers from the facts, quote them, and say where a sample is small "
              "(reliable=false).\n\n<facts>\n" + json.dumps(facts, ensure_ascii=False) + "\n</facts>")
    try:
        msg = client.beta.messages.create(model=ai.MODEL, max_tokens=6000, output_config={"effort": "medium"},
                                          messages=[{"role": "user", "content": prompt}], **ai.FALLBACK_KW)
        text = ai.text_of(msg)
        if msg.stop_reason == "refusal" or not text:
            raise RuntimeError(f"no text (stop_reason={msg.stop_reason})")
        return {"source": msg.model, "text": text}
    except Exception as exc:
        return {"source": "template", "text": template_scouting(facts), "error": str(exc)[:200]}
