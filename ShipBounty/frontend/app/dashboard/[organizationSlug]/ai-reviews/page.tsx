import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import {
  Bot,
  CircleDollarSign,
  Cpu,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";
import {
  EmptyTable,
  PageHeader,
  StatusPill,
} from "@/components/workspace/page-header";
import { PaginationControls } from "@/components/workspace/pagination-controls";
import {
  getOrganizationAIReviews,
  getOrganizations,
  getPullRequests,
  isAuthenticationError,
} from "@/services/api-server";
import { formatDate } from "@/services/api";

export default async function AIReviewCenterPage({
  params,
  searchParams,
}: {
  params: Promise<{ organizationSlug: string }>;
  searchParams: Promise<{ offset?: string }>;
}) {
  const { organizationSlug } = await params;
  const offset = Math.max(0, Number((await searchParams).offset) || 0);
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
  const [reviewPage, pullRequests] = await Promise.all([
    getOrganizationAIReviews(organization.id, offset),
    getPullRequests(),
  ]);
  const reviews = reviewPage.items;
  const pullRequestsById = new Map(pullRequests.map((item) => [item.id, item]));
  const statusCounts =
    (reviewPage.aggregates.status_counts as Record<string, number> | undefined) ??
    {};
  const totalTokens = Number(reviewPage.aggregates.total_tokens ?? 0);
  const costByCurrency =
    (reviewPage.aggregates.cost_by_currency as
      | Record<string, string>
      | undefined) ?? {};
  const recordedCost =
    Object.entries(costByCurrency)
      .map(([currency, amount]) => `${Number(amount).toFixed(4)} ${currency}`)
      .join(" · ") || "0";
  const todayRequests = Number(
    reviewPage.aggregates.today_request_count ?? 0,
  );
  const dailyLimit = Number(
    reviewPage.aggregates.configured_daily_limit ?? 0,
  );

  return (
    <AppShell>
      <div className="space-y-7">
        <PageHeader
          eyebrow="Advisory intelligence"
          title="AI review center"
          description="Structured code-review guidance with immutable model provenance, privacy decisions, moderation results, and input commit identity."
          icon={Bot}
          actions={
            <span className="inline-flex h-11 items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 text-sm font-semibold text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-300">
              <ShieldCheck className="h-4 w-4" />
              Advisory only — cannot authorize payout
            </span>
          }
        />

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            {
              label: "Total reviews",
              value: reviewPage.total,
              detail: `${statusCounts.complete ?? 0} completed`,
              icon: Sparkles,
            },
            {
              label: "Pending",
              value: statusCounts.pending ?? 0,
              detail: `${todayRequests} of ${dailyLimit || "unlimited"} requests today`,
              icon: Cpu,
            },
            {
              label: "Token usage",
              value: totalTokens.toLocaleString(),
              detail: "Recorded provider tokens",
              icon: Bot,
            },
            {
              label: "Recorded cost",
              value: recordedCost,
              detail: "No estimated values",
              icon: CircleDollarSign,
            },
          ].map(({ label, value, detail, icon: Icon }) => (
            <div key={label} className="surface p-5">
              <div className="flex items-start justify-between">
                <p className="text-sm font-medium text-muted-foreground">{label}</p>
                <span className="rounded-xl bg-primary/10 p-2 text-primary">
                  <Icon className="h-4 w-4" />
                </span>
              </div>
              <p className="mt-3 text-3xl font-semibold tracking-tight">{value}</p>
              <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
            </div>
          ))}
        </div>

        <section className="surface overflow-hidden">
          <div className="border-b border-border px-5 py-4">
            <h2 className="font-semibold">Review execution history</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Showing {reviews.length} of {reviewPage.total}. Provider output
              never changes eligibility or financial state.
            </p>
          </div>
          {reviews.length === 0 ? (
            <EmptyTable
              title="No AI reviews requested"
              description="Permitted maintainers can request an advisory review from a complete pull-request analysis."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <caption className="sr-only">
                  Advisory AI review execution history
                </caption>
                <thead>
                  <tr>
                    <th>Pull request</th>
                    <th>Provider</th>
                    <th>Status</th>
                    <th>Input</th>
                    <th>Usage</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {reviews.map((review) => {
                    const pullRequest = pullRequestsById.get(review.pr_id);
                    return (
                      <tr key={review.id}>
                        <td>
                          <Link
                            href={`/pull-requests/${review.pr_id}#ai-review`}
                            className="font-semibold hover:text-primary"
                          >
                            {pullRequest?.title ?? `Pull request ${review.pr_id}`}
                          </Link>
                          <p className="mt-1 max-w-xs truncate text-xs text-muted-foreground">
                            {review.output?.summary ??
                              review.failure_reason ??
                              "Waiting for structured provider output"}
                          </p>
                        </td>
                        <td>
                          <p className="font-semibold">{review.provider}</p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {review.model}
                          </p>
                        </td>
                        <td>
                          <StatusPill status={review.status} />
                        </td>
                        <td>
                          <p className="font-mono text-xs">
                            {review.input_commit_sha.slice(0, 10)}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {review.prompt_version}
                          </p>
                        </td>
                        <td>
                          <p>{(review.total_tokens ?? 0).toLocaleString()} tokens</p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {review.cost_amount === null
                              ? "Cost unavailable"
                              : `${review.cost_amount} ${review.cost_currency ?? ""}`}
                          </p>
                        </td>
                        <td className="text-muted-foreground">
                          {formatDate(review.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <PaginationControls
            pathname={`/dashboard/${encodeURIComponent(organizationSlug)}/ai-reviews`}
            total={reviewPage.total}
            limit={reviewPage.limit}
            offset={reviewPage.offset}
            hasMore={reviewPage.has_more}
          />
        </section>
      </div>
    </AppShell>
  );
}
