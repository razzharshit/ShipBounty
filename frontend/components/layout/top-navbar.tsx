"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Bell,
  Check,
  ChevronDown,
  Command,
  Menu,
  Moon,
  LogOut,
  Search,
  Sun,
} from "lucide-react";

type TopNavbarProps = {
  onMenu: () => void;
  onSearch: () => void;
  onNotifications: () => void;
  organizationSlug: string | null;
  currentOrganization: import("@/lib/types").Organization | null;
  organizations: import("@/lib/types").Organization[];
  user: import("@/lib/types").AuthenticatedUser | null;
  unreadCount: number;
};

export function TopNavbar({
  onMenu,
  onSearch,
  onNotifications,
  organizationSlug,
  currentOrganization,
  organizations,
  user,
  unreadCount,
}: TopNavbarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [dark, setDark] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const parts = pathname.split("/");
  const organization =
    organizationSlug ?? "Choose an organization";
  const section = (parts.at(-1) || "overview")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
  const environment =
    process.env.NEXT_PUBLIC_DEMO_MODE === "true"
      ? "Demo"
      : process.env.NEXT_PUBLIC_APP_ENV ?? "Development";
  const userLabel = user?.display_name || user?.username || "Account";
  const initials = userLabel.slice(0, 2).toUpperCase();

  useEffect(() => {
    const stored = window.localStorage.getItem("gbd:theme");
    const useDark =
      stored === "dark" ||
      (!stored && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", useDark);
    queueMicrotask(() => setDark(useDark));
  }, []);

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    window.localStorage.setItem("gbd:theme", next ? "dark" : "light");
  };

  const logout = async () => {
    const apiUrl =
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    try {
      await fetch(`${apiUrl}/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } finally {
      window.location.assign("/login");
    }
  };

  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-background/88 backdrop-blur-xl">
      <div className="flex h-[76px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button
          onClick={onMenu}
          aria-label="Open navigation"
          className="flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground lg:hidden"
        >
          <Menu className="h-5 w-5" />
        </button>

        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <span className="max-w-[130px] truncate sm:max-w-none">{organization}</span>
            <span>/</span>
            <span>{section}</span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <p className="truncate text-base font-semibold tracking-tight sm:text-lg">
              Engineering rewards operations
            </p>
            <span className="hidden rounded-md border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-indigo-700 dark:border-indigo-400/20 dark:bg-indigo-400/10 dark:text-indigo-300 sm:inline-flex">
              {environment}
            </span>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {organizations.length > 0 && (
            <label className="hidden xl:block">
              <span className="sr-only">Organization</span>
              <select
                value={organizationSlug ?? ""}
                onChange={(event) => {
                  const slug = event.target.value;
                  window.localStorage.setItem("gbd:last-organization", slug);
                  const section =
                    parts[1] === "dashboard" && parts.length >= 4
                      ? parts[3]
                      : "product";
                  router.push(
                    `/dashboard/${encodeURIComponent(slug)}/${section}`,
                  );
                }}
                className="h-10 max-w-52 rounded-xl border border-border bg-card px-3 text-sm font-semibold shadow-sm"
              >
                {organizations.map((item) => (
                  <option key={item.id} value={item.login}>
                    {item.display_name || item.login}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            onClick={onSearch}
            className="hidden h-10 min-w-[220px] items-center gap-2 rounded-xl border border-border bg-card px-3 text-sm text-muted-foreground shadow-sm transition hover:border-primary/30 hover:text-foreground md:flex"
          >
            <Search className="h-4 w-4" />
            <span className="flex-1 text-left">Search workflows</span>
            <kbd className="flex items-center gap-1 rounded-md border border-border bg-muted px-1.5 py-0.5 text-[10px]">
              <Command className="h-3 w-3" />K
            </kbd>
          </button>
          <button
            onClick={toggleTheme}
            aria-label="Toggle color theme"
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground shadow-sm transition hover:text-foreground"
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button
            onClick={onNotifications}
            aria-label="Open notifications"
            className="relative flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground shadow-sm transition hover:text-foreground"
          >
            <Bell className="h-4 w-4" />
            {unreadCount > 0 && (
              <span className="absolute right-2 top-2 h-2 w-2 rounded-full border-2 border-card bg-indigo-500" />
            )}
          </button>
          <div className="relative">
            <button
              onClick={() => setUserMenuOpen((value) => !value)}
              aria-expanded={userMenuOpen}
              className="flex h-10 items-center gap-2 rounded-xl border border-border bg-card px-2.5 shadow-sm"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-[11px] font-bold text-white">
                {initials}
              </span>
              <span className="text-left">
                <span className="hidden max-w-28 truncate text-xs font-semibold sm:block">
                  {userLabel}
                </span>
                <span className="hidden items-center gap-1 text-[10px] capitalize text-emerald-600 sm:flex">
                  <Check className="h-3 w-3" />{" "}
                  {currentOrganization?.role ?? "authenticated"}
                </span>
              </span>
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
            {userMenuOpen && (
              <div className="absolute right-0 top-12 w-56 rounded-xl border border-border bg-popover p-2 shadow-xl">
                <div className="border-b border-border px-3 py-2.5">
                  <p className="text-sm font-semibold">{userLabel}</p>
                  <p className="mt-1 text-xs capitalize text-muted-foreground">
                    {organization} ·{" "}
                    {currentOrganization?.role ?? "repository scoped"}
                  </p>
                </div>
                {organizations.length > 0 && (
                  <label className="block border-b border-border px-3 py-3 text-xs font-semibold">
                    Organization
                    <select
                      value={organizationSlug ?? ""}
                      onChange={(event) => {
                        const slug = event.target.value;
                        window.localStorage.setItem(
                          "gbd:last-organization",
                          slug,
                        );
                        router.push(
                          `/dashboard/${encodeURIComponent(slug)}/product`,
                        );
                        setUserMenuOpen(false);
                      }}
                      className="mt-1.5 h-9 w-full rounded-lg border border-border bg-card px-2 text-sm"
                    >
                      {organizations.map((item) => (
                        <option key={item.id} value={item.login}>
                          {item.display_name || item.login}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <button
                  onClick={logout}
                  className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-400/10"
                >
                  <LogOut className="h-4 w-4" />
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
