"""Create an idempotent demo workspace around an ingested GitHub pull request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.demo_service import (
    DemoBootstrapError,
    bootstrap_demo_workspace,
    demo_mode_enabled,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bind owner, reviewer, finance, and contributor demo personas to "
            "a real GitHub repository and ingested pull request."
        )
    )
    parser.add_argument(
        "--repository",
        required=True,
        help="GitHub repository in owner/name form.",
    )
    parser.add_argument(
        "--pr-number",
        required=True,
        type=int,
        help="The GitHub pull request number already ingested by the worker.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not demo_mode_enabled():
        raise SystemExit(
            "Demo mode is disabled. Set DEMO_MODE=true in a non-production "
            "environment before bootstrapping."
        )
    if len(settings.DEMO_ACCESS_KEY) < 16:
        raise SystemExit("DEMO_ACCESS_KEY must contain at least 16 characters.")

    db = SessionLocal()
    try:
        workspace = bootstrap_demo_workspace(
            db,
            repository_full_name=args.repository,
            pull_request_number=args.pr_number,
        )
        db.commit()
    except DemoBootstrapError as exc:
        db.rollback()
        raise SystemExit(str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(
        json.dumps(
            {
                "status": "ready",
                "workspace": workspace.workspace,
                "repository": workspace.repository,
                "pull_request_id": workspace.pull_request_id,
                "pull_request_number": workspace.pull_request_number,
                "personas": workspace.personas,
                "next": (
                    "Run scripts/run_demo_flow.py after the PR is merged and "
                    "the final webhook analysis completes."
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
