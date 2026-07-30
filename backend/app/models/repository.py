from datetime import datetime

from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    github_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    github_installation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("github_installations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scoring_policy_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("score_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    eligibility_policy_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "repository_policies.id",
            name="fk_repositories_eligibility_policy_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    bounty_policy_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "bounty_policies.id",
            name="fk_repositories_bounty_policy_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    ai_review_policy_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "ai_review_policies.id",
            name="fk_repositories_ai_review_policy_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(512), nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    organization = relationship("Organization", back_populates="repositories")
    github_installation = relationship("GitHubInstallation", back_populates="repositories")
    scoring_policy = relationship("ScoreVersion", back_populates="repositories")
    eligibility_policy = relationship(
        "RepositoryPolicy",
        foreign_keys=[eligibility_policy_id],
        post_update=True,
    )
    eligibility_policies = relationship(
        "RepositoryPolicy",
        back_populates="repository",
        foreign_keys="RepositoryPolicy.repository_id",
    )
    bounty_policy = relationship(
        "BountyPolicy", foreign_keys=[bounty_policy_id], post_update=True
    )
    bounty_policies = relationship(
        "BountyPolicy",
        back_populates="repository",
        foreign_keys="BountyPolicy.repository_id",
    )
    ai_review_policy = relationship(
        "AIReviewPolicy", foreign_keys=[ai_review_policy_id], post_update=True
    )
    ai_review_policies = relationship(
        "AIReviewPolicy",
        back_populates="repository",
        foreign_keys="AIReviewPolicy.repository_id",
    )
    issues = relationship("Issue", back_populates="repository")
    bounties = relationship("Bounty", back_populates="repository")
    permissions = relationship(
        "RepositoryPermission", back_populates="repository", cascade="all, delete-orphan"
    )
    pull_requests = relationship("PullRequest", back_populates="repository")
