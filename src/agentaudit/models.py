"""Core data types shared across the engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Verdict(StrEnum):
    """How an AI answer compares with the help centre.

    Precedence when more than one applies: incorrect > unsupported > partial > correct.
    """

    CORRECT = "correct"          # every material claim is supported and the question is answered
    PARTIAL = "partial"          # accurate, but leaves out something the customer needed
    INCORRECT = "incorrect"      # contradicts the help centre
    UNSUPPORTED = "unsupported"  # states material facts the help centre does not contain


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    body: str


@dataclass(frozen=True)
class Conversation:
    id: str
    topic: str
    question: str
    ai_answer: str
    handed_off: bool = False
    reopened_within_7d: bool = False
    csat: int | None = None


@dataclass
class Grade:
    conversation_id: str
    verdict: Verdict | None
    confidence: Confidence | None = None
    cited_articles: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    explanation: str = ""
    model: str = ""
    error: str | None = None

    @property
    def graded(self) -> bool:
        return self.verdict is not None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Grade:
        verdict = data.get("verdict")
        confidence = data.get("confidence")
        return cls(
            conversation_id=data["conversation_id"],
            verdict=Verdict(verdict) if verdict else None,
            confidence=Confidence(confidence) if confidence else None,
            cited_articles=list(data.get("cited_articles", [])),
            unsupported_claims=list(data.get("unsupported_claims", [])),
            explanation=data.get("explanation", ""),
            model=data.get("model", ""),
            error=data.get("error"),
        )
