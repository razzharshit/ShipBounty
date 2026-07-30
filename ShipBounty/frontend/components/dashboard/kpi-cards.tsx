import type { PullRequest } from "@/lib/types";
import { formatNumber } from "@/services/api";
import { Award, Coins, GitPullRequest, Wallet } from "lucide-react";

interface KpiCardsProps {
  prs: PullRequest[];
}

export function KpiCards({ prs }: KpiCardsProps) {
  const claimsDisbursed = prs.filter((pr) => pr.eligibility_state === "paid").length;
  const bountyPool = 0.00;
  const avgScore = prs.length > 0 ? 0.0 : 0;

  const cards = [
    {
      label: "Total Pull Requests",
      value: prs.length,
      subtext: "Ingested via webhooks",
      icon: GitPullRequest,
      color: "text-blue-600 bg-blue-50/50 border-blue-100",
    },
    {
      label: "Average Contribution Score",
      value: `${avgScore}/100`,
      subtext: "AI analysis quality index",
      icon: Award,
      color: "text-indigo-600 bg-indigo-50/50 border-indigo-100",
    },
    {
      label: "Active Bounty Pool",
      value: `$${formatNumber(bountyPool)}`,
      subtext: "Total allocated funding",
      icon: Wallet,
      color: "text-emerald-600 bg-emerald-50/50 border-emerald-100",
    },
    {
      label: "Claims Disbursed",
      value: claimsDisbursed,
      subtext: "Pull requests with paid eligibility",
      icon: Coins,
      color: "text-amber-600 bg-amber-50/50 border-amber-100",
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map(({ label, value, subtext, icon: Icon, color }) => (
        <div
          key={label}
          className="relative overflow-hidden rounded-xl border border-[#F1F5F9] bg-white p-5 shadow-[0_1px_3px_rgba(15,23,42,0.02)] transition-all duration-300 hover:shadow-[0_4px_12px_rgba(15,23,42,0.05)] hover:-translate-y-0.5"
        >
          <div className="flex items-start justify-between">
            <div className="space-y-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                {label}
              </span>
              <h3 className="text-2xl font-bold tracking-tight text-[#0F172A]">
                {value}
              </h3>
              <p className="text-[11px] font-medium text-[#64748B]">{subtext}</p>
            </div>
            <div className={`flex h-10 w-10 items-center justify-center rounded-lg border ${color}`}>
              <Icon className="h-5 w-5" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

