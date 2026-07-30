from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.models.analysis_run import AnalyzerResultStatus


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def decimal_score(value: int | float | str | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decimal_confidence(value: int | float | str | Decimal) -> Decimal:
    bounded = min(Decimal("1"), max(Decimal("0"), Decimal(str(value))))
    return bounded.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FileInput:
    filename: str
    previous_filename: str | None
    status: str
    sha: str | None
    additions: int
    deletions: int
    changes: int
    patch_hash: str | None
    patch_status: str


@dataclass(frozen=True)
class AnalysisContext:
    pull_request_id: int
    repository_id: int
    head_sha: str
    files: tuple[FileInput, ...]
    languages: tuple[str, ...]
    check_runs: tuple[dict, ...]
    check_runs_error: str | None
    input_complete: bool
    checkout_path: str | None = None
    checkout_error: str | None = None


@dataclass(frozen=True)
class AnalyzerOutput:
    status: AnalyzerResultStatus
    score: Decimal | None
    confidence: Decimal
    findings: tuple[dict, ...] = field(default_factory=tuple)
    evidence: tuple[dict, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def available(
        cls,
        score: int | float | str | Decimal,
        confidence: int | float | str | Decimal,
        *,
        findings: list[dict] | tuple[dict, ...] = (),
        evidence: list[dict] | tuple[dict, ...] = (),
    ) -> "AnalyzerOutput":
        return cls(
            status=AnalyzerResultStatus.AVAILABLE,
            score=decimal_score(score),
            confidence=decimal_confidence(confidence),
            findings=tuple(findings),
            evidence=tuple(evidence),
        )

    @classmethod
    def unavailable(
        cls, reason: str, *, evidence: list[dict] | tuple[dict, ...] = ()
    ) -> "AnalyzerOutput":
        return cls(
            status=AnalyzerResultStatus.UNAVAILABLE,
            score=None,
            confidence=Decimal("0"),
            findings=({"code": "UNAVAILABLE", "message": reason},),
            evidence=tuple(evidence),
        )

    @classmethod
    def inconclusive(
        cls, reason: str, *, evidence: list[dict] | tuple[dict, ...] = ()
    ) -> "AnalyzerOutput":
        return cls(
            status=AnalyzerResultStatus.INCONCLUSIVE,
            score=None,
            confidence=Decimal("0"),
            findings=({"code": "INCONCLUSIVE", "message": reason},),
            evidence=tuple(evidence),
        )

    @classmethod
    def error(cls, message: str) -> "AnalyzerOutput":
        return cls(
            status=AnalyzerResultStatus.ERROR,
            score=None,
            confidence=Decimal("0"),
            errors=(message,),
        )

    def deterministic_payload(self) -> dict:
        return {
            "status": self.status.value,
            "score": str(self.score) if self.score is not None else None,
            "confidence": str(self.confidence),
            "findings": list(self.findings),
            "evidence": list(self.evidence),
            "errors": list(self.errors),
        }


class Analyzer(ABC):
    name: str
    version: str
    category: str

    def supports(self, context: AnalysisContext) -> bool:
        return True

    @abstractmethod
    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        raise NotImplementedError

    def manifest(self) -> dict[str, str]:
        return {
            "name": self.name,
            "version": self.version,
            "category": self.category,
        }


def evidence(
    evidence_type: str,
    description: str,
    *,
    location: str | None = None,
    data: dict | None = None,
) -> dict:
    return {
        "type": evidence_type,
        "description": description,
        "location": location,
        "data": data or {},
    }
