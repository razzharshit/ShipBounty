"""Exercise the complete demo through authenticated HTTP API calls.

The GitHub PR and deterministic analysis are real. Settlement uses the
provider-controlled, deterministic off-chain ledger; manual payout state
endpoints are never used and no blockchain transaction is created.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.demo import DemoPersona
from app.models.pull_request import PullRequest, PullRequestState
from app.models.repository import Repository
from app.services.demo_service import demo_mode_enabled
from app.services.eligibility_service import DEFAULT_ELIGIBILITY_RULES


@dataclass(frozen=True)
class DemoContext:
    workspace: str
    organization_id: int
    repository_id: int
    pull_request_id: int
    contributor_user_id: int


class DemoFlowError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the review-to-confirmed-payout showcase flow."
    )
    parser.add_argument("--repository", required=True, help="owner/name")
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--github-issue-id", required=True, type=int)
    parser.add_argument(
        "--issue-title", default="Showcase bounty issue"
    )
    parser.add_argument("--amount", default="25")
    parser.add_argument("--currency", default="USDC")
    parser.add_argument("--wallet-chain", default="demo-ledger")
    parser.add_argument(
        "--wallet-address",
        default="demo:contributor",
        help="A non-production demo destination.",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
    )
    parser.add_argument(
        "--access-key",
        default=None,
        help="Defaults to DEMO_ACCESS_KEY; prefer the environment variable.",
    )
    return parser.parse_args()


def preflight(repository_full_name: str, pr_number: int) -> DemoContext:
    db = SessionLocal()
    try:
        repository = (
            db.query(Repository)
            .filter(Repository.full_name == repository_full_name)
            .first()
        )
        if repository is None:
            raise DemoFlowError("Repository is not synchronized.")
        pull_request = (
            db.query(PullRequest)
            .filter(
                PullRequest.repo_id == repository.id,
                PullRequest.github_pr_number == pr_number,
            )
            .first()
        )
        if pull_request is None:
            raise DemoFlowError("Pull request is not ingested.")
        if pull_request.state != PullRequestState.MERGED:
            raise DemoFlowError("Pull request must be merged before the demo flow.")
        if not pull_request.file_sync_complete or pull_request.latest_score_id is None:
            raise DemoFlowError(
                "Wait for complete file synchronization and deterministic scoring."
            )
        mappings = {
            item.persona: item
            for item in (
                db.query(DemoPersona)
                .filter(
                    DemoPersona.organization_id == repository.organization_id
                )
                .all()
            )
        }
        missing = {"owner", "reviewer", "finance", "contributor"} - set(mappings)
        if missing:
            raise DemoFlowError(
                "Bootstrap the demo workspace first; missing personas: "
                + ", ".join(sorted(missing))
            )
        if mappings["contributor"].user_id != pull_request.author_id:
            raise DemoFlowError(
                "Contributor persona is not the current PR author. Rerun bootstrap."
            )
        return DemoContext(
            workspace=repository.organization.login,
            organization_id=repository.organization_id,
            repository_id=repository.id,
            pull_request_id=pull_request.id,
            contributor_user_id=pull_request.author_id,
        )
    finally:
        db.close()


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    expected: set[int] = {200, 201, 202},
    **kwargs,
) -> dict:
    response = session.request(method, url, timeout=30, **kwargs)
    if response.status_code not in expected:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text
        raise DemoFlowError(
            f"{method} {url} failed ({response.status_code}): {detail}"
        )
    if not response.content:
        return {}
    value = response.json()
    if not isinstance(value, dict):
        raise DemoFlowError(f"{method} {url} returned an unexpected response")
    return value


def login(
    api_url: str,
    workspace: str,
    persona: str,
    access_key: str,
) -> requests.Session:
    session = requests.Session()
    payload = {
        "workspace": workspace,
        "persona": persona,
        "access_key": access_key,
    }
    request_json(session, "POST", f"{api_url}/auth/demo", json=payload)
    return session


def main() -> None:
    args = parse_args()
    if not demo_mode_enabled():
        raise SystemExit("DEMO_MODE must be enabled outside production.")
    if not settings.PAYOUTS_ENABLED or settings.PAYOUTS_EMERGENCY_PAUSED:
        raise SystemExit(
            "The demo ledger requires PAYOUTS_ENABLED=true and "
            "PAYOUTS_EMERGENCY_PAUSED=false."
        )
    access_key = args.access_key or settings.DEMO_ACCESS_KEY
    if len(access_key) < 16:
        raise SystemExit("A demo access key of at least 16 characters is required.")
    try:
        context = preflight(args.repository, args.pr_number)
        api_url = args.api_url.rstrip("/")
        owner = login(api_url, context.workspace, "owner", access_key)
        reviewer = login(api_url, context.workspace, "reviewer", access_key)
        finance = login(api_url, context.workspace, "finance", access_key)
        contributor = login(
            api_url, context.workspace, "contributor", access_key
        )

        demo_rules = {
            **DEFAULT_ELIGIBILITY_RULES,
            "require_authoritative_score": False,
            "minimum_score": 0,
        }
        policy = request_json(
            owner,
            "PUT",
            f"{api_url}/repositories/{context.repository_id}/eligibility-policy",
            json={
                "name": "Showcase policy",
                "description": (
                    "Demo-only policy: complete GitHub inputs, merge, human "
                    "review, approval, and separation of duties remain required."
                ),
                "rules": demo_rules,
            },
        )
        print("1/12 Demo policy versioned", policy["version"])

        decision = request_json(
            reviewer,
            "POST",
            f"{api_url}/prs/{context.pull_request_id}/eligibility-decisions",
        )
        if decision["status"] != "pending_review":
            raise DemoFlowError(
                "Eligibility did not enter pending_review: "
                + json.dumps(decision.get("failure_reasons"))
            )
        print("2/12 Eligibility evaluated", decision["id"])

        review = request_json(
            reviewer,
            "POST",
            f"{api_url}/eligibility-decisions/{decision['id']}/reviews",
            json={
                "recommendation": "approve",
                "summary": (
                    "Showcase reviewer verified the synchronized evidence and "
                    "deterministic analysis."
                ),
                "findings": [],
            },
        )
        print("3/12 Human review approved", review["id"])

        approval = request_json(
            owner,
            "POST",
            f"{api_url}/eligibility-decisions/{decision['id']}/approvals",
            json={
                "outcome": "approved",
                "reason": "Showcase owner approval with reviewer separation.",
            },
        )
        print("4/12 Eligibility approved", approval["id"])

        issue = request_json(
            owner,
            "POST",
            f"{api_url}/repositories/{context.repository_id}/issues",
            json={
                "github_issue_id": args.github_issue_id,
                "number": args.issue_number,
                "title": args.issue_title,
                "description": "Real GitHub test issue used by the showcase.",
                "url": (
                    f"https://github.com/{args.repository}/issues/"
                    f"{args.issue_number}"
                ),
                "state": "open",
            },
        )
        bounty = request_json(
            owner,
            "POST",
            f"{api_url}/issues/{issue['id']}/bounties",
            json={
                "amount": args.amount,
                "currency": args.currency,
                "expires_at": None,
            },
        )
        bounty = request_json(
            owner,
            "POST",
            f"{api_url}/bounties/{bounty['id']}/fund",
        )
        print("5/12 Bounty created and funded", bounty["id"])

        assignment = request_json(
            owner,
            "POST",
            f"{api_url}/bounties/{bounty['id']}/assign",
            json={
                "assignee_user_id": context.contributor_user_id,
                "pull_request_id": context.pull_request_id,
            },
        )
        print("6/12 Bounty assigned to PR author", assignment["id"])

        wallet = request_json(
            contributor,
            "POST",
            f"{api_url}/wallets",
            json={
                "chain": args.wallet_chain,
                "address": args.wallet_address,
            },
        )
        wallet = request_json(
            owner,
            "POST",
            (
                f"{api_url}/bounties/{bounty['id']}/wallets/"
                f"{wallet['id']}/verify"
            ),
        )
        print("7/12 Demo destination registered and verified", wallet["id"])

        claim = request_json(
            contributor,
            "POST",
            f"{api_url}/bounties/{bounty['id']}/claims",
            json={
                "assignment_id": assignment["id"],
                "pull_request_id": context.pull_request_id,
                "eligibility_decision_id": decision["id"],
                "wallet_id": wallet["id"],
            },
        )
        print("8/12 Claim approved", claim["id"])

        run_id = uuid.uuid4().hex
        treasury = request_json(
            owner,
            "POST",
            f"{api_url}/organizations/{context.organization_id}/treasuries",
            json={
                "provider_key": "ledger",
                "environment": "testnet",
                "chain": args.wallet_chain,
                "currency": args.currency,
                "treasury_address": f"demo:treasury:{run_id}",
                "asset_decimals": 6,
                "custody_model": "off_chain",
                "opening_balance": "10000",
                "per_payout_limit": "1000",
                "daily_spending_limit": "5000",
                "manual_approval_threshold": None,
                "standard_required_approvals": 2,
                "high_value_required_approvals": 2,
                "required_confirmations": 1,
                "simulation_required": True,
                "provider_config": {"purpose": "showcase"},
            },
        )
        treasury = request_json(
            owner,
            "POST",
            f"{api_url}/treasuries/{treasury['id']}/pause",
            json={"paused": False, "reason": "Showcase ledger activation"},
        )
        payout = request_json(
            owner,
            "POST",
            f"{api_url}/claims/{claim['id']}/payouts",
            json={
                "idempotency_key": f"demo-payout-{run_id}",
                "treasury_account_id": treasury["id"],
            },
        )
        request_json(
            owner,
            "POST",
            f"{api_url}/payouts/{payout['id']}/treasury-approvals",
            json={"decision": "approved", "reason": "Owner treasury approval"},
        )
        request_json(
            finance,
            "POST",
            f"{api_url}/payouts/{payout['id']}/treasury-approvals",
            json={"decision": "approved", "reason": "Finance treasury approval"},
        )
        print("9/12 Treasury payout authorized by two roles", payout["id"])

        attempt = request_json(
            finance,
            "POST",
            f"{api_url}/payouts/{payout['id']}/submit",
            json={"idempotency_key": f"demo-attempt-{run_id}"},
        )
        print("10/12 Provider-controlled submission recorded", attempt["id"])

        payout = request_json(
            finance,
            "GET",
            f"{api_url}/payouts/{payout['id']}",
        )
        if payout["state"] != "confirmed":
            raise DemoFlowError(
                f"Ledger provider did not confirm payout: {payout['state']}"
            )
        print("11/12 Provider reconciliation confirmed settlement", payout["id"])
        print(
            "12/12 Showcase complete\n"
            + json.dumps(
                {
                    "repository": args.repository,
                    "pull_request_id": context.pull_request_id,
                    "eligibility_decision_id": decision["id"],
                    "bounty_id": bounty["id"],
                    "claim_id": claim["id"],
                    "payout_id": payout["id"],
                    "payout_state": payout["state"],
                    "transaction_reference": payout["transaction_hash"],
                    "settlement": (
                        "deterministic off-chain demo provider; no funds moved"
                    ),
                },
                indent=2,
            )
        )
    except (DemoFlowError, requests.RequestException) as exc:
        print(f"Demo flow stopped: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
