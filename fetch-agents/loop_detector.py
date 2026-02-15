"""
Loop detection for stuck agents — detects when an agent is in a failure loop
so it can post to HackOverflow instead of burning credit.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionResult:
    """Single step result (e.g. compile, run, test)."""
    status: str  # "success" | "failed" | "timeout"
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class LoopDetector:
    """
    Detects repetitive failures so the agent can ask HackOverflow for help.
    Usage: call record(result) after each attempt; when is_stuck() is True,
    post a Question to the HackOverflow router agent.
    """
    def __init__(self, loop_threshold: int = 5):
        self.history: list[ActionResult] = []
        self.loop_threshold = loop_threshold

    def record(self, result: ActionResult) -> None:
        self.history.append(result)
        # Keep only recent history
        if len(self.history) > self.loop_threshold * 2:
            self.history = self.history[-self.loop_threshold * 2 :]

    def is_stuck(self) -> bool:
        """True if the last loop_threshold results are all failures."""
        if len(self.history) < self.loop_threshold:
            return False
        recent = self.history[-self.loop_threshold :]
        return all(r.status == "failed" for r in recent)

    def last_error(self) -> str:
        """Last error message for including in a Question."""
        for r in reversed(self.history):
            if r.status == "failed" and r.message:
                return r.message
        return ""

    def reset(self) -> None:
        self.history.clear()
