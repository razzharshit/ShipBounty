import type { PullRequest } from "@/lib/types";
import { formatDate, getRepoLabel } from "@/services/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { ArrowLeft, FileDiff, GitCommit, GitPullRequest } from "lucide-react";

interface PRDetailHeaderProps {
  pr: PullRequest;
  showBack?: boolean;
}

const lifecycleBadgeClasses: Record<PullRequest["state"], string> = {
  draft: "border-amber-200 bg-amber-50 text-amber-700",
  open: "border-green-200 bg-[#E8F5E9] text-[#2E7D32]",
  closed: "border-[#E2E8F0] bg-[#F1F5F9] text-[#475569]",
  merged: "border-purple-200 bg-purple-50 text-purple-700",
};

function stateLabel(value: string) {
  return value.replaceAll("_", " ");
}

export function PRDetailHeader({ pr, showBack = true }: PRDetailHeaderProps) {
  return (
    <div className="space-y-4">
      {showBack && (
        <Link
          href="/pull-requests"
          className="inline-flex h-9 items-center rounded-lg px-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
        >
            <ArrowLeft className="mr-1.5 h-4 w-4" />
            Back to Explorer
        </Link>
      )}

      <div className="surface flex flex-col gap-5 p-5 sm:p-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <GitPullRequest className="h-4 w-4 text-primary" />
            <span className="font-mono text-sm text-muted-foreground">
              {getRepoLabel(pr)} #{pr.github_pr_number ?? pr.id}
            </span>
            <Badge
              variant="outline"
              className={lifecycleBadgeClasses[pr.state]}
            >
              {pr.state}
            </Badge>
            <Badge variant="outline" className="border-blue-200 bg-blue-50 text-blue-700">
              Review: {stateLabel(pr.review_state)}
            </Badge>
            <Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700">
              Payout: {stateLabel(pr.eligibility_state)}
            </Badge>
          </div>
          <h1 className="max-w-4xl text-2xl font-semibold tracking-[-0.03em] text-foreground sm:text-3xl">
            {pr.title}
          </h1>
          <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <div className="flex items-center gap-2">
              <Avatar className="h-5 w-5">
                {pr.author.avatar_url && (
                  <AvatarImage src={pr.author.avatar_url} alt={pr.author.username} />
                )}
                <AvatarFallback className="bg-primary/10 text-[10px] text-primary">
                  {pr.author.username.slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              {pr.author.username}
            </div>
            <span>·</span>
            <span>{formatDate(pr.created_at)}</span>
            {pr.head_sha && (
              <>
                <span>·</span>
                <span className="flex items-center gap-1.5 font-mono text-xs">
                  <GitCommit className="h-3.5 w-3.5" />
                  {pr.head_sha.slice(0, 10)}
                </span>
              </>
            )}
          </div>
        </div>

        <Link
          href={`/pull-requests/${pr.id}/patches`}
          className="inline-flex h-11 items-center justify-center rounded-xl bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
            <FileDiff className="mr-2 h-4 w-4" />
            View Patches
        </Link>
      </div>
    </div>
  );
}
