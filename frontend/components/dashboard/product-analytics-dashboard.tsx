import Link from "next/link";
import {
  ArrowUpRight,
  BadgeCheck,
  Bell,
  CircleDollarSign,
  GitBranch,
  HandCoins,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { StatusPill } from "@/components/workspace/page-header";
import type { Notification, ProductAnalytics } from "@/lib/types";
import { formatDate } from "@/services/api";

function mergeTime(seconds: number | null) {
  if (seconds === null) return "—";
  const hours = seconds / 3600;
  return hours < 48 ? `${hours.toFixed(1)}h` : `${(hours / 24).toFixed(1)}d`;
}

function moneyBreakdown(amounts: Record<string, string>) {
  const entries = Object.entries(amounts);
  if (!entries.length) return "No value recorded";
  return entries
    .map(
      ([currency, amount]) =>
        `${Number(amount).toLocaleString("en-US", { maximumFractionDigits: 2 })} ${currency}`,
    )
    .join(" · ");
}

export function ProductAnalyticsDashboard({
  data,
  notifications,
}: {
  data: ProductAnalytics;
  notifications: Notification[];
}) {
  const orgPrefix = `/dashboard/${encodeURIComponent(data.organization.login)}`;
  const cards = [
    {
      label: "Active bounty value",
      value: moneyBreakdown(data.open_bounty_amounts),
      detail: `${data.open_bounties} open bounties`,
      icon: CircleDollarSign,
      href: `${orgPrefix}/rewards`,
      tone: "text-emerald-600 bg-emerald-500/10",
    },
    {
      label: "Human reviews",
      value: data.pending_reviews,
      detail: "Pending policy decisions",
      icon: ShieldCheck,
      href: `${orgPrefix}/reviews`,
      tone: "text-indigo-600 bg-indigo-500/10",
    },
    {
      label: "Eligible claims",
      value: data.eligible_claims,
      detail: "Approved for payout workflow",
      icon: BadgeCheck,
      href: `${orgPrefix}/rewards`,
      tone: "text-violet-600 bg-violet-500/10",
    },
    {
      label: "Pending payouts",
      value: data.pending_payouts,
      detail: "Approval through submission",
      icon: HandCoins,
      href: `${orgPrefix}/finance`,
      tone: "text-amber-600 bg-amber-500/10",
    },
  ];
  const inAppNotifications = notifications.filter(
    (item) => item.channel === "in_app",
  );
  const unread = inAppNotifications.filter((item) => !item.read_at);
  const actionItems = [
    data.pending_reviews
      ? {
          label: `${data.pending_reviews} reviews need a human decision`,
          href: `${orgPrefix}/reviews`,
          tone: "amber",
        }
      : null,
    data.pending_payouts
      ? {
          label: `${data.pending_payouts} payouts are not yet confirmed`,
          href: `${orgPrefix}/finance`,
          tone: "indigo",
        }
      : null,
    unread.length
      ? {
          label: `${unread.length} unread operational notifications`,
          href: "#notifications",
          tone: "emerald",
        }
      : null,
  ].filter(Boolean) as Array<{ label: string; href: string; tone: string }>;

  return (
    <div className="space-y-7">
      <section className="relative overflow-hidden rounded-3xl border border-indigo-300/20 bg-[linear-gradient(125deg,#111827_0%,#1e1b4b_55%,#312e81_100%)] px-6 py-7 text-white shadow-2xl shadow-indigo-950/10 sm:px-8 sm:py-9">
        <div className="absolute -right-20 -top-28 h-80 w-80 rounded-full bg-indigo-400/15 blur-3xl" />
        <div className="absolute bottom-0 right-[28%] h-32 w-32 rounded-full bg-violet-400/10 blur-2xl" />
        <div className="relative grid gap-8 xl:grid-cols-[1fr_auto] xl:items-end">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-indigo-300">
              Executive overview
            </p>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">
              {data.organization.login}
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
              Evidence-backed contribution review and auditable reward operations
              across {data.organization.repository_count} repositories.
            </p>
            <div className="mt-6 flex flex-wrap gap-2 text-xs text-slate-300">
              <span className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5">
                {data.organization.contributor_count} contributors
              </span>
              <span className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5">
                {data.organization.pull_request_count} pull requests
              </span>
              <span className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5">
                Updated {formatDate(data.generated_at)}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-white/10 bg-white/[0.07] p-4 backdrop-blur-sm">
              <p className="text-xs text-indigo-200">Confirmed payouts</p>
              <p className="mt-2 text-2xl font-semibold">{data.confirmed_payouts}</p>
              <p className="mt-1 text-xs text-slate-400">
                {moneyBreakdown(data.confirmed_payout_amounts)}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.07] p-4 backdrop-blur-sm">
              <p className="text-xs text-indigo-200">Average merge time</p>
              <p className="mt-2 text-2xl font-semibold">
                {mergeTime(data.average_merge_seconds)}
              </p>
              <p className="mt-1 text-xs text-slate-400">Created to merged</p>
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(({ label, value, detail, icon: Icon, href, tone }) => (
          <Link
            key={label}
            href={href}
            className="surface group p-5 transition duration-200 hover:-translate-y-0.5 hover:border-primary/25 hover:shadow-lg"
          >
            <div className="flex items-start justify-between gap-3">
              <span className={`rounded-xl p-2.5 ${tone}`}>
                <Icon className="h-[18px] w-[18px]" />
              </span>
              <ArrowUpRight className="h-4 w-4 text-muted-foreground transition group-hover:text-primary" />
            </div>
            <p className="mt-5 text-sm font-medium text-muted-foreground">{label}</p>
            <p className="mt-2 truncate text-2xl font-semibold tracking-tight">
              {value}
            </p>
            <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
          </Link>
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
        <section className="surface overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <div>
              <h2 className="font-semibold">Repository risk and health</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Ingestion, bounty, and review signals in one operational view.
              </p>
            </div>
            <GitBranch className="h-5 w-5 text-primary" />
          </div>
          {data.repositories.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              No accessible repositories.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Repository</th>
                    <th>PRs</th>
                    <th>Reviews</th>
                    <th>Bounties</th>
                    <th>Health</th>
                  </tr>
                </thead>
                <tbody>
                  {data.repositories.map((repository) => (
                    <tr key={repository.repository_id}>
                      <td>
                        <p className="font-semibold">{repository.full_name}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {repository.incomplete_ingestions} incomplete ·{" "}
                          {repository.failed_deliveries} failed deliveries
                        </p>
                      </td>
                      <td>{repository.pull_requests}</td>
                      <td>{repository.pending_reviews}</td>
                      <td>{repository.open_bounties}</td>
                      <td>
                        <StatusPill status={repository.health} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="surface overflow-hidden">
          <div className="flex items-center gap-3 border-b border-border px-5 py-4">
            <Sparkles className="h-5 w-5 text-amber-500" />
            <div>
              <h2 className="font-semibold">Action required</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Prioritized operational work.
              </p>
            </div>
          </div>
          {actionItems.length === 0 ? (
            <div className="flex min-h-64 flex-col items-center justify-center px-8 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-600">
                <BadgeCheck className="h-5 w-5" />
              </span>
              <p className="mt-4 font-semibold">No urgent action</p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Current review, payout, and notification queues are clear.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {actionItems.map((item) => (
                <Link
                  key={item.label}
                  href={item.href}
                  className="group flex items-center gap-3 px-5 py-4 hover:bg-accent/35"
                >
                  <span
                    className={`h-2.5 w-2.5 rounded-full ${
                      item.tone === "amber"
                        ? "bg-amber-500"
                        : item.tone === "emerald"
                          ? "bg-emerald-500"
                          : "bg-indigo-500"
                    }`}
                  />
                  <span className="flex-1 text-sm font-medium">{item.label}</span>
                  <ArrowUpRight className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]">
        <section className="surface overflow-hidden">
          <div className="flex items-center gap-3 border-b border-border px-5 py-4">
            <Users className="h-5 w-5 text-primary" />
            <div>
              <h2 className="font-semibold">Contributor leaderboard</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Merge and payout outcomes.
              </p>
            </div>
          </div>
          <div className="divide-y divide-border">
            {data.contributors.length === 0 ? (
              <p className="py-16 text-center text-sm text-muted-foreground">
                No contributor activity recorded.
              </p>
            ) : (
              data.contributors.slice(0, 8).map((contributor, index) => (
                <div
                  key={contributor.user_id}
                  className="flex items-center gap-3 px-5 py-4"
                >
                  <span className="w-5 text-xs font-bold text-muted-foreground">
                    {index + 1}
                  </span>
                  <Avatar className="h-9 w-9">
                    <AvatarImage
                      src={contributor.avatar_url ?? undefined}
                      alt={contributor.username}
                    />
                    <AvatarFallback>
                      {contributor.username.slice(0, 2).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">
                      {contributor.username}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {contributor.merged_pull_requests} merged ·{" "}
                      {contributor.approved_claims} claims
                    </p>
                  </div>
                  <p className="text-sm font-bold text-emerald-600">
                    {contributor.confirmed_payouts}
                  </p>
                </div>
              ))
            )}
          </div>
        </section>

        <section
          id="notifications"
          className="surface scroll-mt-24 overflow-hidden"
        >
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <div className="flex items-center gap-3">
              <Bell className="h-5 w-5 text-primary" />
              <div>
                <h2 className="font-semibold">Recent activity</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Delivered domain notifications.
                </p>
              </div>
            </div>
            <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">
              {unread.length} unread
            </span>
          </div>
          {inAppNotifications.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              No domain notifications delivered yet.
            </p>
          ) : (
            <div className="divide-y divide-border">
              {inAppNotifications.slice(0, 12).map((notification) => (
                <div key={notification.id} className="flex gap-3 px-5 py-4">
                  <span
                    className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                      notification.read_at ? "bg-muted-foreground/30" : "bg-indigo-500"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-4">
                      <p className="text-sm font-semibold">{notification.subject}</p>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatDate(notification.created_at)}
                      </span>
                    </div>
                    <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                      {notification.body}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
