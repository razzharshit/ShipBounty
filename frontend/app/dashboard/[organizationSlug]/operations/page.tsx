import { notFound, redirect } from "next/navigation";

import {
  OrganizationSelector,
  RememberOrganization,
} from "@/components/dashboard/organization-selector";
import { OperationsDashboard } from "@/components/dashboard/operations-dashboard";
import { AppShell } from "@/components/layout/app-shell";
import { ErrorState } from "@/components/shared/error-state";
import {
  getOperationsDashboard,
  getOrganizations,
  isAuthenticationError,
} from "@/services/api-server";

export default async function OrganizationOperationsPage({
  params,
}: {
  params: Promise<{ organizationSlug: string }>;
}) {
  const { organizationSlug } = await params;
  let organizations: Awaited<ReturnType<typeof getOrganizations>>;
  try {
    organizations = (await getOrganizations()).filter((item) =>
      ["owner", "admin"].includes(item.role),
    );
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    return (
      <AppShell>
        <ErrorState
          title="Operations dashboard unavailable"
          description="Administrator access is required for this organization."
        />
      </AppShell>
    );
  }
  const organization = organizations.find(
    (item) => item.login === decodeURIComponent(organizationSlug),
  );
  if (!organization) notFound();

  let data: Awaited<ReturnType<typeof getOperationsDashboard>>;
  try {
    data = await getOperationsDashboard(organization.id);
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    return (
      <AppShell>
        <ErrorState
          title="Operations dashboard unavailable"
          description="Administrator access is required for this organization."
        />
      </AppShell>
    );
  }
  return (
    <AppShell>
      <div className="space-y-5">
        <RememberOrganization slug={organization.login} />
        <div className="flex justify-end">
          <OrganizationSelector
            organizations={organizations}
            currentSlug={organization.login}
            section="operations"
          />
        </div>
        <OperationsDashboard data={data} />
      </div>
    </AppShell>
  );
}
