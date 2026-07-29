from __future__ import annotations

import hashlib
from decimal import Decimal

from sqlalchemy.orm import Session

from app.analysis.base import canonical_json
from app.models.repository import Repository
from app.models.score import ScoreVersion


CATEGORIES = (
    "correctness",
    "tests",
    "maintainability",
    "security",
    "documentation",
    "architecture",
    "change_risk",
)
DEFAULT_WEIGHTS = {
    "correctness": 0.30,
    "tests": 0.20,
    "maintainability": 0.15,
    "security": 0.15,
    "documentation": 0.05,
    "architecture": 0.10,
    "change_risk": 0.05,
}
DEFAULT_REQUIRED_ANALYZERS = [
    "diff_size_concentration",
    "documentation_changes",
    "dependency_changes",
]
DEFAULT_SETTINGS = {"minimum_confidence": 0.30}


def validate_policy(
    weights: dict,
    analyzer_weights: dict,
    required_analyzers: list,
    settings: dict,
) -> None:
    if set(weights) != set(CATEGORIES):
        raise ValueError(f"Scoring weights must define exactly: {', '.join(CATEGORIES)}")
    decimals = {key: Decimal(str(value)) for key, value in weights.items()}
    if any(value < 0 for value in decimals.values()):
        raise ValueError("Scoring weights cannot be negative")
    if sum(decimals.values()) != Decimal("1.0"):
        raise ValueError("Scoring weights must sum exactly to 1.0")
    if any(Decimal(str(value)) <= 0 for value in analyzer_weights.values()):
        raise ValueError("Analyzer weights must be positive")
    if len(required_analyzers) != len(set(required_analyzers)):
        raise ValueError("Required analyzers cannot contain duplicates")
    minimum_confidence = Decimal(str(settings.get("minimum_confidence", 0)))
    if not Decimal("0") <= minimum_confidence <= Decimal("1"):
        raise ValueError("minimum_confidence must be between 0 and 1")


def policy_payload(
    weights: dict,
    analyzer_weights: dict,
    required_analyzers: list,
    settings: dict,
) -> dict:
    return {
        "weights": weights,
        "analyzer_weights": analyzer_weights,
        "required_analyzers": required_analyzers,
        "settings": settings,
    }


def policy_hash(
    weights: dict,
    analyzer_weights: dict,
    required_analyzers: list,
    settings: dict,
) -> str:
    return hashlib.sha256(
        canonical_json(
            policy_payload(weights, analyzer_weights, required_analyzers, settings)
        ).encode()
    ).hexdigest()


def get_or_create_default_policy(db: Session) -> ScoreVersion:
    policy = (
        db.query(ScoreVersion)
        .filter(ScoreVersion.version == "default-v1")
        .first()
    )
    if policy is not None:
        return policy
    digest = policy_hash(
        DEFAULT_WEIGHTS, {}, DEFAULT_REQUIRED_ANALYZERS, DEFAULT_SETTINGS
    )
    policy = ScoreVersion(
        version="default-v1",
        name="Default balanced policy",
        description="Balanced deterministic policy for general repositories.",
        weights=DEFAULT_WEIGHTS,
        analyzer_weights={},
        required_analyzers=DEFAULT_REQUIRED_ANALYZERS,
        settings=DEFAULT_SETTINGS,
        policy_hash=digest,
    )
    db.add(policy)
    db.flush()
    return policy


def policy_for_repository(db: Session, repository: Repository) -> ScoreVersion:
    if repository.scoring_policy is not None:
        return repository.scoring_policy
    policy = get_or_create_default_policy(db)
    repository.scoring_policy_id = policy.id
    db.flush()
    return policy
