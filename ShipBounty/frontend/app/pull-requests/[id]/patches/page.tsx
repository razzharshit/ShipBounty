import { PatchViewerClient } from "@/components/patches/patch-viewer-client";
import { AppShell } from "@/components/layout/app-shell";
import { PRDetailHeader } from "@/components/pull-requests/pr-detail-header";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import {
  getPRFiles,
  getPRMetrics,
  getPullRequests,
  isAuthenticationError,
} from "@/services/api-server";
import { FileDiff } from "lucide-react";
import { notFound, redirect } from "next/navigation";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PatchesPage({ params }: PageProps) {
  const { id } = await params;
  const prId = Number(id);

  if (Number.isNaN(prId)) notFound();

  let prs;
  try {
    prs = await getPullRequests();
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    return (
      <AppShell>
        <ErrorState
          title="Unable to reach backend"
          description="Make sure the API is running at http://localhost:8000."
        />
      </AppShell>
    );
  }

  const pr = prs.find((p) => p.id === prId);
  if (!pr) notFound();

  const [files, metrics] = await Promise.all([getPRFiles(prId), getPRMetrics(prId)]);

  return (
    <AppShell>
      <div className="space-y-4">
        <PRDetailHeader pr={pr} />

        {files.length === 0 ? (
          <EmptyState
            icon={FileDiff}
            title="No patch data stored"
            description="Patches are extracted when a PR webhook is processed. Ensure the GitHub App has fetched file diffs for this pull request."
          />
        ) : (
          <PatchViewerClient
            files={files}
            hasMetrics={metrics.status === "ready"}
          />
        )}
      </div>
    </AppShell>
  );
}
