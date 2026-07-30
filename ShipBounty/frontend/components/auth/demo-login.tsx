"use client";

import { useState } from "react";
import {
  BadgeDollarSign,
  Code2,
  LoaderCircle,
  ShieldCheck,
  UserRoundCheck,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const PERSONAS = [
  {
    id: "owner",
    label: "Owner",
    detail: "Policy and final approval",
    icon: ShieldCheck,
  },
  {
    id: "reviewer",
    label: "Reviewer",
    detail: "Evidence and human review",
    icon: UserRoundCheck,
  },
  {
    id: "finance",
    label: "Finance",
    detail: "Treasury controls",
    icon: BadgeDollarSign,
  },
  {
    id: "contributor",
    label: "Contributor",
    detail: "Claim the merged PR",
    icon: Code2,
  },
] as const;

type Persona = (typeof PERSONAS)[number]["id"];

export function DemoLogin({
  apiUrl,
  defaultWorkspace,
}: {
  apiUrl: string;
  defaultWorkspace: string;
}) {
  const [workspace, setWorkspace] = useState(defaultWorkspace);
  const [accessKey, setAccessKey] = useState(
    process.env.NEXT_PUBLIC_DEMO_ACCESS_KEY ?? "",
  );
  const [persona, setPersona] = useState<Persona>("owner");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function signIn() {
    setError("");
    setSubmitting(true);
    try {
      const response = await fetch(`${apiUrl}/auth/demo`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: workspace.trim(),
          persona,
          access_key: accessKey,
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(body?.detail ?? "Demo sign-in failed");
      }
      window.location.assign("/demo");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Demo sign-in failed",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section
      className="mt-6 border-t border-slate-200 pt-6"
      aria-labelledby="demo-login-heading"
    >
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <p
            id="demo-login-heading"
            className="text-sm font-semibold text-slate-900"
          >
            Showcase workspace
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Switch roles without creating extra GitHub accounts. Available only
            when demo mode is enabled.
          </p>
        </div>
        <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-amber-700">
          Demo only
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {PERSONAS.map(({ id, label, detail, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setPersona(id)}
            className={cn(
              "rounded-lg border p-3 text-left transition-colors",
              persona === id
                ? "border-blue-500 bg-blue-50"
                : "border-slate-200 bg-white hover:border-slate-300",
            )}
            aria-pressed={persona === id}
          >
            <Icon
              className={cn(
                "mb-2 h-4 w-4",
                persona === id ? "text-blue-600" : "text-slate-500",
              )}
            />
            <span className="block text-xs font-semibold text-slate-900">
              {label}
            </span>
            <span className="mt-0.5 block text-[10px] leading-4 text-slate-500">
              {detail}
            </span>
          </button>
        ))}
      </div>

      <div className="mt-4 space-y-3">
        <label className="block text-xs font-medium text-slate-700">
          Workspace
          <Input
            className="mt-1.5"
            value={workspace}
            onChange={(event) => setWorkspace(event.target.value)}
            placeholder="github-owner-or-organization"
            autoComplete="organization"
          />
        </label>
        <label className="block text-xs font-medium text-slate-700">
          Demo access key
          <Input
            className="mt-1.5"
            type="password"
            value={accessKey}
            onChange={(event) => setAccessKey(event.target.value)}
            placeholder="Provided by the demo operator"
            autoComplete="current-password"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !submitting) void signIn();
            }}
          />
        </label>
      </div>

      {error ? (
        <p className="mt-3 text-xs font-medium text-red-600" role="alert">
          {error}
        </p>
      ) : null}

      <Button
        className="mt-4 w-full"
        type="button"
        disabled={!workspace.trim() || !accessKey || submitting}
        onClick={() => void signIn()}
      >
        {submitting ? (
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <ShieldCheck className="mr-2 h-4 w-4" />
        )}
        Enter as {PERSONAS.find((item) => item.id === persona)?.label}
      </Button>
    </section>
  );
}
