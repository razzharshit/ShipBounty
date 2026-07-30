import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { ArrowRight, Filter, ShieldCheck } from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";
import {
  EmptyTable,
  PageHeader,
  StatusPill,
} from "@/components/workspace/page-header";
import { PaginationControls } from "@/components/workspace/pagination-controls";
import {
  getOrganizations,
  getPullRequests,
  getReviewQueue,
  isAuthenticationError,
} from "@/services/api-server";
import { formatDate } from "@/services/api";

export default async function ReviewQueuePage({
  params,
  searchParams,
}: {
  params: Promise<{ organizationSlug: string }>;
  searchParams: Promise<{ status?: string; offset?: string }>;
}) {
  const { organizationSlug } = await params;
  const resolvedSearchParams = await searchParams;
  const requestedStatus = resolvedSearchParams.status;
  const offset = Math.max(0, Number(resolvedSearchParams.offset) || 0);
  const allowedStatuses = new Set([
    "pending_review",
    "changes_requested",
    "pending_approval",
    "eligible",
    "ineligible",
    "superseded",
  ]);
  const status = allowedStatuses.has(requestedStatus ?? "")
    ? (requestedStatus as
        | "pending_review"
        | "changes_requested"
        | "pending_approval"
        | "eligible"
        | "ineligible"
        | "superseded")
    : undefined;
  let organizations;
  try {
    organizations = await getOrganizations();
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    throw error;
  }
  const organization = organizations.find(
    (item) => item.login === decodeURIComponent(organizationSlug),
  );
  if (!organization) notFound();
  const [decisionPage, pullRequests] = await Promise.all([
    getReviewQueue(organization.id, status, offset),
    getPullRequests(),
  ]);
  const decisions = decisionPage.items;
  const statusCounts =
    (decisionPage.aggregates.status_counts as
      | Record<string, number>
      | undefined) ?? {};
  const pullRequestsById = new Map(pullRequests.map((item) => [item.id, item]));
  const actionRequired =
    (statusCounts.pending_review ?? 0) +
    (statusCounts.changes_requested ?? 0) +
    (statusCounts.pending_approval ?? 0);

  return (
    <AppShell>
      <div className="space-y-7">
        <PageHeader
          eyebrow="Human control plane"
          title="Review queue"
          description="Role-aware review and approval work, ordered by age and backed by the exact score and policy snapshot."
          icon={ShieldCheck}
          actions={
            <form className="flex items-center gap-2">
              <label className="sr-only" htmlFor="review-status">
                Filter review queue by status
              </label>
              <select
                id="review-status"
                name="status"
                defaultValue={status ?? ""}
                className="h-11 rounded-xl border border-border bg-card px-3 text-sm font-semibold shadow-sm"
              >
                <option value="">All statuses</option>
                <option value="pending_review">Pending review</option>
                <option value="changes_requested">Changes requested</option>
                <option value="pending_approval">Pending approval</option>
                <option value="eligible">Eligible</option>
                <option value="ineligible">Ineligible</option>
              </select>
              <button className="inline-flex h-11 items-center gap-2 rounded-xl border border-border bg-card px-4 text-sm font-semibold shadow-sm">
                <Filter className="h-4 w-4" />
                Apply
              </button>
            </form>
          }
        />

        <div className="grid gap-3 sm:grid-cols-3">
          {[
            ["Action required", actionRequired, "Review or approval is waiting"],
            [
              "Waiting for review",
              statusCounts.pending_review ?? 0,
              "Human evidence required",
            ],
            [
              "Eligible",
              statusCounts.eligible ?? 0,
              "Policy gates satisfied",
            ],
          ].map(([label, value, detail]) => (
            <div key={label} className="surface p-5">
              <p className="text-sm font-medium text-muted-foreground">{label}</p>
              <p className="mt-3 text-3xl font-semibold tracking-tight">{value}</p>
              <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
            </div>
          ))}
        </div>

        <section className="surface overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <div>
              <h2 className="font-semibold">Current eligibility decisions</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                New commits supersede stale decisions automatically.
              </p>
            </div>
            <span className="text-sm text-muted-foreground">
              Showing {decisions.length} of {decisionPage.total}
            </span>
          </div>
          {decisions.length === 0 ? (
            <EmptyTable
              title="The review queue is clear"
              description="Merged pull requests appear here after deterministic analysis and policy evaluation."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <caption className="sr-only">
                  Current pull-request eligibility decisions
                </caption>
                <thead>
                  <tr>
                    <th>Pull request</th>
                    <th>Decision</th>
                    <th>Evidence</th>
                    <th>Approvals</th>
                    <th>Age</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {decisions.map((decision) => {
                    const pullRequest = pullRequestsById.get(decision.pr_id);
                    return (
                      <tr key={decision.id}>
                        <td>
                          <p className="max-w-sm truncate font-semibold">
                            {pullRequest?.title ?? `Pull request ${decision.pr_id}`}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {pullRequest
                              ? `${pullRequest.repository.owner}/${pullRequest.repository.name} #${pullRequest.github_pr_number ?? "—"}`
                              : `Internal PR ${decision.pr_id}`}
                          </p>
                        </td>
                        <td>
                          <StatusPill status={decision.status} />
                        </td>
                        <td>
                          <p className="font-mono text-xs">
                            score #{decision.score_id}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            policy #{decision.repository_policy_id}
                          </p>
                        </td>
                        <td>
                          <span className="font-semibold">
                            {decision.approvals.length}
                          </span>
                          <span className="text-muted-foreground">
                            {" "}
                            / {decision.required_approvals}
                          </span>
                        </td>
                        <td className="text-muted-foreground">
                          {formatDate(decision.created_at)}
                        </td>
                        <td>
                          <Link
                            href={`/pull-requests/${decision.pr_id}#human-review`}
                            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary/10 px-3 text-xs font-bold text-primary hover:bg-primary/15"
                          >
                            Review <ArrowRight className="h-3.5 w-3.5" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <PaginationControls
            pathname={`/dashboard/${encodeURIComponent(organizationSlug)}/reviews`}
            total={decisionPage.total}
            limit={decisionPage.limit}
            offset={decisionPage.offset}
            hasMore={decisionPage.has_more}
            query={{ status }}
          />
        </section>
      </div>
    </AppShell>
  );
}
