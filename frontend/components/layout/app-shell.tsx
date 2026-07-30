"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bell,
  Command,
  GitPullRequest,
  LayoutDashboard,
  Search,
  ShieldCheck,
  Sparkles,
  WalletCards,
  Webhook,
} from "lucide-react";

import { Sidebar } from "@/components/layout/sidebar";
import { TopNavbar } from "@/components/layout/top-navbar";
import { useOrganizationContext } from "@/lib/use-organization-context";
import type {
  AuthenticatedUser,
  Notification,
  Organization,
} from "@/lib/types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const commandItems = [
  { label: "Executive overview", icon: LayoutDashboard, suffix: "product" },
  { label: "Pull requests", icon: GitPullRequest, href: "/pull-requests" },
  { label: "Review queue", icon: ShieldCheck, suffix: "reviews" },
  { label: "AI review center", icon: Sparkles, suffix: "ai-reviews" },
  { label: "Payouts and treasury", icon: WalletCards, suffix: "finance" },
  { label: "Operations center", icon: Webhook, suffix: "operations" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [selectedCommand, setSelectedCommand] = useState(0);
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const commandDialogRef = useRef<HTMLDivElement>(null);
  const notificationDialogRef = useRef<HTMLElement>(null);
  const { organizationHref, organizationSlug } = useOrganizationContext();
  const currentOrganization =
    organizations.find((item) => item.login === organizationSlug) ?? null;
  const unreadNotifications = notifications.filter((item) => !item.read_at);
  const filteredCommands = useMemo(
    () =>
      commandItems.filter((item) =>
        item.label.toLowerCase().includes(commandQuery.trim().toLowerCase()),
      ),
    [commandQuery],
  );

  useEffect(() => {
    const stored = window.localStorage.getItem("gbd:sidebar-collapsed");
    queueMicrotask(() => setCollapsed(stored === "true"));
  }, []);

  useEffect(() => {
    let active = true;
    const loadShellData = async () => {
      try {
        const [userResponse, organizationsResponse] = await Promise.all([
          fetch(`${API_URL}/auth/me`, { credentials: "include" }),
          fetch(`${API_URL}/organizations`, { credentials: "include" }),
        ]);
        if (!userResponse.ok || !organizationsResponse.ok) return;
        const nextUser = (await userResponse.json()) as AuthenticatedUser;
        const nextOrganizations =
          (await organizationsResponse.json()) as Organization[];
        if (!active) return;
        setUser(nextUser);
        setOrganizations(nextOrganizations);
        const organization = nextOrganizations.find(
          (item) => item.login === organizationSlug,
        );
        if (!organization) {
          setNotifications([]);
          return;
        }
        const response = await fetch(
          `${API_URL}/notifications?organization_id=${organization.id}`,
          { credentials: "include" },
        );
        if (active && response.ok) {
          setNotifications((await response.json()) as Notification[]);
        }
      } catch {
        // Server-rendered pages remain authoritative if shell enrichment fails.
      }
    };
    void loadShellData();
    return () => {
      active = false;
    };
  }, [organizationSlug]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  useEffect(() => {
    if (!commandOpen && !notificationsOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const dialog = commandOpen
      ? commandDialogRef.current
      : notificationDialogRef.current;
    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    queueMicrotask(() => {
      const first = dialog?.querySelector<HTMLElement>(focusableSelector);
      (first ?? dialog)?.focus();
    });
    const handleOverlayKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setCommandOpen(false);
        setNotificationsOpen(false);
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(focusableSelector),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleOverlayKey);
    return () => {
      window.removeEventListener("keydown", handleOverlayKey);
      document.body.style.overflow = originalOverflow;
      previous?.focus();
    };
  }, [commandOpen, notificationsOpen]);

  const navigate = (href?: string, suffix?: string) => {
    setCommandOpen(false);
    router.push(href ?? organizationHref(suffix ?? "product"));
  };

  const toggleSidebar = () => {
    setCollapsed((value) => {
      const next = !value;
      window.localStorage.setItem("gbd:sidebar-collapsed", String(next));
      return next;
    });
  };

  const markNotificationRead = async (notificationId: number) => {
    const response = await fetch(
      `${API_URL}/notifications/${notificationId}/read`,
      { method: "POST", credentials: "include" },
    );
    if (!response.ok) return;
    const updated = (await response.json()) as Notification;
    setNotifications((items) =>
      items.map((item) => (item.id === updated.id ? updated : item)),
    );
  };

  return (
    <div className="flex min-h-dvh bg-background text-foreground">
      <Sidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
        onToggle={toggleSidebar}
        organizationSlug={organizationSlug}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopNavbar
          onMenu={() => setMobileOpen(true)}
          onSearch={() => setCommandOpen(true)}
          onNotifications={() => setNotificationsOpen(true)}
          organizationSlug={organizationSlug}
          currentOrganization={currentOrganization}
          organizations={organizations}
          user={user}
          unreadCount={unreadNotifications.length}
        />
        <main className="min-w-0 flex-1 overflow-x-hidden">
          <div className="mx-auto w-full max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            {children}
          </div>
        </main>
      </div>

      {commandOpen && (
        <div
          className="fixed inset-0 z-[80] flex items-start justify-center bg-slate-950/55 px-4 pt-[12vh] backdrop-blur-sm"
          onMouseDown={() => setCommandOpen(false)}
        >
          <div
            ref={commandDialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Global command palette"
            tabIndex={-1}
            className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/10 bg-popover shadow-2xl"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-border px-4">
              <Search className="h-5 w-5 text-muted-foreground" />
              <input
                autoFocus
                aria-label="Search commands"
                placeholder="Jump to a workflow…"
                value={commandQuery}
                onChange={(event) => {
                  setCommandQuery(event.target.value);
                  setSelectedCommand(0);
                }}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setSelectedCommand((value) =>
                      Math.min(value + 1, filteredCommands.length - 1),
                    );
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setSelectedCommand((value) => Math.max(value - 1, 0));
                  } else if (event.key === "Enter") {
                    const item = filteredCommands[selectedCommand];
                    if (item) navigate(item.href, item.suffix);
                  }
                }}
                className="h-14 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              <kbd className="rounded-md border border-border bg-muted px-2 py-1 text-[11px] text-muted-foreground">
                ESC
              </kbd>
            </div>
            <div className="p-2">
              <p className="px-3 py-2 text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground">
                Navigate
              </p>
              {filteredCommands.map((item, index) => (
                <button
                  key={item.label}
                  aria-current={index === selectedCommand}
                  onClick={() => navigate(item.href, item.suffix)}
                  className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-medium transition ${
                    index === selectedCommand ? "bg-accent" : "hover:bg-accent"
                  }`}
                >
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <item.icon className="h-4 w-4" />
                  </span>
                  <span className="flex-1">{item.label}</span>
                  <Command className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
              ))}
              {filteredCommands.length === 0 && (
                <p className="px-3 py-8 text-center text-sm text-muted-foreground">
                  No matching workflow.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {notificationsOpen && (
        <>
          <button
            aria-label="Close notifications"
            className="fixed inset-0 z-[70] bg-slate-950/30 backdrop-blur-[2px]"
            onClick={() => setNotificationsOpen(false)}
          />
          <aside
            ref={notificationDialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Notifications"
            tabIndex={-1}
            className="fixed inset-y-0 right-0 z-[71] flex w-full max-w-md flex-col border-l border-border bg-popover shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-border px-6 py-5">
              <div>
                <p className="text-lg font-semibold">Notifications</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Review, ingestion, and payout events
                </p>
              </div>
              <button
                onClick={() => setNotificationsOpen(false)}
                className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-accent"
              >
                Close
              </button>
            </div>
            {notifications.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <Bell className="h-6 w-6" />
              </span>
              <p className="mt-5 font-semibold">Your event stream lives here</p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Open the organization overview to inspect delivered notifications
                and their read state.
              </p>
              <button
                onClick={() => navigate(undefined, "product#notifications")}
                className="mt-5 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground"
              >
                View notification history
              </button>
            </div>
            ) : (
              <div className="flex-1 divide-y divide-border overflow-y-auto">
                {notifications.map((notification) => (
                  <div key={notification.id} className="flex gap-3 px-6 py-4">
                    <span
                      className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                        notification.read_at
                          ? "bg-muted-foreground/30"
                          : "bg-indigo-500"
                      }`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold">
                        {notification.subject}
                      </p>
                      <p className="mt-1 text-sm leading-6 text-muted-foreground">
                        {notification.body}
                      </p>
                      {!notification.read_at && (
                        <button
                          onClick={() =>
                            void markNotificationRead(notification.id)
                          }
                          className="mt-2 text-xs font-bold text-primary hover:underline"
                        >
                          Mark as read
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </aside>
        </>
      )}
    </div>
  );
}
