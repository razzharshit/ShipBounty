"""Audit or backfill repository-scoped GitHub pull-request numbers.

Run after migration 0014. ``--backfill`` obtains an installation token, follows
GitHub pagination for every affected repository, and matches the immutable
global ``github_pr_id`` before writing the visible PR number. No value is
guessed. ``--enforce-not-null`` is the contract step and is accepted only on
PostgreSQL after the unresolved count reaches zero.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.github.auth import get_installation_token
from app.github.client import get_all_pull_requests
from app.models.pull_request import PullRequest


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Resolve missing values from the GitHub App installation.",
    )
    parser.add_argument(
        "--enforce-not-null",
        action="store_true",
        help="Apply the PostgreSQL NOT NULL contract after a clean audit.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    db = SessionLocal()
    try:
        unresolved_query = (
            db.query(PullRequest)
            .filter(PullRequest.github_pr_number.is_(None))
            .order_by(PullRequest.id)
        )
        unresolved = unresolved_query.all()
        if arguments.backfill:
            by_repository: dict[int, list[PullRequest]] = {}
            for pull_request in unresolved:
                by_repository.setdefault(pull_request.repo_id, []).append(
                    pull_request
                )
            for pull_requests in by_repository.values():
                repository = pull_requests[0].repository
                installation = repository.github_installation
                if installation is None:
                    print(
                        f"skip repository={repository.full_name}: "
                        "no GitHub installation"
                    )
                    continue
                token = get_installation_token(installation.installation_id)
                remote_by_id = {
                    int(item["id"]): int(item["number"])
                    for item in get_all_pull_requests(repository.full_name, token)
                    if item.get("id") is not None
                    and item.get("number") is not None
                }
                for pull_request in pull_requests:
                    number = remote_by_id.get(pull_request.github_pr_id)
                    if number is not None:
                        pull_request.github_pr_number = number
                        print(
                            f"resolved pr_pk={pull_request.id} "
                            f"github_pr_number={number}"
                        )
            db.commit()
            unresolved = unresolved_query.all()

        for pull_request in unresolved:
            print(
                f"pr_pk={pull_request.id} "
                f"github_pr_id={pull_request.github_pr_id} "
                f"repository={pull_request.repository.full_name}"
            )
        if unresolved:
            raise SystemExit(
                f"{len(unresolved)} pull request(s) remain unresolved"
            )
        if arguments.enforce_not_null:
            if db.bind.dialect.name != "postgresql":
                raise SystemExit(
                    "--enforce-not-null requires PostgreSQL"
                )
            db.execute(
                text(
                    "ALTER TABLE pull_requests "
                    "ALTER COLUMN github_pr_number SET NOT NULL"
                )
            )
            db.commit()
            print("Applied pull_requests.github_pr_number NOT NULL contract.")
        print("All pull requests have repository-scoped GitHub numbers.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
