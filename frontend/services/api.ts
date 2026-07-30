import type { PullRequest } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function fetchAPI<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    let detail = `API error: ${res.status}`;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const data = await fetchAPI<{ status: string }>("/health");
    return data.status === "ok";
  } catch {
    return false;
  }
}

export function getRepoLabel(pr: PullRequest): string {
  return `${pr.repository.owner}/${pr.repository.name}`;
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatNumber(n: number): string {
  return n.toLocaleString();
}

