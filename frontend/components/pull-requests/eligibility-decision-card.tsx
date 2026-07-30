import { CheckCircle, Clock3, ShieldCheck, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EligibilityDecision } from "@/lib/types";

interface EligibilityDecisionCardProps {
  decision: EligibilityDecision | null;
}

function label(value: string) {
  return value.replaceAll("_", " ");
}

export function EligibilityDecisionCard({
  decision,
}: EligibilityDecisionCardProps) {
  if (!decision) {
    return (
      <Card className="border-[#F1F5F9] bg-white">
        <CardContent className="flex items-center gap-3 p-4 text-sm text-[#64748B]">
          <Clock3 className="h-4 w-4" />
          No payout eligibility decision has been evaluated for this score.
        </CardContent>
      </Card>
    );
  }

  const approved = decision.approvals.filter(
    (approval) => approval.outcome === "approved",
  ).length;
  const complete = decision.status === "eligible";
  const failed = decision.status === "ineligible";

  return (
    <Card className="border-[#F1F5F9] bg-white">
      <CardHeader className="px-4 pb-2 pt-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <ShieldCheck className="h-4 w-4 text-[#2563EB]" />
          Review and approval decision
          <Badge
            className={
              complete
                ? "bg-emerald-50 text-emerald-700"
                : failed
                  ? "bg-red-50 text-red-700"
                  : "bg-amber-50 text-amber-700"
            }
          >
            {label(decision.status)}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 px-4 pb-4 text-xs sm:grid-cols-3">
        <div className="rounded-lg bg-[#F8FAFC] p-3">
          <span className="text-[#64748B]">Policy version</span>
          <p className="mt-1 font-mono font-semibold">
            {decision.evaluation_result.policy.version}
          </p>
        </div>
        <div className="rounded-lg bg-[#F8FAFC] p-3">
          <span className="text-[#64748B]">Human review</span>
          <p className="mt-1 flex items-center gap-1 font-semibold">
            {decision.reviews.some((review) => review.recommendation === "approve") ? (
              <CheckCircle className="h-3.5 w-3.5 text-emerald-600" />
            ) : (
              <Clock3 className="h-3.5 w-3.5 text-amber-600" />
            )}
            {decision.reviews.length} submitted
          </p>
        </div>
        <div className="rounded-lg bg-[#F8FAFC] p-3">
          <span className="text-[#64748B]">Approvals</span>
          <p className="mt-1 flex items-center gap-1 font-semibold">
            {failed ? (
              <XCircle className="h-3.5 w-3.5 text-red-600" />
            ) : (
              <CheckCircle className="h-3.5 w-3.5 text-emerald-600" />
            )}
            {approved}/{decision.required_approvals}
          </p>
        </div>
        <p className="break-all text-[10px] text-[#64748B] sm:col-span-3">
          Score version {decision.score_version_id} · decision hash{" "}
          {decision.evaluation_hash}
        </p>
      </CardContent>
    </Card>
  );
}
