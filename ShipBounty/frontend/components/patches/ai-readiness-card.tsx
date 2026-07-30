import { Card, CardContent } from "@/components/ui/card";
import { Brain, CheckCircle2, FileCode2 } from "lucide-react";

interface AIReadinessCardProps {
  hasMetrics: boolean;
  hasPatches: boolean;
}

export function AIReadinessCard({ hasMetrics, hasPatches }: AIReadinessCardProps) {
  const ready = hasMetrics && hasPatches;

  const items = [
    { label: "Patch Retrieved", done: hasPatches },
    { label: "Metrics Generated", done: hasMetrics },
    { label: "Ready For AI Evaluation", done: ready },
  ];

  return (
    <Card className="border-[#E2E8F0] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#EFF6FF]">
            <Brain className="h-5 w-5 text-[#2563EB]" />
          </div>
          <div className="flex-1">
            <h3 className="text-base font-semibold text-[#0F172A]">AI Analysis Readiness</h3>
            <p className="mt-1 text-sm text-[#64748B]">
              Future AI scoring will analyze these patches to evaluate code quality, relevance,
              complexity, and documentation coverage before bounty distribution.
            </p>
            <div className="mt-3 flex flex-wrap gap-4">
              {items.map(({ label, done }) => (
                <div key={label} className="flex items-center gap-2">
                  {done ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <FileCode2 className="h-4 w-4 text-[#CBD5E1]" />
                  )}
                  <span className={done ? "text-sm text-emerald-700" : "text-sm text-[#94A3B8]"}>
                    {label} {done && "✓"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
