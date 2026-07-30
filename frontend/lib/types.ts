export interface PullRequestAuthor {
  username: string;
  avatar_url: string | null;
}

export interface PullRequestRepository {
  organization_id: number;
  name: string;
  owner: string;
}

export interface PullRequest {
  id: number;
  github_pr_id: number;
  github_pr_number: number | null;
  title: string;
  author_id: number;
  repo_id: number;
  state: "draft" | "open" | "closed" | "merged";
  review_state: "not_requested" | "under_review" | "changes_requested" | "approved";
  eligibility_state: "not_evaluated" | "ineligible" | "eligible" | "claimed" | "paid";
  additions: number;
  deletions: number;
  changed_files: number;
  github_updated_at: string | null;
  github_created_at: string | null;
  merged_at: string | null;
  head_sha: string | null;
  last_processed_delivery_id: string | null;
  last_synchronized_head_sha: string | null;
  file_sync_complete: boolean;
  incomplete_reason: string | null;
  synchronized_at: string | null;
  created_at: string;
  author: PullRequestAuthor;
  repository: PullRequestRepository;
}

export interface PRMetrics {
  id: number;
  pr_id: number;
  total_files: number;
  total_additions: number;
  total_deletions: number;
  has_tests: boolean;
  has_docs: boolean;
  language_breakdown: Record<string, number>;
  analysis_version: string;
  created_at: string;
}

export interface PRFile {
  id: number;
  pr_id: number;
  filename: string;
  previous_filename: string | null;
  github_status: string;
  sha: string | null;
  additions: number;
  deletions: number;
  changes: number;
  patch: string | null;
  patch_available: boolean;
  patch_status: "available" | "binary" | "too_large" | "not_returned";
  contents_url: string | null;
  blob_url: string | null;
  raw_url: string | null;
  first_seen_at: string;
  last_seen_at: string;
  is_current: boolean;
  removed_at: string | null;
  created_at: string;
}

export interface PRScore {
  id: number;
  pr_id: number;
  analysis_run_id: number | null;
  score_version_id: number;
  head_sha: string | null;
  analyzer_suite_version: string;
  scoring_policy_version: string;
  category_scores: Record<string, number>;
  category_confidence: Record<string, number>;
  unavailable_categories: string[];
  final_score: number;
  confidence: number;
  input_complete: boolean;
  is_authoritative: boolean;
  explanation: {
    formula: string;
    policy_weights: Record<string, number>;
    analyzer_status: Record<string, string>;
    [key: string]: unknown;
  };
  deterministic_hash: string;
  evidence: Array<{
    id: number;
    analyzer_result_id: number;
    category: string;
    evidence_type: string;
    description: string;
    location: string | null;
    evidence_data: Record<string, unknown>;
    evidence_hash: string;
  }>;
  created_at: string;
}

export interface Organization {
  id: number;
  github_org_id: number | null;
  login: string;
  display_name: string | null;
  avatar_url: string | null;
  role: "owner" | "admin" | "maintainer" | "reviewer" | "contributor" | "viewer";
  github_verified: boolean;
}

export interface AuthenticatedUser {
  id: number;
  github_id: number;
  username: string;
  avatar_url: string | null;
  email: string | null;
  display_name: string | null;
}

export interface PageEnvelope<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  aggregates: Record<string, unknown>;
}

export interface DeliverySummary {
  id: number;
  delivery_id: string;
  event_type: string;
  action: string | null;
  status: "received" | "queued" | "processing" | "complete" | "incomplete" | "failed";
  attempt_count: number;
  received_at: string;
  started_at: string | null;
  completed_at: string | null;
  next_retry_at: string | null;
  last_error: string | null;
}

