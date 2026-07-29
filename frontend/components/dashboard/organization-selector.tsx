"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import type { Organization } from "@/lib/types";

const STORAGE_KEY = "gbd:last-organization";

export function OrganizationSelector({
  organizations,
  currentSlug,
  section,
}: {
  organizations: Organization[];
  currentSlug: string;
  section: "operations" | "product";
}) {
  const router = useRouter();

  return (
    <label className="flex items-center gap-2 text-xs font-medium text-slate-600">
      Organization
      <select
        value={currentSlug}
        onChange={(event) => {
          const slug = event.target.value;
          localStorage.setItem(STORAGE_KEY, slug);
          router.push(`/dashboard/${encodeURIComponent(slug)}/${section}`);
        }}
        className="h-9 min-w-48 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-900"
      >
        {organizations.map((organization) => (
          <option key={organization.id} value={organization.login}>
            {organization.display_name || organization.login}
          </option>
        ))}
      </select>
    </label>
  );
}

export function RememberOrganization({ slug }: { slug: string }) {
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, slug);
  }, [slug]);
  return null;
}

export function OrganizationLanding({
  organizations,
}: {
  organizations: Organization[];
}) {
  const router = useRouter();
  useEffect(() => {
    const remembered = localStorage.getItem(STORAGE_KEY);
    const selected =
      organizations.find((item) => item.login === remembered) ??
      organizations[0];
    if (selected) {
      router.replace(
        `/dashboard/${encodeURIComponent(selected.login)}/product`,
      );
    }
  }, [organizations, router]);
  return null;
}
