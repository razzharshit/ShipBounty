"use client";

import type { PRFile } from "@/lib/types";
import { cn } from "@/lib/utils";
import { FileCode2, Minus, Plus } from "lucide-react";

interface FileSidebarProps {
  files: PRFile[];
  selectedFilename: string | null;
  onSelect: (filename: string) => void;
}

export function FileSidebar({ files, selectedFilename, onSelect }: FileSidebarProps) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-[#E2E8F0] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
      <div className="border-b border-[#E2E8F0] px-3 py-2.5">
        <p className="text-sm font-semibold text-[#0F172A]">Changed Files</p>
        <p className="text-xs text-[#64748B]">{files.length} file{files.length !== 1 ? "s" : ""}</p>
      </div>
      <div className="flex-1 overflow-y-auto">
        {files.map((file) => (
          <button
            key={file.id}
            type="button"
            onClick={() => onSelect(file.filename)}
            className={cn(
              "flex w-full items-start gap-2.5 border-b border-[#E2E8F0] px-3 py-2.5 text-left transition-colors",
              selectedFilename === file.filename
                ? "bg-[#EFF6FF]"
                : "hover:bg-[#F8FAFC]"
            )}
          >
            <FileCode2 className="mt-0.5 h-4 w-4 shrink-0 text-[#64748B]" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-[#0F172A]">{file.filename}</p>
              <div className="mt-0.5 flex items-center gap-2 text-xs">
                <span className="flex items-center gap-0.5 text-emerald-600">
                  <Plus className="h-3 w-3" />
                  {file.additions}
                </span>
                <span className="flex items-center gap-0.5 text-red-600">
                  <Minus className="h-3 w-3" />
                  {file.deletions}
                </span>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
