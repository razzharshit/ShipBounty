import { AppShell } from "@/components/layout/app-shell";
import { LanguagePieChart } from "@/components/charts/language-pie-chart";
import { MetricsCards } from "@/components/pull-requests/metrics-cards";
import { PRDetailHeader } from "@/components/pull-requests/pr-detail-header";
import { ScoreBreakdown } from "@/components/pull-requests/score-breakdown";
import { EligibilityDecisionCard } from "@/components/pull-requests/eligibility-decision-card";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getPRMetrics,
  getPRScore,
  getEligibilityDecisions,
  getActionErrorMessage,
  getOrganizations,
  getPRAIReviews,
  getPullRequests,
  isAuthenticationError,
  requestAIReview,
  resyncPullRequest,
  submitEligibilityApproval,
  submitHumanReview,
} from "@/services/api-server";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  CheckCircle2,
  FileDiff,
  LayoutDashboard,
  RefreshCw,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { formatDate } from "@/services/api";

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    action_error?: string;
    action_success?: string;
  }>;
}

export default async function PullRequestDetailPage({
  params,
  searchParams,
}: PageProps) {
  const { id } = await params;
  const actionFeedback = await searchParams;
  const prId = Number(id);

  if (Number.isNaN(prId)) notFound();

  let prs;
  try {
    prs = await getPullRequests();
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    return (
      <AppShell>
        <ErrorState
          title="Unable to reach backend"
          description="Make sure the API is running at http://localhost:8000."
        />
      </AppShell>
    );
  }

  const pr = prs.find((p) => p.id === prId);
  if (!pr) notFound();

  const [metrics, score, eligibilityDecisions, aiReviews, organizations] =
    await Promise.all([
    getPRMetrics(prId),
    getPRScore(prId),
    getEligibilityDecisions(prId),
    getPRAIReviews(prId),
    getOrganizations(),
  ]);
  const currentDecision =
    eligibilityDecisions.find((decision) => decision.is_current) ?? null;
  const metricsData = metrics.status === "ready" ? metrics.data : null;
  const scoreData = score.status === "ready" ? score.data : null;
  const organization = organizations.find(
    (item) => item.id === pr.repository.organization_id,
  );
  const policyRules =
    (currentDecision?.evaluation_result.policy.rules as
      | Record<string, unknown>
      | undefined) ?? {};
  const reviewRoles = Array.isArray(policyRules.review_roles)
    ? policyRules.review_roles
    : [];
  const approvalRoles = Array.isArray(policyRules.approval_roles)
    ? policyRules.approval_roles
    : [];
  const canReview =
    currentDecision !== null &&
    ["pending_review", "changes_requested"].includes(currentDecision.status) &&
    Boolean(organization && reviewRoles.includes(organization.role));
  const canApprove =
    currentDecision?.status === "pending_approval" &&
    Boolean(organization && approvalRoles.includes(organization.role));
  async function requestResync() {
    "use server";
    let errorMessage: string | null = null;
    try {
      await resyncPullRequest(prId);
    } catch (error) {
      errorMessage = getActionErrorMessage(error);
    }
    if (errorMessage) {
      redirect(
        `/pull-requests/${prId}?action_error=${encodeURIComponent(errorMessage)}`,
      );
    }
    redirect(
      `/pull-requests/${prId}?action_success=${encodeURIComponent("Synchronization has been queued.")}`,
    );
  }
  async function requestAdvisoryReview(formData?: FormData) {
    "use server";
    const force = formData?.get("force") === "true";
    let errorMessage: string | null = null;
    try {
      await requestAIReview(prId, force);
    } catch (error) {
      errorMessage = getActionErrorMessage(error);
    }
    if (errorMessage) {
      redirect(
        `/pull-requests/${prId}?action_error=${encodeURIComponent(errorMessage)}#ai-review`,
      );
    }
    redirect(
      `/pull-requests/${prId}?action_success=${encodeURIComponent(force ? "Advisory review retry requested." : "Advisory review requested.")}#ai-review`,
    );
  }
  async function submitReviewAction(formData: FormData) {
    "use server";
    if (!currentDecision) return;
    const recommendation = String(formData.get("recommendation"));
    if (
      !["approve", "request_changes", "reject"].includes(recommendation)
    ) {
      return;
    }
    const message = String(formData.get("finding_message") ?? "").trim();
    let errorMessage: string | null = null;
    try {
      await submitHumanReview(currentDecision.id, {
        recommendation: recommendation as
          | "approve"
          | "request_changes"
          | "reject",
        summary: String(formData.get("summary") ?? "").trim(),
        findings: message
          ? [
              {
                severity: String(formData.get("severity") ?? "medium") as
                  | "info"
                  | "low"
                  | "medium"
                  | "high"
                  | "critical",
                category: "human_review",
                code: "REVIEW_FINDING",
                message,
                evidence: { source: "reviewer" },
              },
            ]
          : [],
      });
    } catch (error) {
      errorMessage = getActionErrorMessage(error);
    }
    if (errorMessage) {
      redirect(
        `/pull-requests/${prId}?action_error=${encodeURIComponent(errorMessage)}#human-review`,
      );
    }
    redirect(
      `/pull-requests/${prId}?action_success=${encodeURIComponent("Human review recorded.")}#human-review`,
    );
  }
  async function submitApprovalAction(formData: FormData) {
    "use server";
    if (!currentDecision) return;
    const outcome = String(formData.get("outcome"));
    if (!["approved", "rejected"].includes(outcome)) return;
    const reason = String(formData.get("reason") ?? "").trim();
    let errorMessage: string | null = null;
    try {
      await submitEligibilityApproval(currentDecision.id, {
        outcome: outcome as "approved" | "rejected",
        reason: reason || null,
      });
    } catch (error) {
      errorMessage = getActionErrorMessage(error);
    }
    if (errorMessage) {
      redirect(
        `/pull-requests/${prId}?action_error=${encodeURIComponent(errorMessage)}#human-review`,
      );
    }
    redirect(
      `/pull-requests/${prId}?action_success=${encodeURIComponent("Approval decision recorded.")}#human-review`,
    );
  }

  return (
    <AppShell>
      <div className="space-y-6">
        <PRDetailHeader pr={pr} />
        {actionFeedback.action_error && (
          <div
            role="alert"
            className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-800 dark:border-rose-400/20 dark:bg-rose-400/10 dark:text-rose-200"
          >
            {actionFeedback.action_error}
          </div>
        )}
        {actionFeedback.action_success && (
          <div
            role="status"
            className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200"
          >
            {actionFeedback.action_success}
          </div>
        )}
        <nav className="surface flex gap-1 overflow-x-auto p-1.5">
          {[
            { label: "Overview", href: "#overview", icon: LayoutDashboard },
            { label: "Diff", href: `/pull-requests/${prId}/patches`, icon: FileDiff },
            { label: "Analysis", href: "#analysis", icon: BarChart3 },
            { label: "Human review", href: "#human-review", icon: ShieldCheck },
            { label: "AI review", href: "#ai-review", icon: Bot },
            { label: "Eligibility", href: "#eligibility", icon: CheckCircle2 },
            { label: "Activity", href: "#activity", icon: Activity },
          ].map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className="inline-flex h-10 shrink-0 items-center gap-2 rounded-lg px-3 text-sm font-semibold text-muted-foreground transition hover:bg-accent hover:text-foreground first:bg-primary/10 first:text-primary"
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          ))}
        </nav>

        {metricsData ? (
          <div id="overview" className="scroll-mt-28 space-y-6">
            <MetricsCards metrics={metricsData} />
            <div id="analysis" className="scroll-mt-28">
              {scoreData && <ScoreBreakdown score={scoreData} pr={pr} />}
            </div>
            <div id="eligibility" className="scroll-mt-28">
              <EligibilityDecisionCard decision={currentDecision} />
            </div>
            <Card className="border-border bg-card shadow-sm">
              <CardHeader className="pb-2 pt-4 px-4">
                <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                  <BarChart3 className="h-4 w-4 text-primary" />
                  Language Breakdown
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <LanguagePieChart breakdown={metricsData.language_breakdown} />
              </CardContent>
            </Card>
          </div>
        ) : (
          <EmptyState
            icon={
              metrics.status === "incomplete" ? AlertTriangle : BarChart3
            }
            title={
              metrics.status === "incomplete"
                ? "GitHub synchronization is incomplete"
                : "Analysis is still waiting"
            }
            description={
              metrics.status === "incomplete"
                ? `${metrics.reason}. Limit: 3,000 retrievable files. Last synchronized SHA: ${pr.last_synchronized_head_sha ?? "not recorded"}. No authoritative score is shown.`
                : metrics.status === "missing"
                  ? metrics.message
                  : "Analysis is not available yet."
            }
            action={
              <form action={requestResync}>
                <button
                  type="submit"
                  className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 text-xs font-semibold text-white hover:bg-blue-700"
                >
                  <RefreshCw className="h-4 w-4" />
                  Retry synchronization
                </button>
              </form>
            }
          />
        )}

        <section id="human-review" className="scroll-mt-28 space-y-4">
          <div className="surface p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="eyebrow">Human control plane</p>
                <h2 className="mt-2 text-xl font-semibold">Human review</h2>
                <p className="mt-2 text-sm text-muted-foreground">
                  Findings and approvals are tied to score #
                  {currentDecision?.score_id ?? "—"} and policy #
                  {currentDecision?.repository_policy_id ?? "—"}.
                </p>
              </div>
              <span className="rounded-lg bg-primary/10 px-3 py-2 text-xs font-bold uppercase tracking-wide text-primary">
                {currentDecision?.status.replaceAll("_", " ") ??
                  "Not evaluated"}
              </span>
            </div>

            {!currentDecision ? (
              <p className="mt-6 rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
                No current eligibility decision is available yet.
              </p>
            ) : (
              <div className="mt-6 grid gap-4 lg:grid-cols-2">
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold">Submitted evidence</h3>
                  {currentDecision.reviews.length === 0 ? (
                    <p className="rounded-xl bg-muted/55 p-4 text-sm text-muted-foreground">
                      No human review has been submitted.
                    </p>
                  ) : (
                    currentDecision.reviews.map((review) => (
                      <article
                        key={review.id}
                        className="rounded-xl border border-border p-4"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <p className="font-semibold capitalize">
                            {review.recommendation?.replaceAll("_", " ")}
                          </p>
                          <span className="text-xs text-muted-foreground">
                            {formatDate(review.completed_at ?? review.started_at)}
                          </span>
                        </div>
                        <p className="mt-2 text-sm text-muted-foreground">
                          {review.summary}
                        </p>
                        {review.findings.map((finding) => (
                          <div
                            key={finding.id}
                            className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-400/10 dark:text-amber-200"
                          >
                            <span className="font-bold uppercase">
                              {finding.severity}
                            </span>{" "}
                            · {finding.message}
                          </div>
                        ))}
                      </article>
                    ))
                  )}
                  {currentDecision.approvals.map((approval) => (
                    <article
                      key={approval.id}
                      className="rounded-xl border border-border p-4"
                    >
                      <p className="font-semibold capitalize">
                        Approval {approval.outcome}
                      </p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {approval.reason || "No reason supplied"} ·{" "}
                        {formatDate(approval.created_at)}
                      </p>
                    </article>
                  ))}
                </div>

                <div className="space-y-4">
                  {canReview && (
                    <form
                      action={submitReviewAction}
                      className="rounded-xl border border-border p-4"
                    >
                      <h3 className="flex items-center gap-2 text-sm font-semibold">
                        <UserCheck className="h-4 w-4 text-primary" />
                        Submit review
                      </h3>
                      <label className="mt-4 block text-xs font-semibold">
                        Recommendation
                        <select
                          name="recommendation"
                          className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm"
                        >
                          <option value="approve">Approve</option>
                          <option value="request_changes">
                            Request changes
                          </option>
                          <option value="reject">Reject</option>
                        </select>
                      </label>
                      <label className="mt-3 block text-xs font-semibold">
                        Review summary
                        <textarea
                          name="summary"
                          required
                          minLength={1}
                          className="mt-1.5 min-h-24 w-full rounded-lg border border-border bg-background p-3 text-sm"
                          placeholder="Explain the evidence behind this recommendation."
                        />
                      </label>
                      <div className="mt-3 grid gap-3 sm:grid-cols-[140px_1fr]">
                        <label className="block text-xs font-semibold">
                          Finding severity
                          <select
                            name="severity"
                            className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm"
                          >
                            <option value="info">Info</option>
                            <option value="medium">Medium</option>
                            <option value="high">High</option>
                            <option value="critical">Critical</option>
                          </select>
                        </label>
                        <label className="block text-xs font-semibold">
                          Optional finding
                          <input
                            name="finding_message"
                            className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm"
                            placeholder="Specific risk or required change"
                          />
                        </label>
                      </div>
                      <button className="mt-4 h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">
                        Record immutable review
                      </button>
                    </form>
                  )}
                  {canApprove && (
                    <form
                      action={submitApprovalAction}
                      className="rounded-xl border border-border p-4"
                    >
                      <h3 className="text-sm font-semibold">
                        Record approval decision
                      </h3>
                      <label className="mt-3 block text-xs font-semibold">
                        Reason (required for rejection)
                        <textarea
                          name="reason"
                          className="mt-1.5 min-h-20 w-full rounded-lg border border-border bg-background p-3 text-sm"
                        />
                      </label>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          name="outcome"
                          value="approved"
                          className="h-10 rounded-lg bg-emerald-600 px-4 text-sm font-semibold text-white"
                        >
                          Approve eligibility
                        </button>
                        <button
                          name="outcome"
                          value="rejected"
                          className="h-10 rounded-lg bg-rose-600 px-4 text-sm font-semibold text-white"
                        >
                          Reject
                        </button>
                      </div>
                    </form>
                  )}
                  {!canReview && !canApprove && (
                    <p className="rounded-xl bg-muted/55 p-4 text-sm text-muted-foreground">
                      No action is available for your organization role in the
                      current policy state.
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </section>

        <section id="ai-review" className="scroll-mt-28">
          <div className="surface p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="eyebrow">Advisory intelligence</p>
                <h2 className="mt-2 text-xl font-semibold">AI review</h2>
                <p className="mt-2 text-sm text-muted-foreground">
                  Structured output is advisory and cannot authorize payment.
                </p>
              </div>
              {scoreData && (
                <div className="flex flex-wrap gap-2">
                  <form action={requestAdvisoryReview}>
                    <input type="hidden" name="force" value="true" />
                    <button className="h-10 rounded-lg border border-border bg-card px-4 text-sm font-semibold hover:bg-muted">
                      <RefreshCw className="mr-2 inline h-3.5 w-3.5" />
                      Retry AI review
                    </button>
                  </form>
                  <form action={requestAdvisoryReview}>
                    <button className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">
                      Request advisory review
                    </button>
                  </form>
                </div>
              )}
            </div>
            <div className="mt-6 space-y-4">
              {aiReviews.length === 0 ? (
                <p className="rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
                  No AI review has been requested for this pull request.
                </p>
              ) : (
                aiReviews.map((review) => (
                  <article
                    key={review.id}
                    className="rounded-xl border border-border p-4 sm:p-5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="font-semibold">
                          {review.provider} · {review.model}
                        </p>
                        <p className="mt-1 font-mono text-xs text-muted-foreground">
                          {review.input_commit_sha.slice(0, 12)} ·{" "}
                          {review.prompt_version}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`rounded-lg px-3 py-1.5 text-xs font-bold uppercase ${
                          review.status === "failed" || review.status === "blocked"
                            ? "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                            : review.status === "complete"
                              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                              : "bg-primary/10 text-primary"
                        }`}>
                          {review.status}
                        </span>
                        {(review.status === "failed" || review.status === "pending") && (
                          <form action={requestAdvisoryReview}>
                            <input type="hidden" name="force" value="true" />
                            <button
                              title="Retry AI review"
                              className="rounded-lg border border-border p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                            >
                              <RefreshCw className="h-3.5 w-3.5" />
                            </button>
                          </form>
                        )}
                      </div>
                    </div>
                    {review.status === "failed" && review.failure_reason ? (
                      <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50/60 p-4 dark:border-rose-900/30 dark:bg-rose-950/20">
                        <div className="flex items-center justify-between gap-2">
                          <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-rose-700 dark:text-rose-400">
                            <AlertTriangle className="h-4 w-4" /> Provider Execution Failed
                          </p>
                          <form action={requestAdvisoryReview}>
                            <input type="hidden" name="force" value="true" />
                            <button className="inline-flex items-center gap-1.5 rounded-md bg-rose-600 px-3 py-1 text-xs font-semibold text-white shadow-sm hover:bg-rose-700">
                              <RefreshCw className="h-3 w-3" />
                              Retry attempt
                            </button>
                          </form>
                        </div>
                        <pre className="mt-2 max-h-60 overflow-y-auto whitespace-pre-wrap rounded-lg bg-white/80 p-3 font-mono text-xs text-rose-900 border border-rose-200/50 dark:bg-slate-900/80 dark:text-rose-200 dark:border-rose-900/50">
                          {review.failure_reason}
                        </pre>
                      </div>
                    ) : (
                      <p className="mt-4 text-sm leading-6">
                        {review.output?.summary ?? "The provider is processing this review."}
                      </p>
                    )}
                    {review.output && (
                      <div className="mt-4 grid gap-3 lg:grid-cols-3">
                        {[
                          [
                            "Positive findings",
                            review.output.positive_findings ?? [],
                          ],
                          ["Risk findings", review.output.risk_findings ?? []],
                          [
                            "Recommended actions",
                            review.output.recommended_actions ?? [],
                          ],
                        ].map(([label, items]) => (
                          <div key={String(label)} className="rounded-lg bg-muted/50 p-3">
                            <h3 className="text-xs font-bold uppercase tracking-wide">
                              {String(label)}
                            </h3>
                            <ul className="mt-2 space-y-2 text-sm text-muted-foreground">
                              {(items as string[]).length === 0 ? (
                                <li>None recorded</li>
                              ) : (
                                (items as string[]).map((item) => (
                                  <li key={item}>• {item}</li>
                                ))
                              )}
                            </ul>
                          </div>
                        ))}
                      </div>
                    )}
                    <details className="mt-4 rounded-lg border border-border p-3">
                      <summary className="cursor-pointer text-sm font-semibold">
                        Safety, privacy, and usage provenance
                      </summary>
                      <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                        <div>
                          <dt className="text-muted-foreground">Privacy</dt>
                          <dd className="mt-1 break-words font-mono text-xs">
                            {JSON.stringify(review.privacy_decision)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">Moderation</dt>
                          <dd className="mt-1 break-words font-mono text-xs">
                            {JSON.stringify(
                              review.moderation_result ?? { status: "not_run" },
                            )}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">Usage</dt>
                          <dd className="mt-1">
                            {(review.total_tokens ?? 0).toLocaleString()} tokens
                            · {review.cost_amount ?? 0}{" "}
                            {review.cost_currency ?? ""}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">Requested</dt>
                          <dd className="mt-1">{formatDate(review.created_at)}</dd>
                        </div>
                      </dl>
                    </details>
                  </article>
                ))
              )}
            </div>
          </div>
        </section>

        <section id="activity" className="scroll-mt-28">
          <div className="surface p-5 sm:p-6">
            <p className="eyebrow">Audit timeline</p>
            <h2 className="mt-2 text-xl font-semibold">Activity</h2>
            <ol className="mt-5 space-y-4 border-l border-border pl-5">
              {[
                {
                  label: "Pull request ingested",
                  date: pr.created_at,
                  detail: `GitHub PR #${pr.github_pr_number ?? pr.id}`,
                },
                ...(pr.synchronized_at
                  ? [
                      {
                        label: "GitHub state synchronized",
                        date: pr.synchronized_at,
                        detail: pr.last_synchronized_head_sha
                          ? `Head ${pr.last_synchronized_head_sha.slice(0, 12)}`
                          : "Current GitHub snapshot",
                      },
                    ]
                  : []),
                ...eligibilityDecisions.map((decision) => ({
                  label: `Eligibility ${decision.status.replaceAll("_", " ")}`,
                  date: decision.created_at,
                  detail: `Score #${decision.score_id} · Policy #${decision.repository_policy_id}`,
                })),
                ...aiReviews.map((review) => ({
                  label: `AI review ${review.status}`,
                  date: review.created_at,
                  detail: `${review.provider} · ${review.model}`,
                })),
              ]
                .sort(
                  (left, right) =>
                    new Date(right.date).getTime() -
                    new Date(left.date).getTime(),
                )
                .map((event) => (
                  <li key={`${event.label}-${event.date}`} className="relative">
                    <span className="absolute -left-[25px] top-1.5 h-2 w-2 rounded-full bg-primary" />
                    <p className="font-semibold">{event.label}</p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {event.detail} · {formatDate(event.date)}
                    </p>
                  </li>
                ))}
            </ol>
          </div>
        </section>
      </div>
    </AppShell>
  );
}

