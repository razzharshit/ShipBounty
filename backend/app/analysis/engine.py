from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.analysis.analyzers import DEFAULT_ANALYZERS
from app.analysis.checkout import RepositoryCheckout
from app.analysis.tool_runners import EXTERNAL_ANALYZERS
from app.analysis.base import (
    AnalysisContext,
    Analyzer,
    AnalyzerOutput,
    FileInput,
    stable_hash,
)
from app.analysis.policy import policy_for_repository, validate_policy
from app.models.analysis_run import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalyzerResult,
    AnalyzerResultStatus,
    AnalyzerRawArtifact,
    AnalyzerToolStatus,
)
from app.core.config import settings
from app.models.pull_request import PullRequest
from app.models.pull_request_file import PullRequestFile
from app.models.score import Score, ScoreEvidence, ScoreVersion
from app.models.webhook_delivery import WebhookDelivery


LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".sol": "Solidity",
    ".md": "Markdown",
    ".rst": "reStructuredText",
}


def _quantize_score(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _quantize_confidence(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def analyzer_manifest(analyzers: tuple[Analyzer, ...]) -> list[dict[str, str]]:
    return sorted(
        (analyzer.manifest() for analyzer in analyzers),
        key=lambda item: (item["name"], item["version"]),
    )


def analyzer_suite_version(analyzers: tuple[Analyzer, ...]) -> str:
    digest = stable_hash(analyzer_manifest(analyzers))
    return f"deterministic-{digest[:16]}"


def _file_inputs(files: list[PullRequestFile]) -> tuple[FileInput, ...]:
    return tuple(
        FileInput(
            filename=file.filename,
            previous_filename=file.previous_filename,
            status=file.github_status,
            sha=file.sha,
            additions=file.additions,
            deletions=file.deletions,
            changes=file.changes,
            patch_hash=(
                hashlib.sha256(file.patch.encode()).hexdigest()
                if file.patch is not None
                else None
            ),
            patch_status=file.patch_status,
        )
        for file in sorted(files, key=lambda item: item.filename)
    )


def _sanitized_check_runs(check_runs: list[dict]) -> tuple[dict, ...]:
    sanitized = [
        {
            "id": check.get("id"),
            "name": check.get("name"),
            "status": check.get("status"),
            "conclusion": check.get("conclusion"),
            "details_url": check.get("details_url"),
            "app_slug": (check.get("app") or {}).get("slug"),
        }
        for check in check_runs
    ]
    return tuple(
        sorted(
            sanitized,
            key=lambda check: (
                str(check.get("name") or ""),
                str(check.get("id") or ""),
            ),
        )
    )


def build_context(
    db: Session,
    pull_request: PullRequest,
    check_runs: list[dict],
    check_runs_error: str | None = None,
    *,
    input_complete: bool,
) -> AnalysisContext:
    files = (
        db.query(PullRequestFile)
        .filter(
            PullRequestFile.pr_id == pull_request.id,
            PullRequestFile.is_current.is_(True),
        )
        .all()
    )
    file_inputs = _file_inputs(files)
    languages = sorted(
        {
            language
            for item in file_inputs
            if (
                language := LANGUAGE_BY_EXTENSION.get(
                    PurePosixPath(item.filename).suffix.lower()
                )
            )
        }
    )
    return AnalysisContext(
        pull_request_id=pull_request.id,
        repository_id=pull_request.repo_id,
        head_sha=pull_request.head_sha or "",
        files=file_inputs,
        languages=tuple(languages),
        check_runs=_sanitized_check_runs(check_runs),
        check_runs_error=check_runs_error,
        input_complete=input_complete,
    )


def context_input_hash(context: AnalysisContext) -> str:
    return stable_hash(
        {
            "pull_request_id": context.pull_request_id,
            "repository_id": context.repository_id,
            "head_sha": context.head_sha,
            "input_complete": context.input_complete,
            "languages": list(context.languages),
            "files": [
                {
                    "filename": file.filename,
                    "previous_filename": file.previous_filename,
                    "status": file.status,
                    "sha": file.sha,
                    "additions": file.additions,
                    "deletions": file.deletions,
                    "changes": file.changes,
                    "patch_hash": file.patch_hash,
                    "patch_status": file.patch_status,
                }
                for file in context.files
            ],
            "check_runs": list(context.check_runs),
            "check_runs_error": context.check_runs_error,
        }
    )


def _run_key(
    pull_request_id: int,
    head_sha: str,
    suite_version: str,
    policy: ScoreVersion,
    input_hash: str,
) -> str:
    return stable_hash(
        {
            "pull_request_id": pull_request_id,
            "head_sha": head_sha,
            "analyzer_suite_version": suite_version,
            "scoring_policy_version": policy.version,
            "policy_hash": policy.policy_hash,
            "input_hash": input_hash,
        }
    )


def _execute_analyzer(
    analyzer: Analyzer, context: AnalysisContext
) -> tuple[AnalyzerOutput, int]:
    started = time.perf_counter_ns()
    try:
        if not analyzer.supports(context):
            output = AnalyzerOutput.unavailable(
                "Analyzer does not support the detected repository languages"
            )
        else:
            output = analyzer.analyze(context)
    except Exception as exc:
        output = AnalyzerOutput.error(
            f"{type(exc).__name__}: {str(exc)[:500]}"
        )
    duration_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
    return output, duration_ms


def _aggregate(
    policy: ScoreVersion,
    persisted_results: list[AnalyzerResult],
    input_complete: bool,
) -> dict:
    validate_policy(
        policy.weights,
        policy.analyzer_weights,
        policy.required_analyzers,
        policy.settings,
    )
    available_by_category: dict[str, list[AnalyzerResult]] = defaultdict(list)
    status_by_analyzer: dict[str, str] = {}
    for result in persisted_results:
        status_by_analyzer[result.analyzer_name] = result.status.value
        if result.status == AnalyzerResultStatus.AVAILABLE and result.score is not None:
            available_by_category[result.category].append(result)

    category_scores: dict[str, float] = {}
    category_confidence: dict[str, float] = {}
    for category in policy.weights:
        results = available_by_category.get(category, [])
        if not results:
            continue
        analyzer_weight_total = sum(
            Decimal(str(policy.analyzer_weights.get(result.analyzer_name, 1)))
            for result in results
        )
        weighted_score = sum(
            Decimal(result.score)
            * Decimal(str(policy.analyzer_weights.get(result.analyzer_name, 1)))
            for result in results
        ) / analyzer_weight_total
        weighted_confidence = sum(
            Decimal(result.confidence)
            * Decimal(str(policy.analyzer_weights.get(result.analyzer_name, 1)))
            for result in results
        ) / analyzer_weight_total
        category_scores[category] = float(_quantize_score(weighted_score))
        category_confidence[category] = float(
            _quantize_confidence(weighted_confidence)
        )

    available_policy_weight = sum(
        Decimal(str(policy.weights[category])) for category in category_scores
    )
    if available_policy_weight == 0:
        return {
            "score_available": False,
            "status_by_analyzer": status_by_analyzer,
            "category_scores": {},
            "category_confidence": {},
            "unavailable_categories": list(policy.weights),
        }

    final_score = sum(
        Decimal(str(category_scores[category]))
        * Decimal(str(policy.weights[category]))
        for category in category_scores
    ) / available_policy_weight
    # Missing categories reduce confidence instead of being silently scored as zero.
    confidence = sum(
        Decimal(str(category_confidence[category]))
        * Decimal(str(policy.weights[category]))
        for category in category_scores
    )
    required_available = all(
        status_by_analyzer.get(name) == AnalyzerResultStatus.AVAILABLE.value
        for name in policy.required_analyzers
    )
    minimum_confidence = Decimal(
        str(policy.settings.get("minimum_confidence", 0))
    )
    authoritative = (
        input_complete
        and required_available
        and confidence >= minimum_confidence
    )
    unavailable_categories = [
        category for category in policy.weights if category not in category_scores
    ]
    return {
        "score_available": True,
        "final_score": _quantize_score(final_score),
        "confidence": _quantize_confidence(confidence),
        "category_scores": category_scores,
        "category_confidence": category_confidence,
        "unavailable_categories": unavailable_categories,
        "status_by_analyzer": status_by_analyzer,
        "required_analyzers_available": required_available,
        "is_authoritative": authoritative,
        "available_policy_weight": float(available_policy_weight),
    }


def execute_scoring_run(
    db: Session,
    *,
    pull_request: PullRequest,
    delivery: WebhookDelivery,
    check_runs: list[dict],
    check_runs_error: str | None = None,
    metrics_snapshot: dict,
    input_complete: bool = True,
    analyzers: tuple[Analyzer, ...] = DEFAULT_ANALYZERS,
) -> tuple[AnalysisRun, Score | None, bool]:
    if settings.EXTERNAL_ANALYZERS_ENABLED and analyzers is DEFAULT_ANALYZERS:
        analyzers = (*analyzers, *EXTERNAL_ANALYZERS)
    policy = policy_for_repository(db, pull_request.repository)
    manifest = analyzer_manifest(analyzers)
    suite_version = analyzer_suite_version(analyzers)
    context = build_context(
        db,
        pull_request,
        check_runs,
        check_runs_error=check_runs_error,
        input_complete=input_complete,
    )
    input_hash = context_input_hash(context)
    run_key = _run_key(
        pull_request.id,
        context.head_sha,
        suite_version,
        policy,
        input_hash,
    )
    existing = (
        db.query(AnalysisRun).filter(AnalysisRun.run_key == run_key).first()
    )
    if existing is not None:
        if existing.score is not None:
            pull_request.latest_score_id = existing.score.id
            db.flush()
        return existing, existing.score, False

    now = datetime.utcnow()
    run = AnalysisRun(
        pr_id=pull_request.id,
        delivery_pk=delivery.id,
        analysis_version=suite_version,
        analyzer_version=suite_version,
        scoring_policy_version=policy.version,
        run_key=run_key,
        input_hash=input_hash,
        analyzer_manifest=manifest,
        head_sha=context.head_sha,
        status=AnalysisRunStatus.RUNNING,
        input_complete=input_complete,
        is_authoritative=False,
        metrics_snapshot=metrics_snapshot,
        started_at=now,
        completed_at=None,
    )
    db.add(run)
    db.flush()

    checkout = None
    checkout_path = None
    checkout_error = None
    if settings.EXTERNAL_ANALYZERS_ENABLED:
        try:
            if not delivery.installation_id:
                raise RuntimeError("GitHub installation identity is unavailable")
            checkout = RepositoryCheckout(
                repository_full_name=pull_request.repository.full_name,
                head_sha=context.head_sha,
                installation_id=int(delivery.installation_id),
            )
            checkout_path = checkout.__enter__()
        except Exception as exc:
            checkout = None
            checkout_error = f"{type(exc).__name__}: {str(exc)[:500]}"
    execution_context = replace(
        context,
        checkout_path=checkout_path,
        checkout_error=checkout_error,
    )

    persisted_results: list[AnalyzerResult] = []
    try:
        for analyzer in analyzers:
            output, duration_ms = _execute_analyzer(
                analyzer, execution_context
            )
            persisted_evidence = []
            raw_artifact = None
            for item in output.evidence:
                normalized_item = {
                    **item,
                    "data": dict(item.get("data") or {}),
                }
                artifact = normalized_item["data"].pop(
                    "_raw_artifact", None
                )
                if artifact is not None:
                    raw_artifact = artifact
                persisted_evidence.append(normalized_item)
            result = AnalyzerResult(
                analysis_run_id=run.id,
                analyzer_name=analyzer.name,
                analyzer_version=analyzer.version,
                category=analyzer.category,
                status=output.status,
                score=output.score,
                confidence=output.confidence,
                findings=list(output.findings),
                evidence=persisted_evidence,
                errors=list(output.errors),
                duration_ms=duration_ms,
                result_hash=stable_hash(
                    {
                        "analyzer": analyzer.manifest(),
                        "output": output.deterministic_payload(),
                    }
                ),
            )
            db.add(result)
            if raw_artifact is not None:
                result.raw_artifacts.append(
                    AnalyzerRawArtifact(
                        tool_status=AnalyzerToolStatus(
                            raw_artifact["status"]
                        ),
                        command=raw_artifact["command"],
                        image=raw_artifact["image"],
                        exit_code=raw_artifact["exit_code"],
                        stdout=raw_artifact["stdout"],
                        stderr=raw_artifact["stderr"],
                        output_hash=raw_artifact["output_hash"],
                        duration_ms=raw_artifact["duration_ms"],
                    )
                )
            persisted_results.append(result)
    finally:
        if checkout is not None:
            checkout.__exit__(None, None, None)
    db.flush()

    aggregate = _aggregate(policy, persisted_results, input_complete)
    if not aggregate["score_available"]:
        run.status = AnalysisRunStatus.INCOMPLETE
        run.incomplete_reason = "NO_SCORABLE_ANALYZERS"
        run.completed_at = datetime.utcnow()
        db.flush()
        return run, None, True

    explanation = {
        "formula": "weighted mean of available categories; unavailable categories are excluded, not zeroed",
        "policy_weights": policy.weights,
        "analyzer_weights": policy.analyzer_weights,
        "available_policy_weight": aggregate["available_policy_weight"],
        "unavailable_categories": aggregate["unavailable_categories"],
        "analyzer_status": aggregate["status_by_analyzer"],
        "required_analyzers": policy.required_analyzers,
        "required_analyzers_available": aggregate[
            "required_analyzers_available"
        ],
    }
    score_payload = {
        "run_key": run_key,
        "input_hash": input_hash,
        "policy_hash": policy.policy_hash,
        "analyzer_result_hashes": sorted(
            result.result_hash for result in persisted_results
        ),
        "category_scores": aggregate["category_scores"],
        "category_confidence": aggregate["category_confidence"],
        "final_score": str(aggregate["final_score"]),
        "confidence": str(aggregate["confidence"]),
        "input_complete": input_complete,
        "is_authoritative": aggregate["is_authoritative"],
    }
    score = Score(
        pr_id=pull_request.id,
        analysis_run_id=run.id,
        score_version_id=policy.id,
        head_sha=context.head_sha,
        analyzer_suite_version=suite_version,
        scoring_policy_version=policy.version,
        category_scores=aggregate["category_scores"],
        category_confidence=aggregate["category_confidence"],
        unavailable_categories=aggregate["unavailable_categories"],
        final_score=aggregate["final_score"],
        confidence=aggregate["confidence"],
        input_complete=input_complete,
        is_authoritative=aggregate["is_authoritative"],
        explanation=explanation,
        deterministic_hash=stable_hash(score_payload),
    )
    db.add(score)
    db.flush()

    for result in persisted_results:
        for item in result.evidence:
            evidence_payload = {
                "analyzer": result.analyzer_name,
                "category": result.category,
                "type": item.get("type") or "finding",
                "description": item.get("description") or "Analyzer evidence",
                "location": item.get("location"),
                "data": item.get("data") or {},
            }
            db.add(
                ScoreEvidence(
                    score_id=score.id,
                    analyzer_result_id=result.id,
                    category=result.category,
                    evidence_type=evidence_payload["type"],
                    description=evidence_payload["description"],
                    location=evidence_payload["location"],
                    evidence_data=evidence_payload["data"],
                    evidence_hash=stable_hash(evidence_payload),
                )
            )

    run.status = AnalysisRunStatus.COMPLETE
    run.is_authoritative = score.is_authoritative
    run.completed_at = datetime.utcnow()
    from app.services.eligibility_service import supersede_current_decision

    supersede_current_decision(db, pull_request)
    pull_request.latest_score_id = score.id
    db.flush()
    return run, score, True


def record_incomplete_scoring_run(
    db: Session,
    *,
    pull_request: PullRequest,
    delivery: WebhookDelivery,
    reason: str,
    metrics_snapshot: dict | None = None,
    analyzers: tuple[Analyzer, ...] = DEFAULT_ANALYZERS,
) -> AnalysisRun:
    """Record an unscored input without invalidating immutable score history."""
    policy = policy_for_repository(db, pull_request.repository)
    manifest = analyzer_manifest(analyzers)
    suite_version = analyzer_suite_version(analyzers)
    input_hash = stable_hash(
        {
            "pull_request_id": pull_request.id,
            "repository_id": pull_request.repo_id,
            "head_sha": pull_request.head_sha,
            "input_complete": False,
            "incomplete_reason": reason,
        }
    )
    run_key = _run_key(
        pull_request.id,
        pull_request.head_sha or "",
        suite_version,
        policy,
        input_hash,
    )
    existing = (
        db.query(AnalysisRun).filter(AnalysisRun.run_key == run_key).first()
    )
    if existing is not None:
        pull_request.latest_score_id = None
        db.flush()
        return existing

    now = datetime.utcnow()
    run = AnalysisRun(
        pr_id=pull_request.id,
        delivery_pk=delivery.id,
        analysis_version=suite_version,
        analyzer_version=suite_version,
        scoring_policy_version=policy.version,
        run_key=run_key,
        input_hash=input_hash,
        analyzer_manifest=manifest,
        head_sha=pull_request.head_sha,
        status=AnalysisRunStatus.INCOMPLETE,
        input_complete=False,
        is_authoritative=False,
        incomplete_reason=reason,
        metrics_snapshot=metrics_snapshot,
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    pull_request.latest_score_id = None
    db.flush()
    return run
