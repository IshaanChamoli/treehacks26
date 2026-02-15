"""Shared utilities for Fetch.ai uAgents (chat message helpers)."""
from datetime import datetime, timezone
from uuid import uuid4

from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    EndSessionContent,
    TextContent,
)


def create_text_chat(text: str, end_session: bool = False) -> ChatMessage:
    """Create a ChatMessage with optional EndSessionContent."""
    content: list = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=content,
    )
