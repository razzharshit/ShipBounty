# GitHub Bounty Dispenser Showcase Runbook

This runbook demonstrates the complete product path with a real GitHub test
repository:

`GitHub issue → pull request webhook → queued synchronization → deterministic analysis → human review → owner approval → bounty → claim → two treasury approvals → provider-controlled off-chain settlement`

The GitHub delivery, current PR state, file snapshot, analyzer evidence, review,
approval, bounty, claim, treasury reservation, reconciliation, audit events, and
notification records are real application records. Settlement uses the deterministic
`ledger` provider; no blockchain transaction or money movement occurs.

## 1. Safety boundary

Demo authentication is unavailable by default and fails closed:

- `DEMO_MODE` defaults to `false`.
- `DEMO_MODE=true` is rejected when `APP_ENV=production`.
- The API hides `/auth/demo` with `404` whenever demo mode is unavailable.
- A demo access key must contain at least 16 characters.
- Only users explicitly listed in `demo_personas` can use demo login.
- Every demo persona is scoped to one organization and receives repository-specific
  authorization.
- Every demo login creates an `auth.demo_login` audit record.
- Synthetic owner, reviewer, and finance identities use negative GitHub IDs so they
  cannot be mistaken for real GitHub identities.
- The contributor persona is the actual author of the selected, ingested PR.

Never enable demo mode in a public or production deployment. Do not reuse a
production credential as `DEMO_ACCESS_KEY`.

## 2. Demo personas

The bootstrap command creates one demo workspace with four identities:

| Persona | Effective role | Showcase responsibility |
|---|---|---|
| Owner | `OWNER` | Versions policy, approves eligibility, creates/funds the bounty and treasury, and provides one treasury approval |
| Reviewer | `REVIEWER` | Evaluates eligibility and submits the human review |
| Finance | `ADMIN` | Provides the independent treasury approval and submits through the configured provider |
| Contributor | `CONTRIBUTOR` | The real GitHub PR author; registers a destination and claims the bounty |

Reviewer and owner remain different users. The contributor cannot review or approve
their own work.

## 3. Prerequisites

Install or provide:

- Docker with Docker Compose;
- Python 3 and a virtual environment;
- Node.js/npm supported by the frontend;
- a GitHub account that can create a GitHub App and a test repository;
- a public HTTPS URL that forwards to local port `8000` for GitHub webhook delivery;
- optionally, GitHub CLI (`gh`) to retrieve the issue database ID.

Use `localhost` consistently for both frontend and backend. Do not mix `localhost`
and `127.0.0.1`, because the browser session cookie is host-scoped.

## 4. Configure the GitHub App

Create a private GitHub App for the test account or organization. GitHub documents
the registration fields and installation behavior in
[Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app).

Use these values:

| GitHub App setting | Demo value |
|---|---|
| Homepage URL | `http://localhost:3000` or the project page |
| User authorization callback URL | `http://localhost:8000/auth/github/callback` |
| Request user authorization during installation | Enabled |
| Webhook active | Enabled |
| Webhook URL | `https://YOUR-PUBLIC-HTTPS-HOST/webhook/github` |
| Webhook secret | A new random secret, identical to `GITHUB_WEBHOOK_SECRET` |
| Installation scope | Only the test account is sufficient |

Minimum permissions for this implementation:

| Permission group | Permission | Access |
|---|---|---|
| Repository | Pull requests | Read-only |
| Repository | Checks | Read-only |
| Organization | Members | Read-only |
| Account | Email addresses | Read-only if email synchronization is desired |

Subscribe to:

- Pull request
- Pull request review
- Check run
- Check suite

GitHub only displays webhook subscriptions allowed by the selected permissions, and
recommends selecting the minimum permissions required. See
[Choosing permissions for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app).

After the app is created:

1. Record the App ID, client ID, and client secret.
2. Generate and download a private key.
3. Install the app on the test account.
4. Select only the repository intended for the demo.

The webhook receiver verifies `X-Hub-Signature-256`, persists
`X-GitHub-Delivery`, commits an outbox record, and responds before doing GitHub API
work. This follows GitHub's
[webhook best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks).

## 5. Configure the backend

From the repository root:

```bash
cd backend
cp .env.example .env
```

Set at least:

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/github_bounty_dispenser
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0

