"use client";

import { useState } from "react";
import type { PRFile } from "@/lib/types";
import { AIReadinessCard } from "@/components/patches/ai-readiness-card";
import { DiffViewer } from "@/components/patches/diff-viewer";
import { FileSidebar } from "@/components/patches/file-sidebar";

interface PatchViewerClientProps {
  files: PRFile[];
  hasMetrics: boolean;
}

export function PatchViewerClient({ files, hasMetrics }: PatchViewerClientProps) {
  const [selectedFilename, setSelectedFilename] = useState<string>(files[0]?.filename ?? "");

  const selectedFile = files.find((f) => f.filename === selectedFilename) ?? files[0];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-bold text-[#0F172A]">Patch Viewer</h2>
        <p className="mt-0.5 text-sm text-[#64748B]">
          GitHub-style diff review — the foundation for AI-powered code evaluation
        </p>
      </div>

      <div className="grid h-[520px] gap-3 lg:grid-cols-[240px_1fr]">
        <FileSidebar
          files={files}
          selectedFilename={selectedFile?.filename ?? null}
          onSelect={setSelectedFilename}
        />
        {selectedFile && (
          <DiffViewer
            filename={selectedFile.filename}
            patch={selectedFile.patch}
            patchStatus={selectedFile.patch_status}
          />
        )}
      </div>

      <AIReadinessCard
        hasMetrics={hasMetrics}
        hasPatches={files.some((file) => file.patch_available)}
      />
    </div>
  );
}
