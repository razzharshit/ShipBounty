"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";

const STORAGE_KEY = "gbd:last-organization";

function slugFromPath(pathname: string): string | null {
  const parts = pathname.split("/");
  return parts[1] === "dashboard" && parts.length >= 3 && parts[2]
    ? decodeURIComponent(parts[2])
    : null;
}

export function useOrganizationContext() {
  const pathname = usePathname();
  const pathSlug = slugFromPath(pathname);
  const [rememberedSlug, setRememberedSlug] = useState<string | null>(pathSlug);

  useEffect(() => {
    if (pathSlug) {
      window.localStorage.setItem(STORAGE_KEY, pathSlug);
      queueMicrotask(() => setRememberedSlug(pathSlug));
      return;
    }
    const stored = window.localStorage.getItem(STORAGE_KEY);
    queueMicrotask(() => setRememberedSlug(stored));
  }, [pathSlug]);

  const organizationSlug = pathSlug ?? rememberedSlug;
  return useMemo(
    () => ({
      organizationSlug,
      organizationPrefix: organizationSlug
        ? `/dashboard/${encodeURIComponent(organizationSlug)}`
        : "/dashboard",
      organizationHref: (section: string) =>
        organizationSlug
          ? `/dashboard/${encodeURIComponent(organizationSlug)}/${section}`
          : "/dashboard",
    }),
    [organizationSlug],
  );
}
