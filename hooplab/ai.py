"""Shared Claude client settings.

HoopLab is AI-native: the assistant-coach agent, note/film understanding,
custom drill design and the written briefing all run on Claude. The numeric
engine (skill model, trends, planner) stays deterministic so every number the
agent quotes can be traced back to data.
"""
from __future__ import annotations

import os

MODEL = os.environ.get("HOOPLAB_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("HOOPLAB_EFFORT", "medium")

# Server-side refusal fallback: if a safety classifier declines a request, the
# API re-runs it on a suitable model inside the same call (category-routed).
FALLBACK_KW = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


class AIUnavailable(RuntimeError):
    pass


_client = None


def get_client():
    """Anthropic client, or AIUnavailable when the SDK/credentials are missing.
    Credentials resolve the SDK's usual way (ANTHROPIC_API_KEY, auth token or
    an `ant auth login` profile)."""
    global _client
    if _client is not None:
        return _client
    try:
        import anthropic
    except ImportError as exc:
        raise AIUnavailable("install the AI extra: pip install hooplab[ai]") from exc
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_PROFILE") or os.path.exists(
                os.path.expanduser("~/.config/anthropic"))):
        raise AIUnavailable("set ANTHROPIC_API_KEY (or run `ant auth login`) to enable the AI features")
    _client = anthropic.Anthropic()
    return _client


def set_client(client) -> None:
    """Inject a client (tests, or a custom-configured one)."""
    global _client
    _client = client


def available() -> bool:
    try:
        get_client()
        return True
    except AIUnavailable:
        return False


def dump_block(block) -> dict:
    """Content block -> JSON-able dict, passed back to the API unchanged
    (thinking blocks included, which keeps the conversation append-only)."""
    if isinstance(block, dict):
        return block
    return block.model_dump(mode="json", exclude_none=True)


def text_of(response) -> str:
    return "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text").strip()