export interface OperationsDashboard {
  generated_at: string;
  queue_depth: number;
  awaiting_publish: number;
  queued_jobs: number;
  running_jobs: number;
  failed_jobs: number;
  total_retry_attempts: number;
  incomplete_ingestions: number;
  average_processing_seconds: number | null;
  workers: Array<{
    worker_id: string;
    queues: string[];
    status: string;
    active_tasks: number;
    last_seen_at: string;
    is_stale: boolean;
  }>;
  github_rate_limits: Array<{
    installation_id: number;
    resource: string;
    limit: number;
    remaining: number;
    used: number;
    reset_at: string;
    observed_at: string;
  }>;
  recent_deliveries: DeliverySummary[];
  incomplete_pull_requests: Array<{
    id: number;
    title: string;
    repository: string;
    incomplete_reason: string | null;
    synchronized_at: string | null;
  }>;
  failure_logs: DeliverySummary[];
}

export interface ProductAnalytics {
  generated_at: string;
  organization: {
    id: number;
    login: string;
    repository_count: number;
    contributor_count: number;
    pull_request_count: number;
  };
  open_bounties: number;
  open_bounty_amounts: Record<string, string>;
  pending_reviews: number;
  eligible_claims: number;
  pending_payouts: number;
  confirmed_payouts: number;
  confirmed_payout_amounts: Record<string, string>;
  average_merge_seconds: number | null;
  contributors: Array<{
    user_id: number;
    username: string;
    avatar_url: string | null;
    pull_requests: number;
    merged_pull_requests: number;
    approved_claims: number;
    confirmed_payouts: number;
    last_activity_at: string | null;
  }>;
  repositories: Array<{
    repository_id: number;
    full_name: string;
    pull_requests: number;
    incomplete_ingestions: number;
    failed_deliveries: number;
    open_bounties: number;
    pending_reviews: number;
    last_synchronized_at: string | null;
    health: "healthy" | "attention" | "critical";
  }>;
}

export interface Notification {
  id: number;
  event_id: number;
  channel: "in_app" | "email";
  status: "pending" | "delivered" | "failed";
  subject: string;
  body: string;
  payload: Record<string, unknown>;
  attempt_count: number;
  last_error: string | null;
  delivered_at: string | null;
  read_at: string | null;
  created_at: string;
}

