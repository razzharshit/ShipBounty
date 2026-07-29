from __future__ import annotations

from app.core.config import settings
from app.services.ai_review_service import AIReviewProvider


def configured_ai_review_provider() -> AIReviewProvider:
    provider_name = settings.AI_REVIEW_PROVIDER.strip().lower()
    if provider_name == "openai":
        from app.services.openai_ai_review_provider import (
            OpenAIAdvisoryReviewProvider,
        )

        return OpenAIAdvisoryReviewProvider()
    if provider_name == "gemini":
        from app.services.gemini_ai_review_provider import (
            GeminiAdvisoryReviewProvider,
        )

        return GeminiAdvisoryReviewProvider()
    raise RuntimeError(
        f"Unsupported AI_REVIEW_PROVIDER: {settings.AI_REVIEW_PROVIDER}"
    )
