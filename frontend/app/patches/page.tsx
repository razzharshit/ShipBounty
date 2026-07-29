import { redirect } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { getPullRequests, isAuthenticationError } from "@/services/api-server";
import { FileDiff } from "lucide-react";

export default async function PatchesLandingPage() {
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

  if (prs.length === 0) {
    return (
      <AppShell>
        <EmptyState
          icon={FileDiff}
          title="No patches available"
          description="Ingest a pull request first, then return here to view stored patches."
        />
      </AppShell>
    );
  }

  redirect(`/pull-requests/${prs[0].id}/patches`);
}
