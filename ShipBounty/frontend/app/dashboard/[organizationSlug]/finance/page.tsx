import { notFound, redirect } from "next/navigation";
import {
  AlertTriangle,
  CircleDollarSign,
  Landmark,
  RefreshCw,
  WalletCards,
} from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";
import {
  EmptyTable,
  PageHeader,
  StatusPill,
} from "@/components/workspace/page-header";
import { PaginationControls } from "@/components/workspace/pagination-controls";
import {
  getOrganizations,
  getPayouts,
  getProductAnalytics,
  getTreasuries,
  getTreasuryLedger,
  isAuthenticationError,
} from "@/services/api-server";
import { formatDate } from "@/services/api";

export default async function FinancePage({
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
  const [payoutPage, analytics] = await Promise.all([
    getPayouts(organization.id, offset),
    getProductAnalytics(organization.id),
  ]);
  const canViewTreasury = ["owner", "admin"].includes(organization.role);
  const treasuries = canViewTreasury
    ? await getTreasuries(organization.id)
    : [];
  const primaryTreasury = treasuries[0] ?? null;
  const ledger = primaryTreasury
    ? await getTreasuryLedger(primaryTreasury.id)
    : [];
  const payouts = payoutPage.items;
  const stateCounts =
    (payoutPage.aggregates.state_counts as
      | Record<string, number>
      | undefined) ?? {};
  const formatValue = (value: unknown) => {
    const byCurrency = (value as Record<string, string> | undefined) ?? {};
    return (
      Object.entries(byCurrency)
        .map(
          ([currency, amount]) =>
            `${Number(amount).toLocaleString()} ${currency}`,
        )
        .join(" · ") || "0"
    );
  };
  const reservedValue = formatValue(
    payoutPage.aggregates.reserved_value_by_currency,
  );
  const confirmedValue = formatValue(
    payoutPage.aggregates.confirmed_value_by_currency,
  );

  return (
    <AppShell>
      <div className="space-y-7">
        <PageHeader
          eyebrow="Financial control plane"
          title="Payouts and treasury"
          description="Provider-controlled payout authorization, submission recovery, confirmation, and reconciliation—separate from scoring and review."
          icon={WalletCards}
          actions={
            <span className="inline-flex h-11 items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 text-sm font-semibold text-emerald-800 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-300">
              <Landmark className="h-4 w-4" />
              Treasury controls enforced
            </span>
          }
        />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            {
              label: "Reserved value",
              value: reservedValue,
              detail: "Authorized through submitted",
              icon: Landmark,
            },
            {
              label: "Confirmed value",
              value: confirmedValue,
              detail: `${analytics.confirmed_payouts} confirmed payouts`,
              icon: CircleDollarSign,
            },
            {
              label: "Awaiting action",
              value: (stateCounts.created ?? 0) + (stateCounts.authorized ?? 0),
              detail: "Approval or submission required",
              icon: WalletCards,
            },
            {
              label: "Recovery attention",
              value:
                (stateCounts.submission_unknown ?? 0) +
                (stateCounts.failed ?? 0),
              detail: "No ambiguous result treated as failure",
              icon: AlertTriangle,
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
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
            <div>
              <h2 className="font-semibold">Treasury accounts</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Authoritative ledger balances, custody limits, and emergency
                state.
              </p>
            </div>
            {!canViewTreasury && (
              <span className="text-xs font-semibold text-muted-foreground">
                Owner or administrator access required
              </span>
            )}
          </div>
          {treasuries.length === 0 ? (
            <EmptyTable
              title={
                canViewTreasury
                  ? "No treasury configured"
                  : "Treasury access is restricted"
              }
              description={
                canViewTreasury
                  ? "Create a testnet treasury before authorizing integrated payouts."
                  : "Financial balances and custody configuration are visible only to organization owners and administrators."
              }
            />
          ) : (
            <div className="grid gap-4 p-5 xl:grid-cols-2">
              {treasuries.map((treasury) => (
                <article
                  key={treasury.id}
                  className="rounded-xl border border-border p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold">
                        {treasury.chain} · {treasury.currency}
                      </p>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">
                        {treasury.treasury_address}
                      </p>
                    </div>
                    <StatusPill status={treasury.status} />
                  </div>
                  <dl className="mt-4 grid grid-cols-3 gap-3">
                    {[
                      ["Available", treasury.available_balance],
                      ["Reserved", treasury.reserved_balance],
                      ["Settled", treasury.settled_amount],
                    ].map(([label, value]) => (
                      <div key={String(label)}>
                        <dt className="text-xs text-muted-foreground">
                          {label}
                        </dt>
                        <dd className="mt-1 font-semibold">
                          {Number(value).toLocaleString()}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <p className="mt-4 text-xs text-muted-foreground">
                    {treasury.environment} · {treasury.custody_model} custody ·{" "}
                    {treasury.required_confirmations} confirmation
                    {treasury.required_confirmations === 1 ? "" : "s"} ·
                    simulation {treasury.simulation_required ? "required" : "off"}
                  </p>
                  {treasury.paused_reason && (
                    <p className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-400/10 dark:text-rose-200">
                      Emergency pause: {treasury.paused_reason}
                    </p>
                  )}
                </article>
              ))}
            </div>
          )}
          <PaginationControls
            pathname={`/dashboard/${encodeURIComponent(organizationSlug)}/finance`}
            total={payoutPage.total}
            limit={payoutPage.limit}
            offset={payoutPage.offset}
            hasMore={payoutPage.has_more}
          />
        </section>
        {primaryTreasury && (
          <section className="surface overflow-hidden">
            <div className="border-b border-border px-5 py-4">
              <h2 className="font-semibold">Latest treasury ledger entries</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Account #{primaryTreasury.id}; showing {Math.min(ledger.length, 20)}{" "}
                of {ledger.length} loaded entries.
              </p>
            </div>
            {ledger.length === 0 ? (
              <EmptyTable
                title="The treasury ledger is empty"
                description="Reservations, releases, and settlements will appear here with idempotency provenance."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <caption className="sr-only">
                    Treasury reservation and settlement ledger
                  </caption>
                  <thead>
                    <tr>
                      <th>Entry</th>
                      <th>Type</th>
                      <th>Available Δ</th>
                      <th>Reserved Δ</th>
                      <th>Settled Δ</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ledger.slice(0, 20).map((entry) => (
                      <tr key={entry.id}>
                        <td>
                          <p className="font-semibold">Ledger #{entry.id}</p>
                          <p className="mt-1 font-mono text-xs text-muted-foreground">
                            {entry.idempotency_key}
                          </p>
                        </td>
                        <td className="capitalize">
                          {entry.entry_type.replaceAll("_", " ")}
                        </td>
                        <td>{Number(entry.available_delta).toLocaleString()}</td>
                        <td>{Number(entry.reserved_delta).toLocaleString()}</td>
                        <td>{Number(entry.settled_delta).toLocaleString()}</td>
                        <td className="text-muted-foreground">
                          {formatDate(entry.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
        <section className="surface overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <div>
              <h2 className="font-semibold">Payout ledger workflow</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Showing {payouts.length} of {payoutPage.total}. Provider
                references and confirmation provenance remain auditable.
              </p>
            </div>
            <RefreshCw className="h-4 w-4 text-muted-foreground" />
          </div>
          {payouts.length === 0 ? (
            <EmptyTable
              title="No payouts created"
              description="An approved claim and immutable approval snapshot are required before a payout can enter this console."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <caption className="sr-only">
                  Payout authorization and settlement history
                </caption>
                <thead>
                  <tr>
                    <th>Payout</th>
                    <th>Amount</th>
                    <th>Provider</th>
                    <th>State</th>
                    <th>Confirmations</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {payouts.map((payout) => (
                    <tr key={payout.id}>
                      <td>
                        <p className="font-semibold">Payout #{payout.id}</p>
                        <p className="mt-1 max-w-56 truncate font-mono text-xs text-muted-foreground">
                          {payout.provider_reference ??
                            payout.idempotency_key}
                        </p>
                      </td>
                      <td className="font-semibold">
                        {Number(payout.amount).toLocaleString()} {payout.currency}
                      </td>
                      <td>
                        <p>{payout.provider_key ?? "Not assigned"}</p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {payout.destination_chain}
                          </p>
                          {payout.explorer_url && (
                            <a
                              href={payout.explorer_url}
                              target="_blank"
                              rel="noreferrer"
                              className="mt-1 inline-block text-xs font-semibold text-primary hover:underline"
                            >
                              Open transaction explorer
                            </a>
                          )}
                      </td>
                      <td>
                        <StatusPill status={payout.state} />
                      </td>
                      <td>
                        {payout.observed_confirmations} /{" "}
                        {payout.required_confirmations}
                      </td>
                      <td className="text-muted-foreground">
                        {formatDate(payout.updated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
