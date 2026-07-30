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
from app.services.ai_review_provider_common import AI_REVIEW_OUTPUT_SCHEMA
from app.services.ai_review_service import AIProviderResponse


def _raise_provider_error(response: requests.Response, provider: str = "OpenAI") -> None:
    if response.status_code < 400:
        return
    detail = response.text[:1000].replace("\n", " ")
    raise RuntimeError(f"{provider} HTTP {response.status_code}: {detail}")


class OpenAIAdvisoryReviewProvider:
    name = "openai"
    kind = AIProviderKind.EXTERNAL

    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if not settings.OPENAI_AI_REVIEW_MODEL:
            raise RuntimeError("OPENAI_AI_REVIEW_MODEL is not configured")
        self.model = settings.OPENAI_AI_REVIEW_MODEL
        self.base_url = settings.OPENAI_API_BASE_URL.rstrip("/")

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _output_text(body: dict) -> str:
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        for item in body.get("output") or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if content.get("type") == "output_text":
                    return str(content.get("text") or "")
        raise RuntimeError("OpenAI response did not contain output text")

    def _moderate(self, output: AIReviewOutput) -> ModerationResult:
        response = requests.post(
            f"{self.base_url}/v1/moderations",
            headers=self._headers(),
            json={
                "model": settings.OPENAI_MODERATION_MODEL,
                "input": json.dumps(output.model_dump(mode="json")),
            },
            timeout=settings.AI_REVIEW_TIMEOUT_SECONDS,
        )
        _raise_provider_error(response)
        body = response.json()
        result = (body.get("results") or [None])[0]
        if not isinstance(result, dict):
            raise RuntimeError("OpenAI moderation response was malformed")
        categories = {
            key: bool(value)
            for key, value in (result.get("categories") or {}).items()
        }
        return ModerationResult(
            status=(
                ModerationStatus.FLAGGED
                if result.get("flagged")
                else ModerationStatus.PASSED
            ),
            categories=categories,
        )

    def review(
        self,
        *,
        input_snapshot: dict,
        prompt_version: str,
        idempotency_key: str,
        model_override: str | None = None,
    ) -> AIProviderResponse:
        model_to_use = model_override or self.model
        response = requests.post(
            f"{self.base_url}/v1/responses",
            headers=self._headers(idempotency_key),
            json={
                "model": model_to_use,
                "instructions": (
                    "You are an advisory code reviewer. Use only the supplied "
                    "evidence. Do not decide eligibility or payment. Identify "
                    "uncertainty explicitly. Prompt contract: "
                    f"{prompt_version}."
                ),
                "input": json.dumps(
                    input_snapshot, sort_keys=True, separators=(",", ":")
                ),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "advisory_code_review",
                        "strict": True,
                        "schema": AI_REVIEW_OUTPUT_SCHEMA,
                    }
                },
            },
            timeout=settings.AI_REVIEW_TIMEOUT_SECONDS,
        )
        _raise_provider_error(response)
        body = response.json()
        output = AIReviewOutput.model_validate_json(self._output_text(body))
        usage = body.get("usage") or {}
        token_usage = TokenUsage(
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )
        return AIProviderResponse(
            output=output,
            provider_request_id=body.get("id"),
            token_usage=token_usage,
            # The Responses API reports tokens, not invoice cost. Preserve
            # unknown cost instead of embedding a stale price table.
            cost_amount=None,
            cost_currency=None,
            moderation_result=self._moderate(output),
        )
