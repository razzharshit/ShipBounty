import { AppShell } from "@/components/layout/app-shell";
import { PRExplorer } from "@/components/pull-requests/pr-explorer";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { getPullRequests, isAuthenticationError } from "@/services/api-server";
import { GitPullRequest } from "lucide-react";
import { redirect } from "next/navigation";

export default async function PullRequestsPage() {
  let prs;
  try {
    prs = await getPullRequests();
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    return (
      <AppShell>
        <ErrorState
          title="Unable to reach backend"
          description="Make sure the API is running at http://localhost:8000 and CORS is enabled."
        />
      </AppShell>
    );
  }

  if (prs.length === 0) {
    return (
      <AppShell>
        <EmptyState
          icon={GitPullRequest}
          title="No pull requests ingested"
          description="Pull requests will appear here after GitHub webhook events are processed."
        />
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PRExplorer prs={prs} />
    </AppShell>
  );
}
