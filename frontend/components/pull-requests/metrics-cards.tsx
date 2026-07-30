"use client";

import type { PRMetrics } from "@/lib/types";
import { formatNumber } from "@/services/api";
import { BookOpen, FileCode2, Minus, Plus, TestTube2 } from "lucide-react";

interface MetricsCardsProps {
  metrics: PRMetrics;
}

export function MetricsCards({ metrics }: MetricsCardsProps) {
  const items = [
    { label: "Total Files", value: metrics.total_files, icon: FileCode2, color: "text-[#2563EB]" },
    { label: "Additions", value: metrics.total_additions, icon: Plus, color: "text-emerald-600" },
    { label: "Deletions", value: metrics.total_deletions, icon: Minus, color: "text-red-600" },
    { label: "Has Tests", value: metrics.has_tests ? "Yes" : "No", icon: TestTube2, color: metrics.has_tests ? "text-emerald-600" : "text-[#94A3B8]" },
    { label: "Has Docs", value: metrics.has_docs ? "Yes" : "No", icon: BookOpen, color: metrics.has_docs ? "text-emerald-600" : "text-[#94A3B8]" },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {items.map(({ label, value, icon: Icon, color }) => (
        <div
          key={label}
          className="rounded-lg bg-white p-3.5 shadow-[0_1px_3px_rgba(0,0,0,0.05)]"
        >
          <div className="flex items-center gap-2">
            <Icon className={`h-4 w-4 ${color}`} />
            <span className="text-xs font-medium text-[#64748B]">{label}</span>
          </div>
          <p className="mt-1.5 text-xl font-bold text-[#0F172A]">
            {typeof value === "number" ? formatNumber(value) : value}
          </p>
        </div>
      ))}
    </div>
  );
}
