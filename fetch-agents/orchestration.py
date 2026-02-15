"""
Orchestration using LangGraph: route queries to direct answer or delegate to specialist.
"""
import json
import os
from typing import Literal, TypedDict
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from langgraph.graph import StateGraph, START, END
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False
    StateGraph = None


class RouterState(TypedDict, total=False):
    query: str
    action: str  # "direct" | "delegate"
    response: str


def _is_digest_request(query: str) -> bool:
    q = (query or "").strip().lower()
    triggers = (
        "digest",
        "summary",
        "market snapshot",
        "top questions",
        "status report",
    )
    return any(t in q for t in triggers)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _safe_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _shorten(text: str, limit: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)] + "..."


def _fetch_json(url: str, timeout: float = 6.0) -> dict:
    req = Request(
        url,
        headers={
            "User-Agent": "HackOverflow-FetchAgents/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if isinstance(data, dict):
        return data
    return {}


def _build_hackoverflow_context(query: str) -> str:
    """
    Pull relevant Q&A context from HackOverflow API for grounded coordinator answers.
    """
    if not _env_flag("AI_GATEWAY_PULL_CONTEXT", True):
        return ""
    search = " ".join((query or "").split()[:8]).strip()
    if not search:
        search = "python error agent debugging"

    api_base = os.getenv("HACKOVERFLOW_API_URL", "http://127.0.0.1:8000").rstrip("/")
    max_questions = max(1, _safe_int("AI_GATEWAY_CONTEXT_QUESTIONS", 2))
    max_question_chars = max(80, _safe_int("AI_GATEWAY_CONTEXT_QUESTION_CHARS", 220))
    max_answer_chars = max(80, _safe_int("AI_GATEWAY_CONTEXT_ANSWER_CHARS", 260))

    questions_url = f"{api_base}/questions?{urlencode({'search': search, 'sort': 'top', 'page': 1})}"
    try:
        questions_payload = _fetch_json(questions_url)
    except Exception:
        return ""

    questions = questions_payload.get("questions") or []
    if not isinstance(questions, list) or not questions:
        return ""

    context_lines: list[str] = []
    for idx, q in enumerate(questions[:max_questions], start=1):
        if not isinstance(q, dict):
            continue

        question_id = str(q.get("id", "")).strip()
        title = _shorten(str(q.get("title", "")), max_question_chars)
        body = _shorten(str(q.get("body", "")), max_question_chars)
        score = q.get("score", 0)
        answer_count = q.get("answer_count", 0)
        line = f"{idx}) Q(score={score}, answers={answer_count}) title={title}; body={body}"

        if question_id and isinstance(answer_count, int) and answer_count > 0:
            answers_url = f"{api_base}/questions/{question_id}/answers?{urlencode({'sort': 'top', 'page': 1})}"
            try:
                answers_payload = _fetch_json(answers_url)
                answers = answers_payload.get("answers") or []
                if isinstance(answers, list) and answers and isinstance(answers[0], dict):
                    top_answer = _shorten(str(answers[0].get("body", "")), max_answer_chars)
                    if top_answer:
                        line += f"; top_answer={top_answer}"
            except Exception:
                pass

        context_lines.append(line)

    return "\n".join(context_lines)


def _get_ai_gateway_response(query: str, context: str) -> str | None:
    """
    Use Vercel AI Gateway (OpenAI-compatible endpoint) with cross-provider fallback.
    """
    gateway_enabled = _env_flag("AI_GATEWAY_ENABLED", True)
    gateway_key = (
        os.getenv("AI_GATEWAY_API_KEY")
        or os.getenv("VERCEL_AI_GATEWAY_API_KEY")
        or ""
    ).strip()
    if not gateway_enabled or not gateway_key:
        return None

    try:
        from openai import OpenAI
    except Exception:
        return None

    base_url = os.getenv("AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v1").strip()
    primary_model = os.getenv("AI_GATEWAY_PRIMARY_MODEL", "openai/gpt-4o-mini").strip()
    fallback_raw = os.getenv(
        "AI_GATEWAY_FALLBACK_MODELS",
        "anthropic/claude-3.5-haiku,google/gemini-2.0-flash-001",
    )
    fallback_models = [
        m.strip()
        for m in fallback_raw.split(",")
        if m.strip() and m.strip() != primary_model
    ]

    system_prompt = (
        "You are generating a short operational digest for an AI-agent Q&A platform. "
        "Use retrieved context only. Keep it concise and actionable."
    )
    user_prompt = (
        f"Request:\n{query}\n\n"
        f"Retrieved HackOverflow context:\n{context if context else '(none)'}\n\n"
        "Return:\n"
        "1) Top patterns (3 bullets)\n"
        "2) Fast actions for agents (2 bullets)\n"
        "3) One-line risk note"
    )

    try:
        client = OpenAI(base_url=base_url, api_key=gateway_key)
        request_kwargs = {}
        if fallback_models:
            request_kwargs["extra_body"] = {"models": fallback_models}
        result = client.chat.completions.create(
            model=primary_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
            **request_kwargs,
        )
        if result.choices and result.choices[0].message.content:
            return result.choices[0].message.content
    except Exception:
        return None

    return None


def should_delegate_to_specialist(query: str) -> bool:
    """Decide if the query should be handled by the specialist agent."""
    q = (query or "").strip().lower()
    if not q:
        return False
    # Direct path is reserved for platform digest/status requests.
    # Real user problem questions should be answered by specialist agents.
    if _is_digest_request(q):
        return False
    return True


def get_direct_response(query: str) -> str:
    """Generate direct coordinator output for non-question utilities (digest/status)."""
    if not query or not query.strip():
        return "Please ask a question about HackOverflow, agents, or ASI:One."

    if not _is_digest_request(query):
        return (
            "I route technical questions to specialist agents. "
            "Ask your coding question normally and I will delegate it. "
            "Use words like 'digest' or 'summary' if you want a platform snapshot."
        )

    context = _build_hackoverflow_context(query)
    gateway_response = _get_ai_gateway_response(query, context)
    if gateway_response:
        primary = os.getenv("AI_GATEWAY_PRIMARY_MODEL", "openai/gpt-4o-mini").strip()
        fallbacks = os.getenv(
            "AI_GATEWAY_FALLBACK_MODELS",
            "anthropic/claude-3.5-haiku,google/gemini-2.0-flash-001",
        ).strip()
        return (
            "Vercel AI Gateway Digest\n"
            f"Primary: {primary}\n"
            f"Fallbacks: {fallbacks}\n\n"
            f"{gateway_response}"
        )

    # Non-LLM fallback still provides visible value.
    return (
        "Vercel AI Gateway Digest unavailable right now.\n"
        "Top questions are still being pulled from HackOverflow API, but model summarization failed."
    )


def run_orchestration(query: str) -> tuple[Literal["direct", "delegate"], str]:
    """
    Run LangGraph orchestration: route to direct answer or delegate.
    Returns (action, response). If action is "delegate", response is empty (caller sends to specialist).
    """
    if _LANGGRAPH_AVAILABLE and StateGraph is not None:
        try:
            graph = StateGraph(RouterState)

            def route(state: RouterState) -> RouterState:
                q = state.get("query") or ""
                if should_delegate_to_specialist(q):
                    return {"action": "delegate", "response": ""}
                resp = get_direct_response(q)
                return {"action": "direct", "response": resp}

            graph.add_node("route", route)
            graph.add_edge(START, "route")
            graph.add_edge("route", END)
            app = graph.compile()
            initial = {"query": query, "action": "direct", "response": ""}
            result = app.invoke(initial)
            action = result.get("action") or "direct"
            response = result.get("response") or ""
            return action, response
        except Exception:
            pass
    # Fallback without LangGraph
    if should_delegate_to_specialist(query):
        return ("delegate", "")
    return ("direct", get_direct_response(query))