GITHUB_WEBHOOK_SECRET=THE_SAME_RANDOM_WEBHOOK_SECRET
GITHUB_APP_ID=YOUR_APP_ID
GITHUB_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
GITHUB_OAUTH_CLIENT_ID=YOUR_CLIENT_ID
GITHUB_OAUTH_CLIENT_SECRET=YOUR_CLIENT_SECRET
GITHUB_OAUTH_REDIRECT_URI=http://localhost:8000/auth/github/callback
FRONTEND_URL=http://localhost:3000

AUTH_JWT_KEYS=v1:AT_LEAST_32_RANDOM_CHARACTERS
TOKEN_ENCRYPTION_KEYS=v1:A_VALID_FERNET_KEY
SESSION_COOKIE_NAME=gbd_session

DEMO_MODE=true
DEMO_ACCESS_KEY=AT_LEAST_16_RANDOM_CHARACTERS
```

Generate independent development values with:

```bash
openssl rand -hex 32
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Enable only the deterministic demo ledger and keep mainnet/manual mutation disabled:

```dotenv
PAYOUTS_ENABLED=true
PAYOUTS_EMERGENCY_PAUSED=false
PAYOUTS_ALLOW_MAINNET=false
ALLOW_MANUAL_PAYOUT_STATE=false
```

These flags allow the provider-controlled `ledger` treasury used by the script.
They do not enable mainnet. Never substitute a real custody provider or treasury
credential in the demo environment.

## 6. Configure the frontend

Create or update `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_URL=http://localhost:3000
AUTH_SESSION_COOKIE_NAME=gbd_session
NEXT_PUBLIC_DEMO_MODE=true
NEXT_PUBLIC_DEMO_WORKSPACE=YOUR_GITHUB_OWNER_OR_ORGANIZATION_LOGIN
```

`NEXT_PUBLIC_DEMO_WORKSPACE` is a convenience default, not a secret.

## 7. Start the platform

Use separate terminals.

### Terminal A — PostgreSQL and Redis

```bash
cd backend
docker compose -f compose.yml up -d
```

### Terminal B — backend installation and migrations

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Verify `http://localhost:8000/health` returns:

```json
{"status":"ok"}
```

### Terminal C — Celery worker

```bash
cd backend
source .venv/bin/activate
celery -A app.worker.celery_app:celery_app worker \
  --queues github_ingestion,outbox_dispatch,notifications,operations,payouts,ai_review \
  --concurrency 4
```

### Terminal D — Celery Beat

```bash
cd backend
source .venv/bin/activate
celery -A app.worker.celery_app:celery_app beat
```

### Terminal E — frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000/login`.

## 8. Synchronize the GitHub installation

Before using demo login, click **Continue with GitHub** once.

The OAuth flow synchronizes:

- your GitHub user;
- organization membership;
- GitHub App installations;
- repositories visible through those installations;
- repository permissions;
- an encrypted user access token.

The application never permanently stores an installation access token. Workers mint
short-lived installation tokens as needed.

After OAuth, confirm the test organization appears on the product dashboard.

## 9. Create the real GitHub test scenario

In the selected repository:

1. Create a GitHub issue with clear acceptance criteria.
2. Create a branch.
3. Make a small, reviewable change.
4. Include at least one test-file change when the repository contains production
   code.
5. Include a documentation change if appropriate.
6. Open a PR that references the issue, for example `Closes #1`.
7. Wait for configured CI checks to finish.

Recommended small showcase change:

- one source file;
- one test file;
- one README or documentation update;
- no generated or binary files.

This produces understandable analyzer evidence and avoids an artificially risky
diff.

## 10. Verify ingestion before bootstrap

Open `http://localhost:3000/dashboard/YOUR_ORGANIZATION_LOGIN/operations`.

Expected sequence:

```text
RECEIVED → QUEUED → PROCESSING → COMPLETE
```

Confirm:

- recent webhook delivery is visible;
- queue/outbox depth returns to zero;
- worker heartbeat is fresh;
- no delivery failure remains;
- the PR appears under **Pull Requests**;
- file snapshot is complete;
- the expected files and patches appear;
- a deterministic score and analyzer evidence exist.

If the delivery does not arrive, inspect the GitHub App's **Advanced** delivery page.
GitHub expects a 2xx response within 10 seconds and retains the delivery ID across a
requested redelivery.

