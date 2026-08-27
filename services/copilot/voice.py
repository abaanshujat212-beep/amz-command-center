"""Voice-command intent seam for the System Copilot.

This module deliberately does not transcribe audio and does not execute actions.
It normalizes already-transcribed English/Urdu utterances into safe copilot
intents so the UI/mobile layer can route voice input without putting speech
inside the write path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceIntent:
    kind: str
    tier: str
    normalized_question: str
    requires_confirmation: bool = False


ANSWER_PATTERNS = (
    ("spend", "How much did we spend recently, and what was ACOS?"),
    ("acos", "How much did we spend recently, and what was ACOS?"),
    ("kharch", "How much did we spend recently, and what was ACOS?"),
    ("budget", "Which campaigns are being throttled by their budget?"),
    ("opportunity", "Which products and SQP queries have the strongest opportunities?"),
    ("mauqa", "Which products and SQP queries have the strongest opportunities?"),
    ("fresh", "How fresh is the data, and is any dataset stale?"),
    ("stale", "How fresh is the data, and is any dataset stale?"),
    ("data", "How fresh is the data, and is any dataset stale?"),
)

PROPOSE_PATTERNS = ("recommend", "suggest", "proposal", "kya karna", "kia karna", "batao kya")
WRITE_WORDS = ("apply", "approve", "change", "set", "increase", "decrease", "pause", "enable", "lagao", "chalao")


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def classify(text: str) -> VoiceIntent:
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("voice text is empty")

    if any(word in normalized for word in WRITE_WORDS):
        return VoiceIntent(
            kind="proposal",
            tier="T2",
            normalized_question=normalized,
            requires_confirmation=True,
        )

    if any(word in normalized for word in PROPOSE_PATTERNS):
        return VoiceIntent(
            kind="proposal",
            tier="T2",
            normalized_question=normalized,
            requires_confirmation=True,
        )

    for needle, question in ANSWER_PATTERNS:
        if needle in normalized:
            return VoiceIntent(kind="answer", tier="T1", normalized_question=question)

    return VoiceIntent(kind="answer", tier="T1", normalized_question=normalized)
