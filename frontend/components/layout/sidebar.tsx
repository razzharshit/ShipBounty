"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import {
  Activity,
  Bot,
  ChevronLeft,
  CircleDollarSign,
  FileCode2,
  GitPullRequest,
  LayoutDashboard,
  PanelLeft,
  Presentation,
  Settings2,
  ShieldCheck,
  WalletCards,
  X,
  Zap,
} from "lucide-react";

import { cn } from "@/lib/utils";

type SidebarProps = {
  collapsed: boolean;
  mobileOpen: boolean;
  onClose: () => void;
  onToggle: () => void;
  organizationSlug: string | null;
};

export function Sidebar({
  collapsed,
  mobileOpen,
  onClose,
  onToggle,
  organizationSlug,
}: SidebarProps) {
  const pathname = usePathname();
  const organizationPrefix =
    organizationSlug
      ? `/dashboard/${encodeURIComponent(organizationSlug)}`
      : "/dashboard";
  const organizationHref = (section: string) =>
    organizationSlug ? `${organizationPrefix}/${section}` : "/dashboard";

  const groups = [
    {
      label: "Overview",
      items: [
        {
          href: organizationHref("product"),
          label: "Executive overview",
          icon: LayoutDashboard,
        },
      ],
    },
    {
      label: "Work",
      items: [
        { href: "/pull-requests", label: "Pull requests", icon: GitPullRequest },
        {
          href: organizationHref("reviews"),
          label: "Review queue",
          icon: ShieldCheck,
        },
        {
          href: organizationHref("ai-reviews"),
          label: "AI reviews",
          icon: Bot,
        },
        { href: "/patches", label: "Diff workspace", icon: FileCode2 },
      ],
    },
    {
      label: "Rewards",
      items: [
        {
          href: organizationHref("rewards"),
          label: "Bounties & claims",
          icon: CircleDollarSign,
        },
      ],
    },
    {
      label: "Finance",
      items: [
        {
          href: organizationHref("finance"),
          label: "Payouts & treasury",
          icon: WalletCards,
        },
      ],
    },
    {
      label: "Platform",
      items: [
        {
          href: organizationHref("operations"),
          label: "Operations",
          icon: Activity,
        },
        {
          href: organizationHref("organization"),
          label: "Organization",
          icon: Settings2,
        },
      ],
    },
  ];

  return (
    <>
      {mobileOpen && (
        <button
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-slate-950/55 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex shrink-0 flex-col border-r border-white/8 bg-sidebar text-sidebar-foreground shadow-2xl transition-[width,transform] duration-300 lg:sticky lg:top-0 lg:h-dvh lg:translate-x-0 lg:shadow-none",
          collapsed ? "lg:w-[84px]" : "lg:w-[280px]",
          mobileOpen ? "w-[290px] translate-x-0" : "w-[290px] -translate-x-full",
        )}
      >
        <div className="flex h-[76px] items-center gap-3 border-b border-white/8 px-5">
          <div className="relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-indigo-400/20 bg-slate-900 shadow-lg shadow-indigo-950/35">
            <Image
              src="/shipbounty-logo.png"
              alt="ShipBounty Logo"
              width={40}
              height={40}
              className="h-full w-full object-cover"
            />
          </div>
          <div className={cn("min-w-0 flex-1", collapsed && "lg:hidden")}>
            <p className="truncate text-[11px] font-bold uppercase tracking-[0.2em] text-indigo-300">
              GitHub Rewards
            </p>
            <p className="truncate text-[15px] font-semibold tracking-tight text-white">
              ShipBounty
            </p>
          </div>
          <button
            aria-label="Close navigation"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-white/8 hover:text-white lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-5">
          {process.env.NEXT_PUBLIC_DEMO_MODE === "true" && (
            <Link
              href="/demo"
              onClick={onClose}
              className="flex items-center gap-3 rounded-xl border border-indigo-400/20 bg-indigo-500/10 px-3 py-3 text-sm font-semibold text-indigo-100"
            >
              <Presentation className="h-4 w-4" />
              <span className={cn(collapsed && "lg:hidden")}>Showcase guide</span>
            </Link>
          )}
          {groups.map((group) => (
            <div key={group.label}>
              <p
                className={cn(
                  "mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500",
                  collapsed && "lg:text-center lg:text-[0px]",
                )}
              >
                {group.label}
                {collapsed && <span className="hidden lg:inline">•</span>}
              </p>
              <div className="space-y-1">
                {group.items.map(({ href, label, icon: Icon }) => {
                  const active =
                    pathname === href || pathname.startsWith(`${href}/`);
                  return (
                    <Link
                      key={`${group.label}:${label}:${href}`}
                      href={href}
                      onClick={onClose}
                      title={collapsed ? label : undefined}
                      className={cn(
                        "group relative flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium transition",
                        active
                          ? "bg-indigo-500/16 text-white shadow-[inset_0_0_0_1px_rgba(129,140,248,.16)]"
                          : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-100",
                        collapsed && "lg:justify-center",
                      )}
                    >
                      {active && (
                        <span className="absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-indigo-400" />
                      )}
                      <Icon
                        className={cn(
                          "h-[18px] w-[18px] shrink-0",
                          active ? "text-indigo-300" : "text-slate-500",
                        )}
                      />
                      <span className={cn("truncate", collapsed && "lg:hidden")}>
                        {label}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-white/8 p-3">
          <Link
            href={organizationHref("operations")}
            className={cn(
              "mb-2 flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.04] p-3 text-slate-300 hover:bg-white/[0.07]",
              collapsed && "lg:justify-center lg:p-2.5",
            )}
          >
            <Activity className="h-4 w-4 shrink-0 text-indigo-300" />
            <div className={cn(collapsed && "lg:hidden")}>
              <p className="text-xs font-semibold">Inspect system health</p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                Queue, workers, and GitHub limits
              </p>
            </div>
          </Link>
          <button
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="hidden h-10 w-full items-center justify-center gap-2 rounded-xl text-xs font-medium text-slate-400 transition hover:bg-white/[0.06] hover:text-white lg:flex"
          >
            {collapsed ? (
              <PanelLeft className="h-4 w-4" />
            ) : (
              <>
                <ChevronLeft className="h-4 w-4" />
                Collapse navigation
              </>
            )}
          </button>
        </div>
      </aside>
    </>
  );
}
