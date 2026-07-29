from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.analysis.tool_runners import TOOL_SPECS, run_tool
from app.core.config import settings
from app.services.ai_review_provider_factory import (
    configured_ai_review_provider,
)
from app.services.ai_review_provider_common import AIProviderSafetyBlocked
from app.services.ai_review_quota import (
    AIReviewDailyLimitExceeded,
    reserve_daily_ai_review_request,
)
from app.services.gemini_ai_review_provider import (
    GeminiAdvisoryReviewProvider,
)
from app.services.openai_ai_review_provider import (
    OpenAIAdvisoryReviewProvider,
)


def test_isolated_runner_uses_digest_network_and_resource_guards(
    monkeypatch, tmp_path
):
    spec = TOOL_SPECS[0]
    monkeypatch.setattr(settings, "ANALYZER_CONTAINER_RUNTIME", "docker")
    monkeypatch.setattr(
        settings,
        "ANALYZER_IMAGES_JSON",
        json.dumps({"ruff": "example/ruff@sha256:" + "a" * 64}),
    )
    monkeypatch.setattr(
        "app.analysis.tool_runners.shutil.which", lambda value: "/usr/bin/docker"
    )
    observed = {}

    class Completed:
        returncode = 0
        stdout = b"[]"
        stderr = b""

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr("app.analysis.tool_runners.subprocess.run", fake_run)
    result = run_tool(spec, str(tmp_path))

    assert result["status"] == "passed"
    assert "--network" in observed["command"]
    assert "none" in observed["command"]
    assert "--read-only" in observed["command"]
    assert "--cap-drop" in observed["command"]
    assert observed["kwargs"]["timeout"] == settings.ANALYZER_TIMEOUT_SECONDS


def test_openai_advisory_adapter_uses_strict_schema_and_moderation(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OPENAI_AI_REVIEW_MODEL", "test-model")
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/moderations"):
            return Response(
                {"results": [{"flagged": False, "categories": {}}]}
            )
        return Response(
            {
                "id": "resp_test",
                "output_text": json.dumps(
                    {
                        "summary": "Advisory review",
                        "positive_findings": [],
                        "risk_findings": [],
                        "requirement_coverage": [],
                        "recommended_actions": [],
                        "confidence": 0.75,
                    }
                ),
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            }
        )

    monkeypatch.setattr(
        "app.services.openai_ai_review_provider.requests.post", post
    )
    provider = OpenAIAdvisoryReviewProvider()
    response = provider.review(
        input_snapshot={"contract": {"advisory_only": True}},
        prompt_version="test-v1",
        idempotency_key="review-key",
    )

    request_body = calls[0][1]["json"]
    assert request_body["text"]["format"]["strict"] is True
    assert calls[0][1]["headers"]["Idempotency-Key"] == "review-key"
    assert response.output.confidence == Decimal("0.75")
    assert response.provider_request_id == "resp_test"
    assert response.cost_amount is None
    assert response.moderation_result.status.value == "passed"


def test_gemini_advisory_adapter_uses_schema_safety_and_usage(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        settings, "GEMINI_AI_REVIEW_MODEL", "gemini-test-model"
    )
    calls = []

    class Response:
        headers = {"x-request-id": "gemini-request"}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "safetyRatings": [
                            {
                                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                                "probability": "NEGLIGIBLE",
                                "blocked": False,
                            }
                        ],
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "summary": "Advisory review",
                                            "positive_findings": [],
                                            "risk_findings": [],
                                            "requirement_coverage": [],
                                            "recommended_actions": [],
                                            "confidence": 0.8,
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 6,
                    "totalTokenCount": 18,
                },
            }

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(
        "app.services.gemini_ai_review_provider.requests.post", post
    )
    provider = GeminiAdvisoryReviewProvider()
    response = provider.review(
        input_snapshot={"contract": {"advisory_only": True}},
        prompt_version="test-v1",
        idempotency_key="review-key",
    )

    url, request = calls[0]
    assert url.endswith(
        "/v1beta/models/gemini-test-model:generateContent"
    )
    assert request["headers"]["x-goog-api-key"] == "test-key"
    generation = request["json"]["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseJsonSchema"]["additionalProperties"] is False
    assert response.output.confidence == Decimal("0.8")
    assert response.provider_request_id == "gemini-request"
    assert response.token_usage.total_tokens == 18
    assert response.moderation_result.status.value == "passed"


def test_provider_factory_selects_gemini(monkeypatch):
    monkeypatch.setattr(settings, "AI_REVIEW_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        settings, "GEMINI_AI_REVIEW_MODEL", "gemini-test-model"
    )

    provider = configured_ai_review_provider()

    assert provider.name == "gemini"
    assert provider.model == "gemini-test-model"


def test_gemini_safety_block_is_explicit(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        settings, "GEMINI_AI_REVIEW_MODEL", "gemini-test-model"
    )

    class Response:
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "promptFeedback": {
                    "blockReason": "SAFETY",
                },
                "candidates": [],
            }

    monkeypatch.setattr(
        "app.services.gemini_ai_review_provider.requests.post",
        lambda *args, **kwargs: Response(),
    )
    provider = GeminiAdvisoryReviewProvider()

    with pytest.raises(AIProviderSafetyBlocked) as exc_info:
        provider.review(
            input_snapshot={"contract": {"advisory_only": True}},
            prompt_version="test-v1",
            idempotency_key="review-key",
        )

    assert exc_info.value.moderation_result.status.value == "flagged"


def test_daily_ai_quota_counts_each_provider_attempt_and_enforces_limit(monkeypatch):
    monkeypatch.setattr(settings, "AI_REVIEW_DAILY_LIMIT", 2)

    class FakeRedis:
        def __init__(self):
            self.values = {}

        def eval(
            self,
            script,
            key_count,
            day_key,
            limit,
            day_ttl,
        ):
            current = self.values.get(day_key, 0)
            if int(limit) <= 0 or current >= int(limit):
                return [0, current]
            current += 1
            self.values[day_key] = current
            return [1, current]

    client = FakeRedis()
    first = reserve_daily_ai_review_request(
        provider="gemini",
        client=client,
    )
    second = reserve_daily_ai_review_request(
        provider="gemini",
        client=client,
    )

    assert (first, second) == (1, 2)
    with pytest.raises(AIReviewDailyLimitExceeded):
        reserve_daily_ai_review_request(
            provider="gemini",
            client=client,
        )
