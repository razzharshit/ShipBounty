import { notFound, redirect } from "next/navigation";
import {
  BookOpenCheck,
  Building2,
  GitBranch,
  LockKeyhole,
  ScrollText,
  Users,
} from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";
import {
  EmptyTable,
  PageHeader,
  StatusPill,
} from "@/components/workspace/page-header";
import {
  getAuditLogs,
  getOrganizationMembers,
  getOrganizations,
  getRepositories,
  getRepositoryPolicies,
  isAuthenticationError,
} from "@/services/api-server";
import { formatDate } from "@/services/api";

export default async function OrganizationPage({
  params,
}: {
  params: Promise<{ organizationSlug: string }>;
}) {
  const { organizationSlug } = await params;
  let organizations;
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
  const repositories = await getRepositories(organization.id);
  const canAdminister = ["owner", "admin"].includes(organization.role);
  const [auditLogs, members] = canAdminister
    ? await Promise.all([
        getAuditLogs(organization.id),
        getOrganizationMembers(organization.id),
      ])
    : [[], []];
  const primaryRepository = repositories[0] ?? null;
  const policies = primaryRepository
    ? await getRepositoryPolicies(primaryRepository.id)
    : null;

  return (
    <AppShell>
      <div className="space-y-7">
        <PageHeader
          eyebrow="Tenant administration"
          title={organization.display_name ?? organization.login}
          description="Repository access, policy ownership, verified roles, and audit history stay scoped to this organization."
          icon={Building2}
          actions={
            <span className="inline-flex h-11 items-center gap-2 rounded-xl border border-border bg-card px-4 text-sm font-semibold shadow-sm">
              <LockKeyhole className="h-4 w-4 text-emerald-600" />
              {organization.role}
            </span>
          }
        />
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            {
              label: "Repositories",
              value: repositories.length,
              detail: "Accessible in this tenant",
              icon: GitBranch,
            },
            {
              label: "Verified identity",
              value: canAdminister ? members.length : "Restricted",
              detail: canAdminister
                ? "Organization members"
                : "Member list requires admin access",
              icon: Users,
            },
            {
              label: "Audit events",
              value: auditLogs.length,
              detail: ["owner", "admin"].includes(organization.role)
                ? "Latest 250 events"
                : "Admin access required",
              icon: ScrollText,
            },
          ].map(({ label, value, detail, icon: Icon }) => (
            <div key={label} className="surface p-5">
              <div className="flex items-start justify-between">
                <p className="text-sm font-medium text-muted-foreground">{label}</p>
                <span className="rounded-xl bg-primary/10 p-2 text-primary">
                  <Icon className="h-4 w-4" />
                </span>
              </div>
              <p className="mt-3 text-3xl font-semibold capitalize tracking-tight">
                {value}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
            </div>
          ))}
        </div>
        <section className="surface overflow-hidden">
          <div className="border-b border-border px-5 py-4">
            <h2 className="font-semibold">Members and authorization</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Verified organization roles are independent from repository-level
              grants.
            </p>
          </div>
          {members.length === 0 ? (
            <EmptyTable
              title={
                canAdminister
                  ? "No active members found"
                  : "Administrator access required"
              }
              description="Organization membership and role details are restricted to owners and administrators."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <caption className="sr-only">
                  Organization members and verified roles
                </caption>
                <thead>
                  <tr>
                    <th>Member</th>
                    <th>Role</th>
                    <th>GitHub verification</th>
                    <th>Access</th>
                    <th>Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((member) => (
                    <tr key={member.membership_id}>
                      <td>
                        <p className="font-semibold">
                          {member.display_name || member.username}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          @{member.username}
                        </p>
                      </td>
                      <td>
                        <StatusPill status={member.role} />
                      </td>
                      <td>
                        {member.github_verified ? "Verified" : "Not verified"}
                      </td>
                      <td>{member.is_active ? "Active" : "Inactive"}</td>
                      <td className="text-muted-foreground">
                        {formatDate(member.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="surface overflow-hidden">
          <div className="border-b border-border px-5 py-4">
            <h2 className="font-semibold">Repository policy baseline</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Current immutable policy versions for{" "}
              {primaryRepository?.full_name ?? "the selected repository"}.
            </p>
          </div>
          {!policies ? (
            <EmptyTable
              title="No repository policy baseline"
              description="Connect a repository to initialize scoring, eligibility, bounty, and advisory AI policies."
            />
          ) : (
            <div className="grid gap-4 p-5 sm:grid-cols-2 xl:grid-cols-4">
              {Object.entries(policies).map(([domain, policy]) => (
                <article
                  key={domain}
                  className="rounded-xl border border-border p-4"
                >
                  <p className="text-xs font-bold uppercase tracking-wide text-primary">
                    {domain}
                  </p>
                  <h3 className="mt-2 font-semibold">{policy.name}</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Version {policy.version}
                  </p>
                  <p className="mt-3 truncate font-mono text-xs text-muted-foreground">
                    {policy.policy_hash}
                  </p>
                </article>
              ))}
            </div>
          )}
        </section>
        <div className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
          <section className="surface overflow-hidden">
            <div className="border-b border-border px-5 py-4">
              <h2 className="font-semibold">Repositories and policy scope</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Every business entity traces back to one of these repositories.
              </p>
            </div>
            {repositories.length === 0 ? (
              <EmptyTable
                title="No accessible repositories"
                description="Install the GitHub App or request a repository-scoped role."
              />
            ) : (
              <div className="divide-y divide-border">
                {repositories.map((repository) => (
                  <div
                    key={repository.id}
                    className="flex items-center gap-4 px-5 py-4"
                  >
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      <GitBranch className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-semibold">
                        {repository.full_name}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {repository.is_private ? "Private" : "Public"} · GitHub ID{" "}
                        {repository.github_repo_id}
                      </p>
                    </div>
                    <StatusPill status={repository.role} />
                  </div>
                ))}
              </div>
            )}
          </section>
          <section className="surface overflow-hidden">
            <div className="flex items-center gap-3 border-b border-border px-5 py-4">
              <BookOpenCheck className="h-4 w-4 text-primary" />
              <div>
                <h2 className="font-semibold">Audit activity</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Immutable operator and domain actions.
                </p>
              </div>
            </div>
            {auditLogs.length === 0 ? (
              <EmptyTable
                title={
                  ["owner", "admin"].includes(organization.role)
                    ? "No audit events yet"
                    : "Administrator access required"
                }
                description="Audit visibility is deliberately restricted to organization owners and administrators."
              />
            ) : (
              <div className="max-h-[560px] divide-y divide-border overflow-y-auto">
                {auditLogs.slice(0, 40).map((event) => (
                  <div key={event.id} className="px-5 py-4">
                    <div className="flex items-start justify-between gap-4">
                      <p className="text-sm font-semibold">
                        {event.action.replaceAll(".", " · ")}
                      </p>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatDate(event.created_at)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {event.resource_type}
                      {event.resource_id ? ` #${event.resource_id}` : ""}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  );
}
