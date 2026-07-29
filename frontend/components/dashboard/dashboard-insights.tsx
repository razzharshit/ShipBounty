"use client";

import { useMemo } from "react";
import type { PullRequest } from "@/lib/types";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getRepoLabel } from "@/services/api";
import { GitFork, Trophy, Users } from "lucide-react";

interface DashboardInsightsProps {
  prs: PullRequest[];
}

export function DashboardInsights({ prs }: DashboardInsightsProps) {
  // 1. Group by contributor and calculate metrics
  const contributors = useMemo(() => {
    const groups: Record<
      string,
      {
        username: string;
        avatarUrl: string | null;
        totalPrs: number;
        mergedPrs: number;
        avgScore: number;
        paidClaims: number;
      }
    > = {};

    prs.forEach((pr) => {
      const username = pr.author.username;
      if (!groups[username]) {
        groups[username] = {
          username,
          avatarUrl: pr.author.avatar_url,
          totalPrs: 0,
          mergedPrs: 0,
          avgScore: 0.0, // default fallback base score
          paidClaims: 0,
        };
      }

      groups[username].totalPrs += 1;
      if (pr.state === "merged") {
        groups[username].mergedPrs += 1;
      }
      if (pr.eligibility_state === "paid") {
        groups[username].paidClaims += 1;
      }
    });

    return Object.values(groups).sort((a, b) => b.paidClaims - a.paidClaims);
  }, [prs]);

  // 2. Group by repository
  const repositories = useMemo(() => {
    const groups: Record<
      string,
      {
        fullName: string;
        owner: string;
        name: string;
        prCount: number;
      }
    > = {};

    prs.forEach((pr) => {
      const fullName = getRepoLabel(pr);
      if (!groups[fullName]) {
        groups[fullName] = {
          fullName,
          owner: pr.repository.owner,
          name: pr.repository.name,
          prCount: 0,
        };
      }
      groups[fullName].prCount += 1;
    });

    return Object.values(groups).sort((a, b) => b.prCount - a.prCount);
  }, [prs]);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Developer Leaderboard */}
      <Card className="border-[#F1F5F9] bg-white shadow-[0_1px_3px_rgba(15,23,42,0.02)]">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3 pt-5 px-5">
          <CardTitle className="flex items-center gap-2 text-sm font-bold text-[#0F172A]">
            <Trophy className="h-4 w-4 text-amber-500" />
            Top Contributors
          </CardTitle>
          <Badge variant="outline" className="border-[#E2E8F0] bg-[#F8FAFC] text-[10px] text-[#64748B]">
            By paid claims
          </Badge>
        </CardHeader>
        <CardContent className="px-5 pb-5 pt-0">
          {contributors.length === 0 ? (
            <div className="flex h-36 flex-col items-center justify-center text-center">
              <Users className="h-8 w-8 text-[#94A3B8]" />
              <p className="mt-1 text-xs font-semibold text-[#64748B]">No contributors yet</p>
            </div>
          ) : (
            <div className="divide-y divide-[#F1F5F9]">
              {contributors.slice(0, 5).map((user, idx) => (
                <div key={user.username} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
                  <div className="flex items-center gap-3">
                    <span className="w-5 text-center text-xs font-bold text-[#94A3B8]">
                      #{idx + 1}
                    </span>
                    <Avatar className="h-8 w-8 border border-slate-100">
                      {user.avatarUrl && (
                        <AvatarImage src={user.avatarUrl} alt={user.username} />
                      )}
                      <AvatarFallback className="bg-gradient-to-br from-blue-50 to-indigo-50 text-xs font-semibold text-[#2563EB]">
                        {user.username.slice(0, 2).toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                    <div>
                      <p className="text-xs font-semibold text-[#0F172A]">{user.username}</p>
                      <p className="text-[10px] text-[#64748B]">
                        {user.totalPrs} PR{user.totalPrs > 1 ? "s" : ""} · {user.mergedPrs} merged
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-xs font-bold text-emerald-600">{user.paidClaims}</p>
                    <p className="text-[9px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                      Claims Paid
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Connected Repositories */}
      <Card className="border-[#F1F5F9] bg-white shadow-[0_1px_3px_rgba(15,23,42,0.02)]">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3 pt-5 px-5">
          <CardTitle className="flex items-center gap-2 text-sm font-bold text-[#0F172A]">
            <GitFork className="h-4 w-4 text-blue-600" />
            Connected Repositories
          </CardTitle>
          <Badge variant="outline" className="border-green-100 bg-green-50/50 text-[10px] text-green-700 font-semibold">
            Webhooks Active
          </Badge>
        </CardHeader>
        <CardContent className="px-5 pb-5 pt-0">
          {repositories.length === 0 ? (
            <div className="flex h-36 flex-col items-center justify-center text-center">
              <GitFork className="h-8 w-8 text-[#94A3B8]" />
              <p className="mt-1 text-xs font-semibold text-[#64748B]">No connected repos yet</p>
            </div>
          ) : (
            <div className="divide-y divide-[#F1F5F9]">
              {repositories.map((repo) => (
                <div key={repo.fullName} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
                  <div>
                    <h4 className="text-xs font-semibold text-[#0F172A]">
                      {repo.name}
                    </h4>
                    <p className="text-[10px] text-[#64748B]">{repo.owner}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant="outline" className="border-[#E2E8F0] bg-white text-[10px] text-[#64748B]">
                      {repo.prCount} PR{repo.prCount > 1 ? "s" : ""}
                    </Badge>
                    <span className="flex h-2 w-2 rounded-full bg-emerald-500" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
