from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.analysis_run import AnalysisRunStatus, AnalyzerResultStatus


class ScoreEvidenceRead(BaseModel):
    id: int
    analyzer_result_id: int
    category: str
    evidence_type: str
    description: str
    location: str | None
    evidence_data: dict[str, Any]
    evidence_hash: str

    model_config = ConfigDict(from_attributes=True)


class ScoreRead(BaseModel):
    id: int
    pr_id: int
    analysis_run_id: int | None
    score_version_id: int
    head_sha: str | None
    analyzer_suite_version: str
    scoring_policy_version: str
    category_scores: dict[str, float]
    category_confidence: dict[str, float]
    unavailable_categories: list[str]
    final_score: float
    confidence: float
    input_complete: bool
    is_authoritative: bool
    explanation: dict[str, Any]
    deterministic_hash: str
    evidence: list[ScoreEvidenceRead] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnalyzerResultRead(BaseModel):
    id: int
    analyzer_name: str
    analyzer_version: str
    category: str
    status: AnalyzerResultStatus
    score: float | None
    confidence: float
    findings: list[Any]
    evidence: list[Any]
    errors: list[Any]
    duration_ms: int
    result_hash: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnalysisRunRead(BaseModel):
    id: int
    pr_id: int
    delivery_pk: int
    analyzer_version: str
    scoring_policy_version: str
    run_key: str
    input_hash: str
    analyzer_manifest: list[dict[str, str]]
    head_sha: str | None
    status: AnalysisRunStatus
    input_complete: bool
    is_authoritative: bool
    incomplete_reason: str | None
    metrics_snapshot: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
    analyzer_results: list[AnalyzerResultRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ScoringPolicyRead(BaseModel):
    id: int
    version: str
    name: str
    description: str | None
    weights: dict[str, float]
    analyzer_weights: dict[str, float]
    required_analyzers: list[str]
    settings: dict[str, Any]
    policy_hash: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScoringPolicyUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    weights: dict[str, float]
    analyzer_weights: dict[str, float] = Field(default_factory=dict)
    required_analyzers: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