## 11. Bootstrap the demo workspace

The PR must already be ingested. It may still be open for this step.

```bash
cd backend
source .venv/bin/activate
python scripts/bootstrap_demo.py \
  --repository OWNER/REPOSITORY \
  --pr-number PR_NUMBER
```

Example:

```bash
python scripts/bootstrap_demo.py \
  --repository octocat/bounty-showcase \
  --pr-number 3
```

The command is idempotent. It prints the workspace login, internal PR ID, and persona
usernames. It does not print the demo access key.

## 12. Rehearse persona switching

Sign out and revisit `http://localhost:3000/login`. The showcase panel appears only
when `NEXT_PUBLIC_DEMO_MODE=true`.

For each persona:

1. select the role;
2. enter the workspace login printed by bootstrap;
3. enter `DEMO_ACCESS_KEY`;
4. open **Showcase Guide**.

Use this narration:

- **Contributor** is the real GitHub PR author.
- **Reviewer** evaluates evidence but cannot finalize payment eligibility.
- **Owner** approves eligibility but cannot be the same user as reviewer.
- **Finance** is ready for integrated treasury approval scenarios.

## 13. Merge and process the final head

Merge the PR on GitHub.

The `pull_request.closed` delivery is interpreted as:

- `MERGED` when `pull_request.merged` is true;
- `CLOSED` otherwise.

Wait until the final delivery is `COMPLETE`, the PR lifecycle is `merged`, the file
snapshot is complete, and the latest score matches the final head SHA.

## 14. Retrieve the GitHub issue database ID

The demo API stores both the issue number and GitHub's numeric database ID. With
GitHub CLI:

```bash
gh api repos/OWNER/REPOSITORY/issues/ISSUE_NUMBER --jq .id
```

Copy the printed number. This is different from the visible issue number.

## 15. Run the complete automated showcase

Keep the API running, then:

```bash
cd backend
source .venv/bin/activate
python scripts/run_demo_flow.py \
  --repository OWNER/REPOSITORY \
  --pr-number PR_NUMBER \
  --issue-number ISSUE_NUMBER \
  --github-issue-id GITHUB_ISSUE_DATABASE_ID \
  --issue-title "Improve the showcase feature" \
  --amount 25 \
  --currency USDC
```

The script reads `DEMO_ACCESS_KEY` from backend `.env`. It uses separate HTTP cookie
sessions for owner, reviewer, finance, and contributor, so API authentication,
authorization, validation, notifications, and audit logging are exercised.

Expected output:

```text
1/12 Demo policy versioned
2/12 Eligibility evaluated
3/12 Human review approved
4/12 Eligibility approved
5/12 Bounty created and funded
6/12 Bounty assigned to PR author
7/12 Demo destination registered and verified
8/12 Claim approved
9/12 Treasury payout authorized by two roles
10/12 Provider-controlled submission recorded
11/12 Provider reconciliation confirmed settlement
12/12 Showcase complete
```

The script creates a demo-only eligibility policy that still requires:

- a merged PR;
- complete synchronized inputs;
- a current score for the head SHA;
- human review;
- owner/admin approval;
- reviewer/approver separation;
- no author self-review or self-approval;
- no prior payout.

For predictable demonstration, that policy sets the minimum score to zero and does
not require the score to be authoritative. The deterministic score and its confidence
are still retained and displayed; the relaxation is explicit in the immutable policy
version and audit log.

## 16. Validate the final result

Refresh:

- `/demo` for the guided view;
- `/pull-requests` for lifecycle, review, eligibility, and score;
- `/dashboard/ORGANIZATION_SLUG/operations` for delivery and aggregate worker telemetry;
- `/dashboard/ORGANIZATION_SLUG/product` for bounty, claim, payout, contributor, and notification
  analytics.

Expected final domain states:

| Domain | Expected state |
|---|---|
| Pull request lifecycle | `merged` |
| File synchronization | complete |
| Eligibility decision | `eligible` before claim |
| PR payout eligibility | `paid` after settlement |
| Bounty | `paid` |
| Funding | `exhausted` |
| Assignment | `completed` |
| Claim | `paid` |
| Payout | `confirmed` |
| Payout attempt | `submitted` |

