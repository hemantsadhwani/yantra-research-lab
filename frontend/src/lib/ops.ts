import { BACKEND_URL } from "./chat";

// Public "Live Ops" telemetry. These are SAFE aggregates queried back from Logfire
// by the backend — counts, latency percentiles, cost, guardrail blocks. Never any
// user text, IPs, or raw logs.

export interface OpsEvent {
  ts: string;
  type: "answered" | "blocked";
  detail: string;
}

export interface OpsMetrics {
  available: boolean;
  reason?: string;
  window?: string;
  queries_served?: number;
  answered?: number;
  attacks_blocked?: number;
  leaks?: number;
  p50_ms?: number;
  p95_ms?: number;
  avg_cost_usd?: number;
  total_cost_usd?: number;
  recent_events?: OpsEvent[];
  updated_at?: string;
}

export const METRICS_ENDPOINT = `${BACKEND_URL}/api/metrics`;

export async function fetchMetrics(signal?: AbortSignal): Promise<OpsMetrics> {
  const res = await fetch(METRICS_ENDPOINT, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`metrics ${res.status}`);
  const d = (await res.json()) as Partial<OpsMetrics>;
  return { available: Boolean(d.available), ...d };
}
