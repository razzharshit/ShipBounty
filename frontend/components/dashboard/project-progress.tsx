import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const phases = [
  { name: "GitHub App Integration", status: "Complete" as const },
  { name: "Webhook Processing", status: "Complete" as const },
  { name: "Patch Extraction", status: "Complete" as const },
  { name: "Metrics Engine", status: "Complete" as const },
  { name: "AI Scoring", status: "In Progress" as const },
  { name: "Fraud Detection", status: "Planned" as const },
  { name: "Smart Contract Rewards", status: "Planned" as const },
];

const badgeStyles = {
  Complete: "border-transparent bg-[#E8F5E9] text-[#2E7D32]",
  "In Progress": "border-transparent bg-[#FFF3E0] text-[#E65100]",
  Planned: "border-transparent bg-[#F1F5F9] text-[#475569]",
};

export function ProjectProgress() {
  return (
    <Card className="border-[#E2E8F0] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
      <CardHeader className="pb-2 pt-4 px-4">
        <CardTitle className="text-sm font-semibold text-[#0F172A]">Project Progress</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 px-4 pb-4">
        {phases.map((phase) => (
          <div
            key={phase.name}
            className="flex items-center justify-between rounded-md px-2 py-2 transition-colors hover:bg-slate-50"
          >
            <span className="text-sm text-[#0F172A]">{phase.name}</span>
            <Badge variant="outline" className={badgeStyles[phase.status]}>
              {phase.status}
            </Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
