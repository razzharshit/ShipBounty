from __future__ import annotations

import logging
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.models.pr_metrics import PRMetrics
from app.models.pull_request_file import PullRequestFile
from app.core.config import settings


logger = logging.getLogger(__name__)


LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".php": "PHP",
    ".rb": "Ruby",
    ".sol": "Solidity",
    ".html": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
    ".md": "Markdown",
}


def _is_test_file(filename: str) -> bool:
    normalized = filename.replace("\\", "/").lower()
    return any(pattern in normalized for pattern in ("tests/", "test_", ".spec.", ".test."))


def _is_docs_file(filename: str) -> bool:
    normalized = filename.replace("\\", "/").lower()
    basename = PurePosixPath(normalized).name
    return basename in {"readme.md", "readme.rst"} or any(
        pattern in normalized for pattern in ("docs/", "documentation/")
    )


def _detect_language(filename: str) -> str | None:
    extension = PurePosixPath(filename).suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(extension)


def get_pr_metrics_by_pr_id(db: Session, pr_id: int) -> PRMetrics | None:
    return db.query(PRMetrics).filter(PRMetrics.pr_id == pr_id).first()


def analyze_pull_request(
    db: Session,
    pr_id: int,
    *,
    commit: bool = True,
) -> PRMetrics:
    logger.info("Analyzing PR: %s", pr_id)

    files = (
        db.query(PullRequestFile)
        .filter(
            PullRequestFile.pr_id == pr_id,
            PullRequestFile.is_current.is_(True),
        )
        .all()
    )

    total_files = len(files)
    total_additions = sum(file.additions for file in files)
    total_deletions = sum(file.deletions for file in files)
    has_tests = any(_is_test_file(file.filename) for file in files)
    has_docs = any(_is_docs_file(file.filename) for file in files)
    language_breakdown: dict[str, int] = {}

    for file in files:
        language = _detect_language(file.filename)
        if language:
            language_breakdown[language] = language_breakdown.get(language, 0) + 1

    logger.info("Total Files: %s", total_files)
    logger.info("Total Additions: %s", total_additions)
    logger.info("Total Deletions: %s", total_deletions)
    logger.info("Has Tests: %s", has_tests)
    logger.info("Has Docs: %s", has_docs)
    logger.info("Languages: %s", language_breakdown)

    metrics = get_pr_metrics_by_pr_id(db, pr_id)
    if metrics:
        metrics.total_files = total_files
        metrics.total_additions = total_additions
        metrics.total_deletions = total_deletions
        metrics.has_tests = has_tests
        metrics.has_docs = has_docs
        metrics.language_breakdown = language_breakdown
        metrics.analysis_version = settings.ANALYSIS_VERSION
    else:
        metrics = PRMetrics(
            pr_id=pr_id,
            total_files=total_files,
            total_additions=total_additions,
            total_deletions=total_deletions,
            has_tests=has_tests,
            has_docs=has_docs,
            language_breakdown=language_breakdown,
            analysis_version=settings.ANALYSIS_VERSION,
        )
        db.add(metrics)

    db.flush()

    if commit:
        db.commit()
        db.refresh(metrics)
    logger.info("Metrics saved successfully: pr_id=%s", pr_id)

    return metrics
