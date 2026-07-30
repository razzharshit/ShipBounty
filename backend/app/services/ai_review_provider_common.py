from __future__ import annotations

from app.schemas.ai_review import ModerationResult


AI_REVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "positive_findings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risk_findings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "requirement_coverage": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommended_actions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "summary",
        "positive_findings",
        "risk_findings",
        "requirement_coverage",
        "recommended_actions",
        "confidence",
    ],
}


class AIProviderSafetyBlocked(RuntimeError):
    def __init__(self, moderation_result: ModerationResult) -> None:
        super().__init__(
            moderation_result.details or "AI provider blocked unsafe content"
        )
        self.moderation_result = moderation_result
