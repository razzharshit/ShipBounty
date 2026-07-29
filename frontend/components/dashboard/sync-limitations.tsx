import Link from "next/link";
import { AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PullRequest } from "@/lib/types";


interface SyncLimitationsProps {
  prs: PullRequest[];
}

function reasonLabel(reason: string | null) {
  if (reason === "GITHUB_FILE_LIMIT") {
    return "GitHub’s 3,000-file API limit was reached";
  }
  return reason?.replaceAll("_", " ").toLowerCase() ?? "File synchronization is incomplete";
}

export function SyncLimitations({ prs }: SyncLimitationsProps) {
  const incompletePrs = prs.filter((pr) => !pr.file_sync_complete);
  if (incompletePrs.length === 0) {
    return null;
  }

  return (
    <Card className="border-amber-200 bg-amber-50/60 shadow-none">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-amber-900">
          <AlertTriangle className="h-4 w-4" />
          Synchronization limitations
          <Badge variant="outline" className="border-amber-300 bg-white text-amber-800">
            {incompletePrs.length}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {incompletePrs.map((pr) => (
          <div
            key={pr.id}
            className="flex flex-col gap-1 rounded-md border border-amber-200 bg-white/80 px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
          >
            <Link
              href={`/pull-requests/${pr.id}`}
              className="text-sm font-medium text-amber-950 hover:underline"
            >
              {pr.title}
            </Link>
            <span className="text-xs text-amber-800">
              {reasonLabel(pr.incomplete_reason)}; authoritative scoring is disabled.
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
