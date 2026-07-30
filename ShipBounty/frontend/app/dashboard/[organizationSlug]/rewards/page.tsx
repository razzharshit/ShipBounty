import { notFound, redirect } from "next/navigation";
import {
  CircleDollarSign,
  GitPullRequest,
  HandCoins,
  Users,
} from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";
import {
  EmptyTable,
  PageHeader,
  StatusPill,
} from "@/components/workspace/page-header";
import { PaginationControls } from "@/components/workspace/pagination-controls";
import {
  getBounties,
  getClaims,
  getOrganizations,
  getRepositories,
  isAuthenticationError,
} from "@/services/api-server";
import { formatDate } from "@/services/api";

export default async function RewardsPage({
  params,
  searchParams,
}: {
  params: Promise<{ organizationSlug: string }>;
  searchParams: Promise<{
    bounty_offset?: string;
    claim_offset?: string;
  }>;
}) {
  const { organizationSlug } = await params;
  const resolvedSearchParams = await searchParams;
  const bountyOffset = Math.max(
    0,
    Number(resolvedSearchParams.bounty_offset) || 0,
  );
  const claimOffset = Math.max(
    0,
    Number(resolvedSearchParams.claim_offset) || 0,
  );
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
  const [bountyPage, claimPage, repositories] = await Promise.all([
    getBounties(organization.id, bountyOffset),
    getClaims(organization.id, claimOffset),
    getRepositories(organization.id),
  ]);
  const bounties = bountyPage.items;
  const claims = claimPage.items;
  const repositoriesById = new Map(
    repositories.map((item) => [item.id, item]),
  );
  const bountyStatusCounts =
    (bountyPage.aggregates.status_counts as
      | Record<string, number>
      | undefined) ?? {};
  const claimStatusCounts =
    (claimPage.aggregates.status_counts as
      | Record<string, number>
      | undefined) ?? {};
  const activeValueByCurrency =
    (bountyPage.aggregates.active_value_by_currency as
      | Record<string, string>
      | undefined) ?? {};
  const activeValue =
    Object.entries(activeValueByCurrency)
      .map(
        ([currency, amount]) =>
          `${Number(amount).toLocaleString()} ${currency}`,
      )
      .join(" · ") || "0";

  return (
    <AppShell>
      <div className="space-y-7">
        <PageHeader
          eyebrow="Contribution rewards"
          title="Bounties and claims"
          description="Trace every reward from issue policy and contributor assignment through eligibility, claim approval, and settlement."
          icon={CircleDollarSign}
        />
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            {
              label: "Active bounty value",
              value: activeValue,
              detail: "Open and assigned rewards",
              icon: HandCoins,
            },
            {
              label: "Active bounties",
              value:
                (bountyStatusCounts.open ?? 0) +
                (bountyStatusCounts.assigned ?? 0),
              detail: `${bountyPage.total} total records`,
              icon: GitPullRequest,
            },
            {
              label: "Approved claims",
              value: claimStatusCounts.approved ?? 0,
              detail: "Awaiting payout lifecycle",
              icon: Users,
            },
          ].map(({ label, value, detail, icon: Icon }) => (
            <div key={label} className="surface p-5">
              <div className="flex items-start justify-between">
                <p className="text-sm font-medium text-muted-foreground">{label}</p>
                <span className="rounded-xl bg-emerald-500/10 p-2 text-emerald-600">
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
            <h2 className="font-semibold">Bounty workspace</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Showing {bounties.length} of {bountyPage.total}. Funding and
              eligibility are independent controls.
            </p>
          </div>
          {bounties.length === 0 ? (
            <EmptyTable
              title="No bounties in this organization"
              description="Record a GitHub issue and create a policy-bound bounty to begin the reward lifecycle."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <caption className="sr-only">
                  Organization bounties and funding state
                </caption>
                <thead>
                  <tr>
                    <th>Bounty</th>
                    <th>Repository</th>
                    <th>Reward</th>
                    <th>Lifecycle</th>
                    <th>Funding</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {bounties.map((bounty) => (
                    <tr key={bounty.id}>
                      <td>
                        <p className="font-semibold">Bounty #{bounty.id}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Issue #{bounty.issue_id}
                        </p>
                      </td>
                      <td>
                        {repositoriesById.get(bounty.repository_id)?.full_name ??
                          `Repository ${bounty.repository_id}`}
                      </td>
                      <td className="font-semibold">
                        {Number(bounty.amount).toLocaleString()} {bounty.currency}
                      </td>
                      <td>
                        <StatusPill status={bounty.status} />
                      </td>
                      <td>
                        <StatusPill status={bounty.funding_status} />
                      </td>
                      <td className="text-muted-foreground">
                        {formatDate(bounty.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <PaginationControls
            pathname={`/dashboard/${encodeURIComponent(organizationSlug)}/rewards`}
            total={bountyPage.total}
            limit={bountyPage.limit}
            offset={bountyPage.offset}
            hasMore={bountyPage.has_more}
            offsetKey="bounty_offset"
            query={{ claim_offset: claimOffset || undefined }}
          />
        </section>
        <section className="surface overflow-hidden">
          <div className="border-b border-border px-5 py-4">
            <h2 className="font-semibold">Claims</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Showing {claims.length} of {claimPage.total} immutable claims.
            </p>
          </div>
          {claims.length === 0 ? (
            <EmptyTable
              title="No claims submitted"
              description="An eligible pull request, approved assignment, and verified wallet are required before a claim is created."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <caption className="sr-only">
                  Bounty claims and payout readiness
                </caption>
                <thead>
                  <tr>
                    <th>Claim</th>
                    <th>Bounty</th>
                    <th>Pull request</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {claims.map((claim) => (
                    <tr key={claim.id}>
                      <td className="font-semibold">Claim #{claim.id}</td>
                      <td>Bounty #{claim.bounty_id}</td>
                      <td>PR #{claim.pull_request_id}</td>
                      <td className="font-semibold">
                        {Number(claim.amount).toLocaleString()} {claim.currency}
                      </td>
                      <td>
                        <StatusPill status={claim.status} />
                      </td>
                      <td className="text-muted-foreground">
                        {formatDate(claim.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <PaginationControls
            pathname={`/dashboard/${encodeURIComponent(organizationSlug)}/rewards`}
            total={claimPage.total}
            limit={claimPage.limit}
            offset={claimPage.offset}
            hasMore={claimPage.has_more}
            offsetKey="claim_offset"
            query={{ bounty_offset: bountyOffset || undefined }}
          />
        </section>
      </div>
    </AppShell>
  );
}
