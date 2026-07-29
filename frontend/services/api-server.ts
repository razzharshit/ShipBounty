import "server-only";

import { cookies } from "next/headers";
import type {
  AIReview,
  AuditLog,
  Bounty,
  Claim,
  EligibilityDecision,
  Notification,
  OperationsDashboard,
  Organization,
  OrganizationMember,
  PageEnvelope,
  PRFile,
  PRMetrics,
  PullRequest,
  PRScore,
  ProductAnalytics,
  Payout,
  RepositoryAccess,
  PolicySummary,
  TreasuryAccount,
  TreasuryLedgerEntry,
} from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SESSION_COOKIE_NAME =
  process.env.AUTH_SESSION_COOKIE_NAME ?? "gbd_session";

export class ServerApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export type AnalysisResult<T> =
  | { status: "ready"; data: T }
  | { status: "missing"; message: string }
  | { status: "incomplete"; reason: string };

async function fetchAuthenticatedAPI<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const session = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  const headers = new Headers(init?.headers);
  if (session) {
    headers.set(
      "Cookie",
      `${SESSION_COOKIE_NAME}=${encodeURIComponent(session)}`,
    );
  }
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers,
  });
  if (!response.ok) {
    let detail = `API error: ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The status remains authoritative when an upstream body is not JSON.
    }
    throw new ServerApiError(detail, response.status);
  }
  return response.json();
}

export function isAuthenticationError(error: unknown): boolean {
  return error instanceof ServerApiError && error.status === 401;
}

export function getActionErrorMessage(error: unknown): string {
  if (!(error instanceof ServerApiError)) {
    return "The action could not be completed. Please try again.";
  }
  const prefix =
    error.status === 403
      ? "You do not have permission for this action."
      : error.status === 409
        ? "The record changed before this action completed."
        : error.status === 422
          ? "The submitted information was not accepted."
          : error.status === 429
            ? "The request limit has been reached."
            : error.status === 503
              ? "The external provider is temporarily unavailable."
              : "The action could not be completed.";
  return `${prefix} ${error.message}`.trim();
}

export async function getPullRequests(): Promise<PullRequest[]> {
  return fetchAuthenticatedAPI<PullRequest[]>("/prs");
}

export async function getOrganizations(): Promise<Organization[]> {
  return fetchAuthenticatedAPI<Organization[]>("/organizations");
}

export async function getOperationsDashboard(
  organizationId: number,
): Promise<OperationsDashboard> {
  return fetchAuthenticatedAPI<OperationsDashboard>(
    `/organizations/${organizationId}/operations-dashboard`,
  );
}

export async function getProductAnalytics(
  organizationId: number,
): Promise<ProductAnalytics> {
  return fetchAuthenticatedAPI<ProductAnalytics>(
    `/organizations/${organizationId}/product-analytics`,
  );
}

export async function getNotifications(
  organizationId?: number,
): Promise<Notification[]> {
  const query =
    organizationId === undefined ? "" : `?organization_id=${organizationId}`;
  return fetchAuthenticatedAPI<Notification[]>(`/notifications${query}`);
}

export async function getRepositories(
  organizationId: number,
): Promise<RepositoryAccess[]> {
  return fetchAuthenticatedAPI<RepositoryAccess[]>(
    `/organizations/${organizationId}/repositories`,
  );
}

export async function getOrganizationMembers(
  organizationId: number,
): Promise<OrganizationMember[]> {
  return fetchAuthenticatedAPI<OrganizationMember[]>(
    `/organizations/${organizationId}/members`,
  );
}

export async function getRepositoryPolicies(repositoryId: number): Promise<{
  eligibility: PolicySummary;
  scoring: PolicySummary;
  bounty: PolicySummary;
  ai: PolicySummary;
}> {
  const [eligibility, scoring, bounty, ai] = await Promise.all([
    fetchAuthenticatedAPI<PolicySummary>(
      `/repositories/${repositoryId}/eligibility-policy`,
    ),
    fetchAuthenticatedAPI<PolicySummary>(
      `/repositories/${repositoryId}/scoring-policy`,
    ),
    fetchAuthenticatedAPI<PolicySummary>(
      `/repositories/${repositoryId}/bounty-policy`,
    ),
    fetchAuthenticatedAPI<PolicySummary>(
      `/repositories/${repositoryId}/ai-review-policy`,
    ),
  ]);
  return { eligibility, scoring, bounty, ai };
}

export async function getReviewQueue(
  organizationId: number,
  status?: EligibilityDecision["status"],
  offset = 0,
  limit = 50,
): Promise<PageEnvelope<EligibilityDecision>> {
  const parameters = new URLSearchParams({
    offset: String(Math.max(0, offset)),
    limit: String(limit),
  });
  if (status) parameters.set("status", status);
  return fetchAuthenticatedAPI<PageEnvelope<EligibilityDecision>>(
    `/organizations/${organizationId}/review-queue?${parameters}`,
  );
}

export async function getOrganizationAIReviews(
  organizationId: number,
  offset = 0,
  limit = 50,
): Promise<PageEnvelope<AIReview>> {
  return fetchAuthenticatedAPI<PageEnvelope<AIReview>>(
    `/organizations/${organizationId}/ai-reviews?offset=${Math.max(0, offset)}&limit=${limit}`,
  );
}

export async function getBounties(
  organizationId: number,
  offset = 0,
  limit = 50,
): Promise<PageEnvelope<Bounty>> {
  return fetchAuthenticatedAPI<PageEnvelope<Bounty>>(
    `/organizations/${organizationId}/bounties?offset=${Math.max(0, offset)}&limit=${limit}`,
  );
}

export async function getClaims(
  organizationId: number,
  offset = 0,
  limit = 50,
): Promise<PageEnvelope<Claim>> {
  return fetchAuthenticatedAPI<PageEnvelope<Claim>>(
    `/organizations/${organizationId}/claims?offset=${Math.max(0, offset)}&limit=${limit}`,
  );
}

export async function getPayouts(
  organizationId: number,
  offset = 0,
  limit = 50,
): Promise<PageEnvelope<Payout>> {
  return fetchAuthenticatedAPI<PageEnvelope<Payout>>(
    `/organizations/${organizationId}/payouts?offset=${Math.max(0, offset)}&limit=${limit}`,
  );
}

export async function getTreasuries(
  organizationId: number,
): Promise<TreasuryAccount[]> {
  return fetchAuthenticatedAPI<TreasuryAccount[]>(
    `/organizations/${organizationId}/treasuries`,
  );
}

export async function getTreasuryLedger(
  treasuryId: number,
): Promise<TreasuryLedgerEntry[]> {
  return fetchAuthenticatedAPI<TreasuryLedgerEntry[]>(
    `/treasuries/${treasuryId}/ledger`,
  );
}

export async function getAuditLogs(
  organizationId: number,
): Promise<AuditLog[]> {
  return fetchAuthenticatedAPI<AuditLog[]>(
    `/organizations/${organizationId}/audit-logs`,
  );
}

export async function getPRMetrics(
  prId: number,
): Promise<AnalysisResult<PRMetrics>> {
  try {
    const data = await fetchAuthenticatedAPI<PRMetrics>(`/prs/${prId}/metrics`);
    return { status: "ready", data };
  } catch (error) {
    if (error instanceof ServerApiError && error.status === 404) {
      return { status: "missing", message: error.message };
    }
    if (error instanceof ServerApiError && error.status === 409) {
      return { status: "incomplete", reason: error.message };
    }
    throw error;
  }
}

export async function getPRFiles(prId: number): Promise<PRFile[]> {
  try {
    return await fetchAuthenticatedAPI<PRFile[]>(`/prs/${prId}/files`);
  } catch (error) {
    if (error instanceof ServerApiError && error.status === 404) return [];
    throw error;
  }
}

export async function getPRScore(prId: number): Promise<AnalysisResult<PRScore>> {
  try {
    const data = await fetchAuthenticatedAPI<PRScore>(`/scores/${prId}`);
    return { status: "ready", data };
  } catch (error) {
    if (error instanceof ServerApiError && error.status === 404) {
      return { status: "missing", message: error.message };
    }
    if (error instanceof ServerApiError && error.status === 409) {
      return { status: "incomplete", reason: error.message };
    }
    throw error;
  }
}

export async function resyncPullRequest(prId: number): Promise<void> {
  await fetchAuthenticatedAPI(`/prs/${prId}/resync`, { method: "POST" });
}

export async function getEligibilityDecisions(
  prId: number,
): Promise<EligibilityDecision[]> {
  return fetchAuthenticatedAPI<EligibilityDecision[]>(
    `/prs/${prId}/eligibility-decisions`,
  );
}

export async function getPRAIReviews(prId: number): Promise<AIReview[]> {
  return fetchAuthenticatedAPI<AIReview[]>(`/prs/${prId}/ai-reviews`);
}

export async function requestAIReview(
  prId: number,
  force = false,
): Promise<AIReview> {
  const query = force ? "?force=true" : "";
  return fetchAuthenticatedAPI<AIReview>(`/prs/${prId}/ai-reviews${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export async function retryAIReview(reviewId: number): Promise<AIReview> {
  return fetchAuthenticatedAPI<AIReview>(`/ai-reviews/${reviewId}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}

export async function submitHumanReview(
  decisionId: number,
  payload: {
    recommendation: "approve" | "request_changes" | "reject";
    summary: string;
    findings: Array<{
      severity: "info" | "low" | "medium" | "high" | "critical";
      category: string;
      code: string;
      message: string;
      evidence: Record<string, unknown>;
    }>;
  },
): Promise<void> {
  await fetchAuthenticatedAPI(
    `/eligibility-decisions/${decisionId}/reviews`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function submitEligibilityApproval(
  decisionId: number,
  payload: {
    outcome: "approved" | "rejected";
    reason: string | null;
  },
): Promise<void> {
  await fetchAuthenticatedAPI(
    `/eligibility-decisions/${decisionId}/approvals`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}
