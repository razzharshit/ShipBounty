import { AlertCircle, Award, CheckCircle, Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PullRequest, PRScore } from "@/lib/types";

interface ScoreBreakdownProps {
  score: PRScore;
  pr: PullRequest;
}

function labelForCategory(category: string) {
  return category
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function ScoreBreakdown({ score, pr }: ScoreBreakdownProps) {
  const finalScore = score.final_score;
  const radius = 45;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (finalScore / 100) * circumference;
  const categories = Object.entries(score.category_scores);

  return (
    <div className="grid gap-4 md:grid-cols-[280px_1fr]">
      <Card className="flex flex-col justify-between border-[#F1F5F9] bg-white shadow-[0_1px_3px_rgba(15,23,42,0.02)]">
        <CardHeader className="px-4 pb-0 pt-4">
          <CardTitle className="text-xs font-bold uppercase tracking-wider text-[#64748B]">
            Deterministic Score
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center justify-center space-y-4 p-4 text-center">
          <div className="relative flex h-28 w-28 items-center justify-center">
            <svg className="h-full w-full -rotate-90" aria-label={`Score ${finalScore} out of 100`}>
              <circle cx="56" cy="56" r={radius} className="stroke-slate-100" strokeWidth="8" fill="transparent" />
              <circle
                cx="56"
                cy="56"
                r={radius}
                className="animate-draw-ring stroke-[#2563EB]"
                strokeWidth="8"
                fill="transparent"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
              />
            </svg>
            <div className="absolute flex flex-col items-center">
              <span className="text-2xl font-black leading-none text-[#0F172A]">{finalScore}</span>
              <span className="mt-0.5 text-[9px] font-bold uppercase tracking-wider text-[#94A3B8]">out of 100</span>
            </div>
          </div>

          <div className="flex flex-wrap justify-center gap-2">
            <Badge className={score.is_authoritative ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}>
              {score.is_authoritative ? "Authoritative" : "Provisional"}
            </Badge>
            <Badge variant="outline">{Math.round(score.confidence * 100)}% confidence</Badge>
          </div>

          <div className="w-full rounded-lg border border-[#F1F5F9] bg-[#F8FAFC] p-3">
            <span className="block text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">
              Payout decision
            </span>
            <p className="mt-1 text-sm font-bold text-[#0F172A]">
              {labelForCategory(pr.eligibility_state)}
            </p>
            <p className="mt-1 text-[10px] leading-4 text-[#64748B]">
              A score is evidence only. Policy evaluation, human review, and an authorized approval are required before eligibility.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card className="border-[#F1F5F9] bg-white shadow-[0_1px_3px_rgba(15,23,42,0.02)]">
        <CardHeader className="px-5 pb-2 pt-4">
          <CardTitle className="flex items-center gap-2 text-xs font-bold text-[#0F172A]">
            <Award className="h-4 w-4 text-[#2563EB]" />
            Versioned analysis
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5 px-5 pb-5 pt-0">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {categories.map(([category, value]) => (
              <div key={category} className="space-y-1.5 rounded-lg border border-[#F1F5F9] bg-[#F8FAFC] p-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-[#0F172A]">{labelForCategory(category)}</span>
                  <span className="font-bold text-[#64748B]">{value}/100</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200/60">
                  <div className="h-full rounded-full bg-blue-600" style={{ width: `${value}%` }} />
                </div>
                <span className="block text-[9px] font-medium text-[#94A3B8]">
                  {Math.round((score.category_confidence[category] ?? 0) * 100)}% confidence
                </span>
              </div>
            ))}
          </div>

          {score.unavailable_categories.length > 0 && (
            <div className="flex gap-2 rounded-lg border border-amber-100 bg-amber-50 p-3 text-xs text-amber-800">
              <AlertCircle className="h-4 w-4 shrink-0" />
              Unavailable analyzers were excluded, not scored as zero: {score.unavailable_categories.map(labelForCategory).join(", ")}.
            </div>
          )}

          <div className="space-y-2">
            <h4 className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-[#94A3B8]">
              <Info className="h-3.5 w-3.5" />
              Reproducibility
            </h4>
            <div className="space-y-2 rounded-lg border border-[#F1F5F9] p-3 text-xs text-[#475569]">
              <div className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-emerald-500" />
                Policy: <code>{score.scoring_policy_version}</code>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-emerald-500" />
                Analyzer suite: <code>{score.analyzer_suite_version}</code>
              </div>
              <p className="break-all text-[10px] text-[#64748B]">Result hash: {score.deterministic_hash}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
