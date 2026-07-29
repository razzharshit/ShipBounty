import { notFound, redirect } from "next/navigation";

import {
  OrganizationSelector,
  RememberOrganization,
} from "@/components/dashboard/organization-selector";
import { ProductAnalyticsDashboard } from "@/components/dashboard/product-analytics-dashboard";
import { AppShell } from "@/components/layout/app-shell";
import {
  getNotifications,
  getOrganizations,
  getProductAnalytics,
  isAuthenticationError,
} from "@/services/api-server";

export default async function OrganizationProductPage({
  params,
}: {
  params: Promise<{ organizationSlug: string }>;
}) {
  const { organizationSlug } = await params;
  let organizations: Awaited<ReturnType<typeof getOrganizations>>;
  try {
    organizations = await getOrganizations();
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    throw error;
  }
  const organization = organizations.find(
    (item) => item.login === decodeURIComponent(organizationSlug),
  );
  if (!organization) notFound();

  let data: Awaited<ReturnType<typeof getProductAnalytics>>;
  let notifications: Awaited<ReturnType<typeof getNotifications>>;
  try {
    [data, notifications] = await Promise.all([
      getProductAnalytics(organization.id),
      getNotifications(organization.id),
    ]);
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    throw error;
  }
  return (
    <AppShell>
      <div className="space-y-5">
        <RememberOrganization slug={organization.login} />
        <div className="flex justify-end">
          <OrganizationSelector
            organizations={organizations}
            currentSlug={organization.login}
            section="product"
          />
        </div>
        <ProductAnalyticsDashboard
          data={data}
          notifications={notifications}
        />
      </div>
    </AppShell>
  );
}
