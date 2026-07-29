"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { PullRequest } from "@/lib/types";
import { getRepoLabel } from "@/services/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GitPullRequest, Minus, Plus, Search } from "lucide-react";

type SortKey = "date" | "additions" | "deletions" | "files";
type FilterState = "all" | PullRequest["state"];

const lifecycleBadgeClasses: Record<PullRequest["state"], string> = {
  draft: "border-amber-200 bg-amber-50 text-amber-700",
  open: "border-green-200 bg-[#E8F5E9] text-[#2E7D32]",
  closed: "border-[#E2E8F0] bg-[#F1F5F9] text-[#475569]",
  merged: "border-purple-200 bg-purple-50 text-purple-700",
};

interface PRExplorerProps {
  prs: PullRequest[];
}

export function PRExplorer({ prs }: PRExplorerProps) {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("date");
  const [filter, setFilter] = useState<FilterState>("all");

  const filtered = useMemo(() => {
    let result = [...prs];

    if (filter !== "all") {
      result = result.filter((pr) => pr.state === filter);
    }

    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (pr) =>
          pr.title.toLowerCase().includes(q) ||
          pr.author.username.toLowerCase().includes(q) ||
          getRepoLabel(pr).toLowerCase().includes(q) ||
          String(pr.id).includes(q)
      );
    }

    result.sort((a, b) => {
      switch (sort) {
        case "additions":
          return b.additions - a.additions;
        case "deletions":
          return b.deletions - a.deletions;
        case "files":
          return b.changed_files - a.changed_files;
        default:
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      }
    });

    return result;
  }, [prs, search, sort, filter]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">Engineering work</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">
            Pull request workspace
          </h1>
          <p className="mt-2 text-sm text-muted-foreground sm:text-base">
            Synchronized GitHub state, deterministic evidence, and policy decisions.
          </p>
        </div>
        <Badge variant="outline" className="w-fit border-border bg-card px-3 py-1.5 text-muted-foreground">
          {filtered.length} of {prs.length} PRs
        </Badge>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#94A3B8]" />
          <Input
            placeholder="Search by title, author, repo, or ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-11 rounded-xl border-border bg-card pl-9 text-foreground placeholder:text-muted-foreground"
          />
        </div>
        <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
          <SelectTrigger className="h-11 w-full rounded-xl border-border bg-card sm:w-44">
            <SelectValue placeholder="Sort by" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="date">Newest first</SelectItem>
            <SelectItem value="additions">Most additions</SelectItem>
            <SelectItem value="deletions">Most deletions</SelectItem>
            <SelectItem value="files">Most files</SelectItem>
          </SelectContent>
        </Select>
        <Select value={filter} onValueChange={(v) => setFilter(v as FilterState)}>
          <SelectTrigger className="h-11 w-full rounded-xl border-border bg-card sm:w-36">
            <SelectValue placeholder="Filter" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All states</SelectItem>
            <SelectItem value="draft">Draft</SelectItem>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="closed">Closed</SelectItem>
            <SelectItem value="merged">Merged</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="surface overflow-hidden">
        <div className="hidden grid-cols-[72px_1fr_180px_140px_72px_72px_72px] gap-3 border-b border-border bg-muted/45 px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground md:grid">
          <span>ID</span>
          <span>Title</span>
          <span>Repository</span>
          <span>Author</span>
          <span>Files</span>
          <span className="text-emerald-600">+</span>
          <span className="text-red-600">−</span>
        </div>

        <div className="divide-y divide-border">
          {filtered.map((pr) => (
            <Link
              key={pr.id}
              href={`/pull-requests/${pr.id}`}
              className="group grid grid-cols-1 gap-2 px-5 py-4 transition-colors hover:bg-accent/35 md:grid-cols-[72px_1fr_180px_140px_72px_72px_72px] md:items-center md:gap-3"
            >
              <span className="font-mono text-sm text-muted-foreground group-hover:text-primary">
                #{pr.id}
              </span>
              <div className="flex min-w-0 items-center gap-2">
                <GitPullRequest className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary" />
                <span className="truncate font-semibold text-foreground">{pr.title}</span>
                <Badge
                  variant="outline"
                  className={lifecycleBadgeClasses[pr.state]}
                >
                  {pr.state}
                </Badge>
              </div>
              <span className="truncate text-sm text-muted-foreground">{getRepoLabel(pr)}</span>
              <div className="flex items-center gap-2">
                <Avatar className="h-6 w-6">
                  {pr.author.avatar_url && (
                    <AvatarImage src={pr.author.avatar_url} alt={pr.author.username} />
                  )}
                  <AvatarFallback className="bg-primary/10 text-xs text-primary">
                    {pr.author.username.slice(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                <span className="truncate text-sm text-foreground">{pr.author.username}</span>
              </div>
              <span className="text-sm text-muted-foreground">{pr.changed_files}</span>
              <span className="flex items-center gap-1 text-sm font-medium text-emerald-600">
                <Plus className="h-3 w-3" />
                {pr.additions}
              </span>
              <span className="flex items-center gap-1 text-sm font-medium text-red-600">
                <Minus className="h-3 w-3" />
                {pr.deletions}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