The transaction reference begins with `ledger:ledger_`. It is an off-chain provider
reference, not a blockchain transaction hash, and must not be presented as one.

## 17. Presenter script

A concise seven-minute narrative:

1. **GitHub issue and PR** — show the real requirements, files, tests, and merge.
2. **Operations** — show the delivery ID, asynchronous queue, worker completion, and
   rate-limit telemetry.
3. **PR evidence** — show the complete file snapshot, patches, metrics, analyzer
   statuses, score version, confidence, and head SHA.
4. **Reviewer persona** — explain the human review and structured findings.
5. **Owner persona** — explain immutable policy/score provenance and separation of
   duties.
6. **Bounty and claim** — show issue linkage, funded assignment, verified destination,
   and claimant/PR-author match.
7. **Settlement and audit** — show separate authorized, submitted, and confirmed
   states, then notifications and product analytics.

## 18. Failure demonstrations

Use these only in a disposable rehearsal:

- Send the same GitHub delivery again: the API returns duplicate and creates no
  second effective job.
- Close a PR without merging: lifecycle becomes `closed`, and eligibility fails
  `PULL_REQUEST_NOT_MERGED`.
- Disable the worker: deliveries remain observable and recoverable in the outbox.
- Use a wrong demo access key: login returns `401`.
- Set `APP_ENV=production` with demo mode: configuration refuses to start.
- Attempt review as the contributor: author self-review is rejected.
- Attempt approval as the reviewer after reviewing: separation of duties rejects it.
- Use an unverified wallet: claim creation is rejected.
- Replay payout creation with the same idempotency key: the existing payout is
  returned.

## 19. Repeating the showcase

Do not delete financial or audit history to rerun a demo. Use:

- a new GitHub issue;
- a new branch and PR;
- the same repository;
- the same demo access key if it is still private;
- `bootstrap_demo.py` with the new PR number;
- `run_demo_flow.py` with the new issue and PR numbers.

The bootstrap updates the contributor persona to the new PR author and removes the
old demo-only contributor grant when the author changes. Historic application
records remain intact.

## 20. Troubleshooting

### Demo login returns 404

- Confirm backend `DEMO_MODE=true`.
- Confirm `APP_ENV` is not `production`.
- Restart the backend after changing `.env`.

### Demo login returns 401

- Confirm the access key matches exactly.
- Confirm bootstrap completed.
- Use the organization/repository owner login printed by bootstrap.

### Repository is not synchronized

- Install the GitHub App on the repository.
- Use **Continue with GitHub** once.
- Confirm the installation is visible to the OAuth user.

### PR is not ingested

- Confirm the webhook public URL ends with `/webhook/github`.
- Confirm webhook secret values match.
- Confirm Pull request events are subscribed.
- Inspect GitHub App delivery response and redeliver after fixing.

### Delivery remains received or queued

- Confirm Redis is healthy.
- Confirm Celery Beat is dispatching the outbox.
- Confirm the worker listens to `outbox_dispatch` and `github_ingestion`.

### Analysis is incomplete

- Confirm the worker can mint an installation token.
- Confirm Pull requests read permission.
- Confirm the PR does not exceed GitHub's 3,000-file API cap.
- Inspect delivery `last_error` and retry count in operations.

### Demo runner reports ineligible

- Confirm the PR is merged.
- Wait for the final head synchronization.
- Confirm `file_sync_complete=true`.
- Confirm a latest deterministic score exists.
- Do not reuse a PR that already has a paid claim.

### Browser signs in but server pages redirect to login

- Use `localhost` for both origins.
- Keep backend and frontend cookie names equal.
- Restart the frontend after `.env.local` changes.

## 21. Switching to a real testnet provider

The default showcase ends with a simulated off-chain confirmation. A separate,
advanced rehearsal can use `base_sepolia_custody`, but only after a custody service,
multisig policy, funded testnet treasury, exact USDC contract, confirmations, and
reconciliation are configured. Do not put a treasury private key in this application
or its database.

Keep:

- `PAYOUTS_ALLOW_MAINNET=false`;
- a Base Sepolia-only treasury;
- low per-payout and daily limits;
- manual approval thresholds;
- transaction simulation;
- emergency pause;
- reconciliation monitoring.

That advanced test is intentionally outside the default demo runner.
