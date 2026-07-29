import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BarChart3,
  FileDown,
  GitPullRequest,
  Save,
  Webhook,
} from "lucide-react";

const steps = [
  { label: "PR Created", icon: GitPullRequest },
  { label: "Webhook Triggered", icon: Webhook },
  { label: "Files Retrieved", icon: FileDown },
  { label: "Patch Stored", icon: Save },
  { label: "Metrics Generated", icon: BarChart3 },
];

export function ActivityTimeline() {
  return (
    <Card className="border-[#E2E8F0] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
      <CardHeader className="pb-2 pt-4 px-4">
        <CardTitle className="text-sm font-semibold text-[#0F172A]">Activity Pipeline</CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4">
        <div className="relative">
          {steps.map((step, index) => (
            <div key={step.label} className="relative flex gap-3 pb-5 last:pb-0">
              {index < steps.length - 1 && (
                <div className="absolute left-[15px] top-8 h-[calc(100%-1.25rem)] w-px bg-[#CBD5E1]" />
              )}
              <div className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#2563EB]">
                <step.icon className="h-3.5 w-3.5 text-white" />
              </div>
              <div className="pt-0.5">
                <p className="text-sm font-medium text-[#0F172A]">{step.label}</p>
                <p className="text-xs text-[#64748B]">Automated on each PR event</p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
