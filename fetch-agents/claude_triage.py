"""
Optional Claude Agent SDK integration for curator triage.

This is a helper layer. Fetch.ai/uAgents routing remains primary.
If SDK is unavailable or disabled, we gracefully fall back to heuristics.
"""
import os
from typing import Any

from models import Question


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _compact(text: str, limit: int = 800) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."


def _heuristic_lane(q: Question) -> str:
    e = (q.error_message or "").lower()
    c = (q.code or "").lower()
    urgent_markers = (
        "oom",
        "out of memory",
        "segmentation fault",
        "panic",
        "timeout",
        "connection refused",
        "permission denied",
    )
    if q.bounty > 0 or any(m in e or m in c for m in urgent_markers):
        return "fast-lane"
    return "deep-lane"


def heuristic_triage(q: Question) -> dict[str, Any]:
    lane = _heuristic_lane(q)
    actions: list[str] = [
        "Reproduce with a minimal snippet.",
        "Capture full traceback and environment versions.",
    ]
    if lane == "fast-lane":
        actions.insert(0, "Prioritize immediate unblock and quick rollback path.")

    summary = (
        f"Heuristic triage for {q.language or 'unknown'} error: "
        f"{_compact(q.error_message, 180)}"
    )
    return {
        "lane": lane,
        "summary": summary,
        "actions": actions,
        "source": "heuristic",
    }


def _build_prompt(q: Question) -> str:
    return (
        "You are a triage coordinator for AI coding agents.\n"
        "Return strict JSON with keys: lane, summary, actions.\n"
        "lane must be one of: fast-lane, deep-lane.\n"
        "summary must be <= 200 chars.\n"
        "actions must be an array with 2-3 short action strings.\n\n"
        f"Language: {q.language}\n"
        f"Error: {q.error_message}\n"
        f"Tags: {q.tags}\n"
        f"Bounty: {q.bounty}\n"
        f"Code:\n{q.code[:2000]}"
    )


def _extract_text(event: Any) -> str:
    """
    Best-effort extraction from streamed SDK events.
    """
    for attr in ("text", "content", "message"):
        value = getattr(event, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(event, str):
        return event.strip()
    return ""


def _parse_json_blob(text: str) -> dict[str, Any] | None:
    import json
    text = (text or "").strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    blob = text[start : end + 1]
    try:
        data = json.loads(blob)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


async def claude_sdk_triage(q: Question) -> dict[str, Any] | None:
    """
    Run triage using Claude Agent SDK if enabled and available.
    """
    if not _env_flag("CLAUDE_TRIAGE_ENABLED", False):
        return None

    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
    except Exception:
        return None

    prompt = _build_prompt(q)
    allowed_tools_raw = os.getenv("CLAUDE_TRIAGE_ALLOWED_TOOLS", "").strip()
    allowed_tools = [t.strip() for t in allowed_tools_raw.split(",") if t.strip()]
    max_tokens_raw = os.getenv("CLAUDE_TRIAGE_MAX_TOKENS", "").strip()
    request_kwargs: dict[str, Any] = {}
    if max_tokens_raw:
        try:
            request_kwargs["max_output_tokens"] = int(max_tokens_raw)
        except ValueError:
            pass

    try:
        options = ClaudeAgentOptions(allowed_tools=allowed_tools, **request_kwargs)
        chunks: list[str] = []
        async for event in query(prompt=prompt, options=options):
            text = _extract_text(event)
            if text:
                chunks.append(text)
        joined = "\n".join(chunks).strip()
        parsed = _parse_json_blob(joined)
        if not parsed:
            return None
        lane = str(parsed.get("lane", "")).strip().lower()
        if lane not in {"fast-lane", "deep-lane"}:
            lane = _heuristic_lane(q)
        summary = _compact(str(parsed.get("summary", "")).strip(), 200)
        actions_raw = parsed.get("actions")
        actions: list[str] = []
        if isinstance(actions_raw, list):
            for item in actions_raw:
                item_text = _compact(str(item), 120)
                if item_text:
                    actions.append(item_text)
        if not actions:
            actions = heuristic_triage(q)["actions"]
        return {
            "lane": lane,
            "summary": summary or heuristic_triage(q)["summary"],
            "actions": actions[:3],
            "source": "claude-sdk",
        }
    except Exception:
        return None


async def get_triage_plan(q: Question) -> dict[str, Any]:
    """
    Try Claude SDK triage first, fall back to deterministic heuristics.
    """
    plan = await claude_sdk_triage(q)
    if plan:
        return plan
    return heuristic_triage(q)

