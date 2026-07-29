import Link from "next/link";
import { redirect } from "next/navigation";
import {
  Activity,
  BadgeCheck,
  CircleDollarSign,
  GitMerge,
  GitPullRequest,
  ListChecks,
  ShieldCheck,
} from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getOrganizations,
  getPullRequests,
  getPRScore,
  isAuthenticationError,
} from "@/services/api-server";

const STEPS = [
  {
    title: "1. GitHub App connected",
    description:
      "Install the app on one test repository and subscribe to pull request, review, and check events.",
    icon: ShieldCheck,
  },
  {
    title: "2. Real PR ingested",
    description:
      "Open a PR from the GitHub account that will act as the contributor. The queue fetches the current snapshot.",
    icon: GitPullRequest,
  },
  {
    title: "3. Analysis completed",
    description:
      "Merge the PR and wait for a complete, versioned deterministic score for its final head SHA.",
    icon: ListChecks,
  },
  {
    title: "4. Human controls exercised",
    description:
      "Use reviewer and owner personas to demonstrate separation of review and approval duties.",
    icon: BadgeCheck,
  },
  {
    title: "5. Bounty settled",
    description:
      "The demo runner creates the issue, bounty, claim, two treasury approvals, and a provider-controlled off-chain settlement.",
    icon: CircleDollarSign,
  },
];

export default async function DemoPage() {
  if (process.env.NEXT_PUBLIC_DEMO_MODE !== "true") redirect("/dashboard");

  let organizations: Awaited<ReturnType<typeof getOrganizations>>;
  let pullRequests: Awaited<ReturnType<typeof getPullRequests>>;
  try {
    [organizations, pullRequests] = await Promise.all([
      getOrganizations(),
      getPullRequests(),
    ]);
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    throw error;
  }

  const latest = pullRequests[0];
  const scoreResult = latest
    ? await getPRScore(latest.id).catch(() => null)
    : null;
  const score =
    scoreResult?.status === "ready" ? scoreResult.data : null;
  const merged = pullRequests.filter((item) => item.state === "merged").length;

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-5">
        <section className="overflow-hidden rounded-2xl border border-blue-100 bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950 p-7 text-white shadow-sm">
          <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
            <div className="max-w-2xl">
              <Badge className="mb-4 border-white/10 bg-white/10 text-blue-100">
                Non-production showcase
              </Badge>
              <h1 className="text-3xl font-bold tracking-tight">
                GitHub contribution to auditable reward
              </h1>
              <p className="mt-3 max-w-xl text-sm leading-6 text-slate-300">
                This guide uses a real GitHub repository, webhook delivery,
                file snapshot, and deterministic analysis. Only the final
                payment provider response is simulated.
              </p>
            </div>
            <Link
              href={
                organizations[0]
                  ? `/dashboard/${encodeURIComponent(organizations[0].login)}/operations`
                  : "/dashboard"
              }
              className="inline-flex items-center justify-center rounded-lg border border-white/15 bg-white/10 px-4 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-white/15"
            >
              <Activity className="mr-2 h-4 w-4" />
              Open operations
            </Link>
          </div>
        </section>

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Organizations", organizations.length],
            ["Ingested PRs", pullRequests.length],
            ["Merged PRs", merged],
            ["Latest score", score ? Number(score.final_score).toFixed(1) : "Waiting"],
          ].map(([label, value]) => (
            <Card key={label}>
              <CardContent className="p-5">
                <p className="text-xs font-medium text-slate-500">{label}</p>
                <p className="mt-2 text-2xl font-bold tracking-tight text-slate-900">
                  {value}
                </p>
              </CardContent>
            </Card>
          ))}
        </section>

        <div className="grid gap-5 lg:grid-cols-[1.4fr_0.6fr]">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Showcase sequence</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {STEPS.map(({ title, description, icon: Icon }) => (
                <div
                  key={title}
                  className="flex gap-4 rounded-xl border border-slate-200 p-4"
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      {title}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      {description}
                    </p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Current GitHub evidence</CardTitle>
            </CardHeader>
            <CardContent>
              {latest ? (
                <div className="space-y-4">
                  <div>
                    <p className="text-xs text-slate-500">Latest pull request</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">
                      {latest.title}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {latest.repository.owner}/{latest.repository.name} ·{" "}
                      {latest.author.username}
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-slate-500">Lifecycle</p>
                      <p className="mt-1 font-semibold capitalize text-slate-900">
                        {latest.state}
                      </p>
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-slate-500">File snapshot</p>
                      <p className="mt-1 font-semibold text-slate-900">
                        {latest.file_sync_complete ? "Complete" : "Waiting"}
                      </p>
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-slate-500">Review</p>
                      <p className="mt-1 font-semibold capitalize text-slate-900">
                        {latest.review_state.replaceAll("_", " ")}
                      </p>
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-slate-500">Eligibility</p>
                      <p className="mt-1 font-semibold capitalize text-slate-900">
                        {latest.eligibility_state.replaceAll("_", " ")}
                      </p>
                    </div>
                  </div>
                  <Link
                    href={`/pull-requests/${latest.id}`}
                    className="inline-flex items-center text-xs font-semibold text-blue-600 hover:text-blue-700"
                  >
                    <GitMerge className="mr-1.5 h-4 w-4" />
                    Inspect synchronized evidence
                  </Link>
                </div>
              ) : (
                <p className="text-sm leading-6 text-slate-500">
                  No pull request has been ingested yet. Open the test PR after
                  the GitHub App and workers are running.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
