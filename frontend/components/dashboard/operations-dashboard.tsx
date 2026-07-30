import {
  Activity,
  AlertTriangle,
  Clock3,
  Gauge,
  ListRestart,
  Server,
  Timer,
  Webhook,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/services/api";
import type { OperationsDashboard as OperationsData } from "@/lib/types";

function duration(seconds: number | null) {
  if (seconds === null) return "No completed jobs";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${(seconds / 60).toFixed(1)}m`;
}

function statusClass(status: string) {
  if (status === "complete" || status === "delivered") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "failed" || status === "incomplete") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  if (status === "processing") {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  return "border-amber-200 bg-amber-50 text-amber-700";
}

export function OperationsDashboard({ data }: { data: OperationsData }) {
  const metrics = [
    { label: "Queue depth", value: data.queue_depth, detail: `${data.awaiting_publish} awaiting publish`, icon: ListRestart },
    { label: "Running jobs", value: data.running_jobs, detail: `${data.queued_jobs} queued`, icon: Activity },
    { label: "Failed jobs", value: data.failed_jobs, detail: `${data.total_retry_attempts} retry attempts`, icon: AlertTriangle },
    { label: "Incomplete PRs", value: data.incomplete_ingestions, detail: "Authoritative scoring withheld", icon: Webhook },
    { label: "Average processing", value: duration(data.average_processing_seconds), detail: "Completed delivery duration", icon: Timer },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Operations</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-950">Ingestion control room</h2>
          <p className="mt-1 text-sm text-slate-500">Live database-backed delivery, worker and GitHub API telemetry.</p>
        </div>
        <p className="text-xs text-slate-400">Updated {formatDate(data.generated_at)}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {metrics.map(({ label, value, detail, icon: Icon }) => (
          <Card key={label} className="border-slate-200 shadow-none">
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</p>
                  <p className="mt-1.5 text-2xl font-bold text-slate-950">{value}</p>
                  <p className="mt-1 text-[11px] text-slate-500">{detail}</p>
                </div>
                <div className="rounded-lg bg-slate-100 p-2 text-slate-600"><Icon className="h-4 w-4" /></div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
        <Card className="border-slate-200 shadow-none">
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Webhook className="h-4 w-4 text-blue-600" />Recent webhook deliveries</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            {data.recent_deliveries.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">No webhook deliveries recorded for this organization.</p>
            ) : (
              <table className="w-full min-w-[680px] text-left text-xs">
                <thead className="border-b border-slate-100 text-[10px] uppercase tracking-wider text-slate-400">
                  <tr><th className="pb-2 font-semibold">Delivery</th><th className="pb-2 font-semibold">Event</th><th className="pb-2 font-semibold">Status</th><th className="pb-2 font-semibold">Attempts</th><th className="pb-2 font-semibold">Received</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.recent_deliveries.map((delivery) => (
                    <tr key={delivery.id}>
                      <td className="max-w-44 truncate py-3 font-mono text-[11px] text-slate-700">{delivery.delivery_id}</td>
                      <td className="py-3 text-slate-600">{delivery.event_type}{delivery.action ? ` · ${delivery.action}` : ""}</td>
                      <td className="py-3"><Badge variant="outline" className={statusClass(delivery.status)}>{delivery.status}</Badge></td>
                      <td className="py-3 text-slate-600">{delivery.attempt_count}</td>
                      <td className="py-3 text-slate-500">{formatDate(delivery.received_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="border-slate-200 shadow-none">
            <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Server className="h-4 w-4 text-indigo-600" />Worker heartbeat</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {data.workers.length === 0 ? (
                <p className="py-5 text-sm text-slate-500">No worker heartbeat has been recorded.</p>
              ) : data.workers.map((worker) => (
                <div key={worker.worker_id} className="rounded-lg border border-slate-100 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-semibold text-slate-800">{worker.worker_id}</p>
                    <Badge variant="outline" className={worker.is_stale ? "border-rose-200 bg-rose-50 text-rose-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}>{worker.is_stale ? "stale" : "online"}</Badge>
                  </div>
                  <p className="mt-1 text-[10px] text-slate-500">{worker.active_tasks} active · seen {formatDate(worker.last_seen_at)}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="border-slate-200 shadow-none">
            <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Gauge className="h-4 w-4 text-emerald-600" />GitHub rate limits</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {data.github_rate_limits.length === 0 ? (
                <p className="py-5 text-sm text-slate-500">No GitHub rate-limit headers observed yet.</p>
              ) : data.github_rate_limits.map((limit) => {
                const percentage = limit.limit ? (limit.remaining / limit.limit) * 100 : 0;
                return (
                  <div key={`${limit.installation_id}-${limit.resource}`}>
                    <div className="flex justify-between text-[11px]"><span className="font-semibold text-slate-700">{limit.resource}</span><span className="text-slate-500">{limit.remaining.toLocaleString()} / {limit.limit.toLocaleString()}</span></div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${percentage < 20 ? "bg-rose-500" : "bg-emerald-500"}`} style={{ width: `${Math.max(0, Math.min(100, percentage))}%` }} /></div>
                    <p className="mt-1 text-[10px] text-slate-400">Resets {formatDate(limit.reset_at)}</p>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="border-slate-200 shadow-none">
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><AlertTriangle className="h-4 w-4 text-amber-600" />Incomplete PR ingestions</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {data.incomplete_pull_requests.length === 0 ? <p className="py-5 text-sm text-slate-500">No incomplete PR ingestions.</p> : data.incomplete_pull_requests.map((pr) => (
              <div key={pr.id} className="rounded-lg border border-amber-100 bg-amber-50/50 p-3">
                <p className="text-xs font-semibold text-slate-900">{pr.title}</p>
                <p className="mt-1 text-[11px] text-slate-500">{pr.repository} · {pr.incomplete_reason ?? "Incomplete snapshot"}</p>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card className="border-slate-200 shadow-none">
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Clock3 className="h-4 w-4 text-rose-600" />Failure logs</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {data.failure_logs.length === 0 ? <p className="py-5 text-sm text-slate-500">No delivery failures recorded.</p> : data.failure_logs.map((failure) => (
              <div key={failure.id} className="rounded-lg border border-rose-100 bg-rose-50/40 p-3">
                <div className="flex items-center justify-between gap-2"><p className="text-xs font-semibold text-slate-900">{failure.event_type}</p><span className="text-[10px] text-slate-400">{formatDate(failure.received_at)}</span></div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-rose-700">{failure.last_error}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
