# ShipBounty - Backend

FastAPI backend with durable, asynchronous GitHub webhook ingestion.

## Tech Stack

- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Celery
- Redis
- Flower
- python-dotenv

## Project Structure

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   ├── models/
│   ├── schemas/
│   ├── db/
│   ├── services/
│   └── core/
├── alembic/
├── alembic.ini
├── .env
├── requirements.txt
└── README.md
```

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Start PostgreSQL and Redis:

   ```bash
   docker compose up -d postgres redis
   ```

4. Copy `.env.example` to `.env` and provide the GitHub App, session, and
   encryption credentials:

   ```env
   cp .env.example .env
   ```

5. Run migrations:

   ```bash
   alembic upgrade head
   ```

6. Start the API:

   ```bash
   uvicorn app.main:app --reload
   ```

7. Start a worker and the outbox dispatcher:

   ```bash
   celery -A app.worker.celery_app:celery_app worker \
     --queues github_ingestion,outbox_dispatch,notifications,operations,payouts,ai_review \
     --concurrency 4
   ```

   In a separate process:

   ```bash
   celery -A app.worker.celery_app:celery_app beat
   ```

   Optional monitoring:

   ```bash
   celery -A app.worker.celery_app:celery_app flower
   ```

8. Run the test suite:

   ```bash
   pip install -r requirements-dev.txt
   pytest
   ```

## API Endpoints

- `GET /` -> `{"message": "API running"}`
- `GET /health` -> basic app and DB health probe
- `GET /auth/github/start` -> begin GitHub App user authorization with state and PKCE
- `GET /auth/github/callback` -> synchronize identity and establish a secure session
- `GET /auth/me` -> return the authenticated user
- `POST /auth/demo` -> non-production, explicitly bootstrapped showcase persona login
- `POST /auth/logout` -> revoke the user's current application sessions
- `GET /organizations` -> list accessible tenants and effective roles
- `GET /organizations/{id}/repositories` -> list authorized repositories
- `GET /organizations/{id}/audit-logs` -> organization audit trail for admins
- `GET /platform/operations/unresolved-deliveries` -> unresolved signed deliveries
  for allowlisted platform administrators
- `GET /platform/operations/workers` -> detailed worker identity and metadata for
  allowlisted platform administrators
- `GET /prs` -> list pull requests in authorized repositories
- `POST /prs` -> create a PR record with `MAINTAINER` access
- `POST /prs/{id}/resync` -> enqueue a current-state GitHub synchronization
- `GET /scores/{pr_id}` -> fetch the latest deterministic score
- `GET /prs/{pr_id}/scores` -> fetch immutable score history
- `GET /prs/{pr_id}/analysis-runs` -> inspect analyzer results and errors
- `GET /repositories/{id}/scoring-policy` -> inspect repository scoring weights
- `PUT /repositories/{id}/scoring-policy` -> version a new repository policy
- `GET|PUT /repositories/{id}/eligibility-policy` -> inspect or version review gates
- `POST /prs/{id}/eligibility-decisions` -> evaluate the latest score against policy
- `GET /prs/{id}/eligibility-decisions` -> inspect versioned decision history
- `POST /eligibility-decisions/{id}/reviews` -> submit human findings/recommendation
- `POST /eligibility-decisions/{id}/approvals` -> approve or reject payout eligibility
- `GET|PUT /repositories/{id}/bounty-policy` -> inspect or version bounty rules
- `POST /repositories/{id}/issues` -> synchronize an issue before creating a bounty
- `POST /issues/{id}/bounties` -> create a policy-bound bounty
- `POST /bounties/{id}/fund` -> record that bounty funding is available
- `POST /bounties/{id}/assign` -> assign a funded bounty
- `POST /bounty-assignments/{id}/link-pr` -> link requirements to the assignee's PR
- `POST /wallets` -> register a user payout destination
- `POST /bounties/{id}/claims` -> create an approved, financially snapshotted claim
- `POST /claims/{id}/payouts` -> idempotently create one payout for a claim
- legacy payout-state mutation routes -> hidden unless the non-production manual
  state gate is explicitly enabled
- `GET|POST /organizations/{id}/treasuries` -> inspect or create a paused treasury
- `POST /treasuries/{id}/pause` -> activate or emergency-pause a treasury
- `GET /treasuries/{id}/ledger` -> inspect immutable reservations and settlements
- `POST /treasuries/{id}/reconcile-balance` -> compare observed custody balance
- `POST /payouts/{id}/treasury-approvals` -> record a distinct treasury decision
- `POST /payouts/{id}/submit` -> simulate and idempotently submit through a provider
- `POST /payouts/{id}/reconcile` -> poll provider confirmation state
- `GET /payouts/{id}/reconciliations` -> inspect immutable status observations
- `GET|PUT /repositories/{id}/ai-review-policy` -> inspect or version AI/privacy rules
- `POST /prs/{id}/ai-reviews` -> build a privacy-filtered advisory review request
- `GET /prs/{id}/ai-reviews` -> inspect immutable AI review history
- legacy AI complete/fail routes -> hidden unless the non-production manual state
  gate is explicitly enabled
- `GET /organizations/{id}/operations-dashboard` -> live ingestion and worker telemetry
- `GET /organizations/{id}/product-analytics` -> tenant-scoped bounty and review analytics
- `GET /notifications` -> current user's in-app delivery history
- `POST /notifications/{id}/read` -> mark an in-app notification as read
- `POST /webhook/github` -> durable GitHub webhook receiver (HMAC SHA256 validated)

All endpoints other than `/`, `/health`, the OAuth entry/callback, and the signed
GitHub webhook require the `gbd_session` HTTP-only cookie or a bearer session JWT.
`POST /auth/demo` is an additional entry route only when `DEMO_MODE=true` outside
production; disabled environments return `404`.

### Legacy GitHub PR-number contract

Migration `20260725_0014` first backfills repository-scoped PR numbers from stored
signed deliveries. For older rows without delivery evidence, run:

```bash
python scripts/audit_github_pr_numbers.py --backfill
python scripts/audit_github_pr_numbers.py --enforce-not-null
```

The first command follows GitHub pagination and matches the immutable global PR ID.
The second refuses to apply PostgreSQL `NOT NULL` until no unresolved row remains.

## Showcase mode

The root [demo runbook](../DEMO_RUNBOOK.md) explains how to connect a disposable
GitHub repository and exercise the complete real-ingestion-to-simulated-settlement
flow. In summary:

```bash
python scripts/bootstrap_demo.py \
  --repository OWNER/REPOSITORY \
  --pr-number PR_NUMBER

