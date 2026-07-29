import { redirect } from "next/navigation";
import { OrganizationLanding } from "@/components/dashboard/organization-selector";
import { getOrganizations, isAuthenticationError } from "@/services/api-server";

export default async function DashboardPage() {
  let organizations;
  try {
    organizations = await getOrganizations();
  } catch (error) {
    if (isAuthenticationError(error)) redirect("/login");
    throw error;
  }
  if (organizations.length === 0) redirect("/pull-requests");
  return <OrganizationLanding organizations={organizations} />;
}

