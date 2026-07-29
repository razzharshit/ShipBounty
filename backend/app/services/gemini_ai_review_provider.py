from __future__ import annotations

import json

import requests

from app.core.config import settings
from app.models.ai_review import AIProviderKind
from app.schemas.ai_review import (
    AIReviewOutput,
    ModerationResult,
    ModerationStatus,
    TokenUsage,
)
from app.services.ai_review_provider_common import (
    AIProviderSafetyBlocked,
    AI_REVIEW_OUTPUT_SCHEMA,
)
from app.services.ai_review_service import AIProviderResponse


def _raise_provider_error(response: requests.Response) -> None:
    if response.status_code < 400:
        return
    try:
        json_body = response.json()
        detail = json.dumps(json_body, indent=2)
    except Exception:
        detail = response.text[:4000]
    raise RuntimeError(f"Gemini HTTP {response.status_code}:\n{detail}")


class GeminiAdvisoryReviewProvider:
    name = "gemini"
    kind = AIProviderKind.EXTERNAL

    def __init__(self) -> None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        if not settings.GEMINI_AI_REVIEW_MODEL:
            raise RuntimeError("GEMINI_AI_REVIEW_MODEL is not configured")
        self.model = settings.GEMINI_AI_REVIEW_MODEL
        self.base_url = settings.GEMINI_API_BASE_URL.rstrip("/")

    @staticmethod
    def _output_text(candidate: dict) -> str:
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        text = "".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict)
        )
        if not text:
            raise RuntimeError("Gemini response did not contain output text")
        return text

    @staticmethod
    def _moderation(body: dict, candidate: dict) -> ModerationResult:
        prompt_feedback = body.get("promptFeedback") or {}
        finish_reason = str(candidate.get("finishReason") or "").upper()
        ratings = candidate.get("safetyRatings") or []
        categories = {
            str(item.get("category") or "unknown").lower(): bool(
                item.get("blocked")
            )
            for item in ratings
            if isinstance(item, dict)
        }
        block_reason = prompt_feedback.get("blockReason")
        flagged = bool(block_reason or finish_reason == "SAFETY")
        flagged = flagged or any(categories.values())
        return ModerationResult(
            status=(
                ModerationStatus.FLAGGED
                if flagged
                else ModerationStatus.PASSED
            ),
            categories=categories,
            details=(
                f"Gemini blocked the prompt: {block_reason}"
                if block_reason
                else None
            ),
        )

    def review(
        self,
        *,
        input_snapshot: dict,
        prompt_version: str,
        idempotency_key: str,
        model_override: str | None = None,
    ) -> AIProviderResponse:
        candidates_to_try = [
            model_override or self.model,
            "gemini-flash-latest",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
        ]
        models_to_try: list[str] = []
        for m in candidates_to_try:
            if m and m not in models_to_try:
                models_to_try.append(m)

        last_response = None
        for current_model in models_to_try:
            response = requests.post(
                f"{self.base_url}/v1beta/models/{current_model}:generateContent",
                headers={
                    "x-goog-api-key": settings.GEMINI_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "systemInstruction": {
                        "parts": [
                            {
                                "text": (
                                    "You are an advisory code reviewer. Use only "
                                    "the supplied evidence. Do not decide "
                                    "eligibility or payment. Identify uncertainty "
                                    "explicitly. Prompt contract: "
                                    f"{prompt_version}."
                                )
                            }
                        ]
                    },
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": json.dumps(
                                        input_snapshot,
                                        sort_keys=True,
                                        separators=(",", ":"),
                                    )
                                }
                            ],
                        }
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseJsonSchema": AI_REVIEW_OUTPUT_SCHEMA,
                        "maxOutputTokens": settings.GEMINI_MAX_OUTPUT_TOKENS,
                    },
                    "safetySettings": [
                        {
                            "category": category,
                            "threshold": "BLOCK_ONLY_HIGH",
                        }
                        for category in (
                            "HARM_CATEGORY_HARASSMENT",
                            "HARM_CATEGORY_HATE_SPEECH",
                            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            "HARM_CATEGORY_DANGEROUS_CONTENT",
                        )
                    ],
                },
                timeout=settings.GEMINI_TIMEOUT_SECONDS,
            )
            if response.status_code < 400:
                break
            last_response = response
            if response.status_code != 503:
                break
        else:
            response = last_response  # type: ignore

        _raise_provider_error(response)
        body = response.json()
        candidates = body.get("candidates") or []
        if not candidates:
            block_reason = (body.get("promptFeedback") or {}).get(
                "blockReason"
            )
            if block_reason:
                raise AIProviderSafetyBlocked(
                    ModerationResult(
                        status=ModerationStatus.FLAGGED,
                        details=f"Gemini blocked the prompt: {block_reason}",
                    )
                )
            raise RuntimeError("Gemini response did not contain a candidate")
        candidate = candidates[0]
        moderation = self._moderation(body, candidate)
        if moderation.status == ModerationStatus.FLAGGED:
            raise AIProviderSafetyBlocked(moderation)
        output = AIReviewOutput.model_validate_json(
            self._output_text(candidate)
        )
        usage = body.get("usageMetadata") or {}
        prompt_tokens = int(usage.get("promptTokenCount") or 0)
        completion_tokens = int(usage.get("candidatesTokenCount") or 0)
        total_tokens = int(
            usage.get("totalTokenCount")
            or prompt_tokens + completion_tokens
        )
        request_id = body.get("responseId")
        if not request_id:
            request_id = getattr(response, "headers", {}).get("x-request-id")
        return AIProviderResponse(
            output=output,
            provider_request_id=request_id,
            token_usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
            # The free/paid tier is account-side state. Preserve unknown cost
            # rather than recording a false zero.
            cost_amount=None,
            cost_currency=None,
            moderation_result=moderation,
        )