export interface ReviewFinding {
  id: number;
  review_id: number;
  severity: "info" | "low" | "medium" | "high" | "critical";
  category: string;
  code: string;
  message: string;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface HumanReview {
  id: number;
  eligibility_decision_id: number;
  reviewer_user_id: number;
  status: "pending" | "in_progress" | "completed" | "cancelled";
  recommendation: "approve" | "request_changes" | "reject" | null;
  summary: string | null;
  started_at: string;
  completed_at: string | null;
  findings: ReviewFinding[];
}

export interface EligibilityApproval {
  id: number;
  eligibility_decision_id: number;
  approver_user_id: number;
  outcome: "approved" | "rejected";
  reason: string | null;
  score_id: number;
  score_version_id: number;
  repository_policy_id: number;
  created_at: string;
}

export interface EligibilityDecision {
  id: number;
  pr_id: number;
  score_id: number;
  score_version_id: number;
  repository_policy_id: number;
  status:
    | "pending_review"
    | "changes_requested"
    | "pending_approval"
    | "eligible"
    | "ineligible"
    | "superseded";
  is_current: boolean;
  evaluation_result: {
    checks: Record<string, boolean>;
    score: {
      id: number;
      version_id: number;
      head_sha: string | null;
      final_score: number;
      confidence: number;
      deterministic_hash: string;
    };
    policy: {
      id: number;
      version: string;
      policy_hash: string;
      rules: Record<string, unknown>;
    };
  };
  failure_reasons: string[];
  requires_human_review: boolean;
  required_approvals: number;
  evaluation_hash: string;
  evaluated_by_user_id: number | null;
  final_approved_by_user_id: number | null;
  created_at: string;
  finalized_at: string | null;
  reviews: HumanReview[];
  approvals: EligibilityApproval[];
}

export interface RepositoryAccess {
  id: number;
  github_repo_id: number;
  organization_id: number;
  name: string;
  owner: string;
  full_name: string;
  is_private: boolean;
  is_archived: boolean;
  role: Organization["role"];
}

export interface OrganizationMember {
  membership_id: number;
  user_id: number;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  role: Organization["role"];
  github_verified: boolean;
  is_active: boolean;
  created_at: string;
}

export interface PolicySummary {
  id: number;
  version: string;
  name: string;
  description?: string | null;
  policy_hash: string;
  rules?: Record<string, unknown>;
  weights?: Record<string, number>;
}

export interface AIReview {
  id: number;
  pr_id: number;
  analysis_run_id: number;
  repository_policy_id: number;
  ai_review_policy_id: number;
  requested_by_user_id: number | null;
  provider: string;
  model: string;
  provider_kind: "local" | "external";
  prompt_version: string;
  input_commit_sha: string;
  privacy_decision: Record<string, unknown>;
  status: "pending" | "complete" | "failed" | "blocked";
  output: {
    summary?: string;
    positive_findings?: string[];
    risk_findings?: string[];
    requirement_coverage?: string[];
    recommended_actions?: string[];
    confidence?: number;
  } | null;
  provider_request_id: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_amount: string | number | null;
  cost_currency: string | null;
  moderation_result: Record<string, unknown> | null;
  failure_reason: string | null;
  advisory_only: true;
  review_key: string;
  created_at: string;
  completed_at: string | null;
}

export interface Bounty {
  id: number;
  organization_id: number;
  repository_id: number;
  issue_id: number;
  bounty_policy_id: number;
  eligibility_policy_id: number;
  amount: string | number;
  currency: string;
  status:
    | "draft"
    | "open"
    | "assigned"
    | "closed"
    | "paid"
    | "cancelled"
    | "expired";
  funding_status:
    | "unfunded"
    | "pending"
    | "funded"
    | "exhausted"
    | "refunded";
  expires_at: string | null;
  created_by_user_id: number;
  created_at: string;
}

export interface Claim {
  id: number;
  bounty_id: number;
  assignment_id: number;
  pull_request_id: number;
  eligibility_decision_id: number;
  approval_id: number;
  claimant_user_id: number;
  wallet_id: number;
  amount: string | number;
  currency: string;
  destination_chain: string;
  destination_address: string;
  status: "approved" | "rejected" | "cancelled" | "paid";
  created_at: string;
}

export interface Payout {
  id: number;
  claim_id: number;
  approval_id: number;
  amount: string | number;
  currency: string;
  destination_chain: string;
  destination_address: string;
  idempotency_key: string;
  treasury_account_id: number | null;
  provider_key: string | null;
  provider_reference: string | null;
  state:
    | "created"
    | "authorized"
    | "submitting"
    | "submission_unknown"
    | "submitted"
    | "confirmed"
    | "failed"
    | "cancelled";
  transaction_hash: string | null;
  explorer_url: string | null;
  required_confirmations: number;
  observed_confirmations: number;
  next_reconciliation_at: string | null;
  confirmed_at: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface TreasuryAccount {
  id: number;
  organization_id: number;
  provider_key: string;
  environment: "testnet" | "mainnet";
  chain: string;
  currency: string;
  treasury_address: string;
  asset_contract_address: string | null;
  custody_model: string;
  opening_balance: string | number;
  observed_balance: string | number | null;
  available_balance: string | number;
  reserved_balance: string | number;
  settled_amount: string | number;
  per_payout_limit: string | number;
  daily_spending_limit: string | number;
  manual_approval_threshold: string | number | null;
  required_confirmations: number;
  simulation_required: boolean;
  status: "active" | "paused";
  paused_reason: string | null;
  last_balance_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TreasuryLedgerEntry {
  id: number;
  treasury_account_id: number;
  payout_id: number | null;
  entry_type: string;
  currency: string;
  available_delta: string | number;
  reserved_delta: string | number;
  settled_delta: string | number;
  idempotency_key: string;
  entry_metadata: Record<string, unknown>;
  created_at: string;
}

export interface AuditLog {
  id: number;
  action: string;
  resource_type: string;
  actor_user_id: number | null;
  repository_id: number | null;
  resource_id: string | null;
  event_metadata: Record<string, unknown>;
  created_at: string;
}

