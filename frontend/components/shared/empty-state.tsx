import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[#E2E8F0] bg-white px-6 py-12 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[#F1F5F9]">
        <Icon className="h-6 w-6 text-[#64748B]" />
      </div>
      <h3 className="text-base font-semibold text-[#0F172A]">{title}</h3>
      <p className="mt-1.5 max-w-md text-sm text-[#64748B]">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
