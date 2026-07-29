"use client";

import { cn } from "@/lib/utils";
import type { PRFile } from "@/lib/types";

interface DiffViewerProps {
  filename: string;
  patch: string | null;
  patchStatus: PRFile["patch_status"];
}

const missingPatchMessages: Record<Exclude<PRFile["patch_status"], "available">, string> = {
  binary: "This is a binary file, so a textual patch is unavailable.",
  too_large: "The patch is too large for GitHub’s pull-request files response.",
  not_returned: "GitHub did not return patch content for this file.",
};

function getLineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) {
    return "text-zinc-500 bg-zinc-900/50";
  }
  if (line.startsWith("@@")) {
    return "text-blue-400 bg-blue-500/10 font-semibold";
  }
  if (line.startsWith("+")) {
    return "text-emerald-300 bg-emerald-500/10";
  }
  if (line.startsWith("-")) {
    return "text-red-300 bg-red-500/10";
  }
  return "text-zinc-400";
}

export function DiffViewer({ filename, patch, patchStatus }: DiffViewerProps) {
  if (!patch) {
    const message =
      patchStatus === "available"
        ? missingPatchMessages.not_returned
        : missingPatchMessages[patchStatus];
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-zinc-800/60 bg-[#0d1117] p-8 text-sm text-zinc-500">
        {message}
      </div>
    );
  }

  const lines = patch.split("\n");

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-zinc-800/60 bg-[#0d1117]">
      <div className="flex items-center gap-2 border-b border-zinc-800/80 bg-zinc-900/80 px-4 py-2.5">
        <span className="text-xs font-medium text-zinc-400">Diff</span>
        <span className="text-sm font-mono text-zinc-200">{filename}</span>
      </div>
      <div className="flex-1 overflow-auto p-4">
        <pre className="font-mono text-[13px] leading-6">
          {lines.map((line, index) => (
            <div
              key={index}
              className={cn("whitespace-pre-wrap break-all px-3 py-0.5", getLineClass(line))}
            >
              {line || " "}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