python scripts/run_demo_flow.py \
  --repository OWNER/REPOSITORY \
  --pr-number PR_NUMBER \
  --issue-number ISSUE_NUMBER \
  --github-issue-id GITHUB_ISSUE_DATABASE_ID
```

Demo mode is fail-closed, cannot run with `APP_ENV=production`, and uses explicit
tenant-scoped owner, reviewer, finance, and real-PR-author personas. The final demo
settlement is synthetic and moves no funds.

## Tenancy and authorization

Every repository has a non-null `organization_id`. Pull requests, files, metrics,
scores, and analysis runs inherit their tenant boundary through the repository.
Existing repositories are backfilled into organizations by owner during migration.

Authorization has two independent sources:

- a GitHub-verified organization membership; and
- a repository permission synchronized from the repositories visible through the
  user's GitHub App installations.

Organization owners can administer every organization repository. Other organization
members must have a current repository permission, preventing membership alone from
exposing private repositories. Roles are ordered `OWNER`, `ADMIN`, `MAINTAINER`,
`REVIEWER`, `CONTRIBUTOR`, and `VIEWER`. Collection queries filter inaccessible rows
in SQL, while individual resource queries authorize before loading business data.

GitHub App user authorization uses OAuth state and PKCE. The resulting user and
refresh tokens are encrypted with the primary Fernet key in
`TOKEN_ENCRYPTION_KEYS`. Installation access tokens are never stored: workers mint
their short-lived token when a GitHub API operation starts. The automatic
`github_app_authorization.revoked` webhook removes stored user credentials and
GitHub-sourced permissions and invalidates existing application sessions.

Redis enforces a fixed-window API rate limit. Development falls back to an in-process
limiter when Redis is unavailable; production fails closed. Security-sensitive
events—including login, logout, role changes, access denials, synchronization, and
authorization revocation—are recorded in `audit_logs`.

### Required GitHub App permissions

Configure user authorization and a callback matching `GITHUB_OAUTH_REDIRECT_URI`.
The app needs organization members read access to verify membership, account email
read access if email synchronization is required, and the repository metadata/pull
request permissions already needed by ingestion. Subscribe to pull request, pull
request review, and the automatic GitHub App authorization events.

### Secret rotation

Both `AUTH_JWT_KEYS` and `TOKEN_ENCRYPTION_KEYS` are comma-separated keyrings in
`key-id:secret` form. The first key is used for new data; older keys remain available
for verification/decryption.

1. Prepend a new key and deploy.
2. For OAuth encryption, run
   `python scripts/rotate_oauth_tokens.py` to re-encrypt all rows atomically.
3. Keep old JWT keys for at least `AUTH_SESSION_TTL_SECONDS`.
4. Remove retired keys and redeploy.

Rotate the GitHub App private key by adding the replacement in GitHub, deploying the
replacement `GITHUB_PRIVATE_KEY`, verifying token minting, and only then deleting the
old key. Rotate the webhook secret with an overlap or coordinated deployment so
in-flight deliveries are not rejected. Never place secrets or generated installation
tokens in the database or logs.

## Reliable webhook flow

The request path only:

1. verifies `X-Hub-Signature-256`;
2. inserts the globally unique `X-GitHub-Delivery`;
3. stores the original payload and its SHA-256 hash;
4. inserts an outbox row in the same database transaction; and
5. returns `202 Accepted`.

A repeated delivery ID returns `200 OK` without creating another job. The database
unique constraint is the deduplication guarantee.

Celery Beat dispatches pending outbox rows to Redis. The worker then fetches the
current pull request, reviews, and complete file list from GitHub before synchronizing
the database and running the configured analysis version. Queue publication failures
remain recoverable in the outbox, and processing failures remain visible in
`webhook_deliveries`.

Celery tasks use late acknowledgements, exponential retry backoff with jitter, hard
and soft time limits, and a prefetch multiplier of one. Processing is idempotent:
pull requests are upserted, file rows are made to match GitHub's current list, metrics
and scores are recalculated, and PostgreSQL advisory locks prevent concurrent work on
the same delivery. PostgreSQL—not Celery's result backend—is authoritative for status.

## Complete GitHub snapshots

PR file synchronization requests 100 files per page and follows GitHub's `rel="next"`
Link header until the complete response has been fetched. The database is not modified
until all remote pages, the current PR, and current reviews have been retrieved.

Every current file stores its GitHub status, SHA, rename source, counts, patch
availability, API URLs, and first/last-seen timestamps. Files absent from a later
snapshot are retained for audit with `is_current=false`; API reads and analysis only
use current rows.

GitHub limits the pull-request files response to 3,000 files. Reaching that boundary
marks the delivery and PR `GITHUB_FILE_LIMIT`, records a non-authoritative analysis
run, preserves the last complete file snapshot, and disables authoritative metrics
and scoring. The dashboard displays these synchronization limitations.

Each successful snapshot creates or reuses a deterministic `analysis_runs` record.
A run is authoritative only when its inputs are complete, every policy-required
analyzer is available, and its confidence meets the repository policy. The PR also
stores GitHub's `updated_at`, the current head SHA, the last processed delivery, and
the last completely synchronized head SHA. Older snapshots are rejected before they
can overwrite newer lifecycle or file state.

## Deterministic scoring

Scoring is independent of the dashboard and runs from the synchronized file snapshot
plus GitHub checks for the current head SHA. The stable run key covers the PR, head
SHA, analyzer suite, policy hash, and complete input hash. Reprocessing identical
inputs reuses the prior result; a head, analyzer version, or policy change creates a
new score without overwriting history.

The initial analyzer suite covers diff size/concentration, language-aware test-file
changes, documentation, dependency changes, lint/type-check results, complexity,
duplication, function size, security findings, and aggregate CI status. An external
tool that is missing, still running, unsupported, or failed is recorded as
`unavailable`, `inconclusive`, or `error`. It is never converted into a zero.

Available analyzer results are combined within their categories, then category scores
use the versioned repository weights. Unavailable categories are excluded from the
weighted mean and reduce confidence. The balanced default is:

- correctness 30%
- tests 20%
- maintainability 15%
- security 15%
- documentation 5%
- architecture 10%
- change risk 5%

`score_versions`, `scores`, `analyzer_results`, and `score_evidence` retain the policy,
versions, findings, evidence, errors, confidence, and deterministic hashes needed to
reproduce and explain a result. PostgreSQL triggers and SQLAlchemy guards make
completed results insert-only. Updating a repository policy creates or selects an
immutable policy version; the next scoring run uses it.

## Review and approval domain

A deterministic score is evidence; it never directly changes a PR to `eligible` and
there is no score-to-payment API. Eligibility follows this sequence:

1. The latest score is evaluated against an immutable `repository_policies` version.
2. Hard failures—such as an unmerged PR, stale/non-authoritative score, incomplete
   input, minimum-score failure, or prior payout—produce an explainable ineligible
   decision.
3. Passing decisions enter `pending_review` when human review is required.
4. An authorized reviewer submits a completed `reviews` record and optional immutable
   `review_findings`.
5. A separate authorized user submits an immutable `approvals` record.
6. Only the required number of approvals changes the decision and PR to `eligible`.

The default policy requires a merged PR, an authoritative score of at least 70, one
human review, one owner/admin approval, separation of reviewer and approver, and
prevents PR authors from reviewing or approving themselves. Policy versions are
repository-specific and configurable without rewriting prior decisions.

Every `eligibility_decisions` row records the exact score, score version, repository
policy version/hash, evaluation checks, failure reasons, reviewer findings, approver
identity, and final decision hash. A new score or repository policy supersedes an
active decision and resets non-paid PRs to `not_evaluated`; the old decision,
reviews, findings, and approvals remain available for audit.

Manual PR creation cannot supply `eligibility_state`. The dashboard no longer exposes
the previous score-derived mock disbursement flow and instead shows review, approval,
score-version, and policy-version provenance.

## Bounties, claims, and payouts

An issue and immutable repository bounty-policy version must exist before a bounty can
be created. Every bounty snapshots both its bounty policy and eligibility policy, then
moves independently through funding and assignment. A claim is accepted only when the
bounty is funded and assigned, the linked pull request is merged, the current
eligibility decision was produced by the bounty's policy, an immutable approval
exists, and the claimant has an active verified wallet.

Approved claims copy the bounty amount, currency, wallet chain, and wallet address
into an immutable financial snapshot. Payouts then copy that snapshot and the exact
approval ID. Database constraints guarantee one payout per approved claim and unique
idempotency keys; application retries return the existing payout or attempt instead
of creating another transfer.

The payout lifecycle is:

`created` → `authorized` → `submitting` → `submitted` → `confirmed`

Submission failure moves a payout to `failed`, from which a new idempotent attempt can
be made. Submission and confirmation are intentionally separate: provider acceptance
does not mark a claim or bounty paid. Only confirmation changes the claim to `paid`,
the bounty to `paid`, its funding to `exhausted`, and PR eligibility to `paid`.
Cancellation is represented but is not yet exposed as an API operation.

These endpoints record and secure the payout state machine; they do not broadcast a
blockchain transaction or call a payment provider. A provider adapter should use the
attempt idempotency key, then call the submitted and confirmation operations from
authenticated provider-processing code. PostgreSQL is authoritative for all states.
The existing tenant-scoped `audit_logs` table is the Phase 5 audit-event ledger.

## Advisory AI review

AI review runs only after the current head has a complete deterministic analysis. It
does not participate in eligibility-policy evaluation, approval, claim creation, or
payout transitions. Every AI record has a database-enforced `advisory_only=true`
constraint.

The server builds and hashes the exact provider input from:

- the PR title, description, and input commit SHA;
- linked issue and bounty requirements;
- a bounded structured file/diff summary and deterministically selected patch chunks;
- static analyzer findings and CI results; and
- the immutable repository review-policy version and rules.

Provider output must validate against this strict shape:

```json
{
  "summary": "string",
  "positive_findings": ["string"],
  "risk_findings": ["string"],
  "requirement_coverage": ["string"],
  "recommended_actions": ["string"],
  "confidence": 0.0
}
```

Each immutable review records the provider, model, provider kind, prompt version,
input commit and hash, input snapshot, privacy decision, structured output, provider
request ID, prompt/completion/total token counts, cost and currency, moderation
result, requester, and timestamps. Output without a passed moderation/safety result
is retained for audit but the review is marked `failed`, not `complete`.

Repository-specific AI policies are immutable and versioned. By default, public
repositories may use external providers and bounded patch chunks. Private
repositories block external providers before any repository data is assembled or
sent; the blocked attempt is retained with an empty input snapshot and an auditable
privacy reason. An administrator must create a new policy version to opt a private
repository into external processing. Local providers remain available without an
external transfer.

The API deliberately separates request construction from provider completion. A
provider adapter can implement `AIReviewProvider`, consume the stored canonical
input, use the review key for provider idempotency, enforce its own credentials and
transport, and then persist the validated response. No external AI SDK or secret is
embedded in the domain layer.

## Operational dashboard and notifications

The operations dashboard reads durable PostgreSQL telemetry rather than Celery's
result backend. It reports current queue and outbox depth, queued/running/failed
deliveries, retry totals, worker heartbeat freshness, GitHub API rate-limit
snapshots, incomplete PR snapshots, recent processing durations, and persisted
failure logs. Celery Beat records a worker heartbeat every 30 seconds and dispatches
due notifications every 10 seconds.

Product analytics are calculated only from business records the caller can access:
open bounties, pending human reviews, eligible claims, payout state and value, merge
time, contributor activity, repository health, and organization totals. Empty data
is returned as an explicit empty state; the UI does not synthesize chart series.

Notification production follows:

`domain event` → `organization policy` → `channel delivery`

Domain events are immutable and idempotent. The first adapters are in-app and SMTP
email. Each recipient/channel combination has its own delivery status, attempt
count, last error, exponential retry time, and stable idempotency key. Supported
events cover analysis completion/failure, review requests/changes, bounty
eligibility, claim approval, and payout submission/confirmation/failure. Configure
the SMTP variables in `.env`; when email is intentionally unconfigured, failed email
attempts remain visible and retry up to `NOTIFICATION_MAX_RETRIES` while in-app
delivery continues independently.

## Real payout integration

The payout integration is provider-neutral. `PayoutProvider` defines destination
validation, idempotent submission, status polling, and explorer-link generation.
The built-in `ledger` provider exercises the complete off-chain approval and ledger
flow without broadcasting value. `base_sepolia_custody` calls a separately operated
HTTPS custody service; that service owns transaction construction, simulation,
multisig signing, and broadcast, so this application never stores a treasury private
key.

Every treasury is organization-scoped and created paused. It records its environment,
chain, currency/contract, dedicated operating address, opening and observed balances,
per-payout and daily limits, approval thresholds, required confirmation level,
simulation requirement, and non-secret provider configuration. Provider configuration
containing keys, tokens, passwords, or secrets is rejected.

Integrated payouts snapshot the treasury, provider, and confirmation policy when
created. The legacy manual attempt/submission/confirmation endpoints reject those
payouts, preventing operators from bypassing provider reconciliation. Authorization
requires:

1. the immutable claim and eligibility approval still match;
2. the claimant is not a treasury approver;
3. global and treasury emergency pauses are clear;
4. provider destination validation succeeds;
5. distinct approvals meet the normal or high-value threshold;
6. the payout and daily limits pass; and
7. the immutable ledger has enough available balance.

Authorization creates a reservation entry (`available -amount`, `reserved +amount`).
Provider confirmation creates exactly one settlement (`reserved -amount`,
`settled +amount`) before the claim, bounty, and PR move to paid. Ledger entries,
treasury approvals, balance observations, and provider reconciliations are insert-only
in both SQLAlchemy and PostgreSQL.

Celery polls submitting/submitted payouts every 30 seconds and active treasury
balances every 60 seconds. Status observations retain provider responses,
confirmations, transaction hashes, errors, and explorer links. An ambiguous submit
timeout leaves the same attempt in `submitting`; retrying with the same idempotency
key calls the provider again without creating another attempt.

The first blockchain configuration is testnet-only Base Sepolia: chain ID `84532`
and the Base Sepolia explorer come from the
[Base network documentation](https://docs.base.org/base-chain/quickstart/connecting-to-base);
test USDC `0x036CbD53842c5426634e7929541eC2318f3dCF7e` comes from
[Circle's contract registry](https://developers.circle.com/stablecoins/usdc-contract-addresses).
Mainnet remains blocked unless `PAYOUTS_ALLOW_MAINNET=true`, and all
submission remains blocked until `PAYOUTS_ENABLED=true` and
`PAYOUTS_EMERGENCY_PAUSED=false`. Re-verify chain, contract, RPC, Safe/custody,
finality, fee, and operating-limit assumptions before changing either flag.

## Independent state models

- Pull request lifecycle: `draft`, `open`, `closed`, `merged`
- Review: `not_requested`, `under_review`, `changes_requested`, `approved`
- Ingestion: `received`, `queued`, `processing`, `complete`, `incomplete`, `failed`
- Payout eligibility: `not_evaluated`, `ineligible`, `eligible`, `claimed`, `paid`

Merging does not change payout eligibility. Eligibility remains `not_evaluated` until
a separate policy evaluation validates the bounty, issue linkage, approvals, checks,
score threshold, prior payouts, and organization policy.

## Example Test Payload

Use this authenticated payload for `POST /prs`:

```json
{
  "github_pr_id": 101,
  "repo_id": 1,
  "title": "Add webhook listener scaffold",
  "additions": 120,
  "deletions": 12,
  "changed_files": 5
}
```

`author_id` is optional and defaults to the authenticated user. `repo_id` is required
and the caller must have at least `MAINTAINER` access.

## GitHub Webhook Testing

1. Run server:

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

2. Run ngrok in a separate terminal:

   ```bash
   ngrok http 8000
   ```

3. Set your GitHub webhook URL to:

   ```text
   https://<ngrok-url>/webhook/github
   ```

4. In GitHub webhook settings, use:
   - Content type: `application/json`
   - Secret: value from `.env` (`GITHUB_WEBHOOK_SECRET`)
   - Events: `Pull requests`, `Pull request reviews`, `Check runs`, and `Check suites`

   Supported pull request actions are `opened`, `reopened`, `synchronize`, `closed`,
   `edited`, `ready_for_review`, `converted_to_draft`, `review_requested`, and
   `review_request_removed`. Supported review actions are `submitted` and `dismissed`.
   Relevant check-run/check-suite updates resynchronize the linked PR's current head.
   GitHub App authorization revocations are delivered automatically and are also
   handled. Grant Checks read access so lint, security, complexity, and CI conclusions
   can contribute evidence; missing permission is recorded as unavailable.

5. Create or update a PR, then verify the delivery reaches `complete` in
   `webhook_deliveries`.

GitHub recommends fast 2xx acknowledgement, asynchronous work, and deduplication by
delivery ID. See the
[webhook best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)
and [delivery header documentation](https://docs.github.com/en/webhooks/webhook-events-and-payloads#delivery-headers).
For file synchronization limits and pagination behavior, see the
[pull-request files endpoint](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files)
and [REST pagination guide](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api).
GitHub check-run evidence uses the
[check runs for a Git reference endpoint](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference).
For identity and access behavior, see GitHub's
[user access token flow](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app),
[installation repository endpoints](https://docs.github.com/en/rest/apps/installations),
and [organization membership endpoints](https://docs.github.com/en/rest/orgs/members).
