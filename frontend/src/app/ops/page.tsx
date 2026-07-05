"use client";

import { useEffect, useState } from "react";
import { fetchMetrics, type OpsMetrics } from "@/lib/ops";

const REFRESH_MS = 30_000;

function fmtMs(ms?: number): string {
  if (ms === undefined || ms === null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function fmtCost(usd?: number): string {
  if (!usd) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function Stat({
  label,
  value,
  accent,
  sub,
}: {
  label: string;
  value: string;
  accent?: "acc" | "up" | "down";
  sub?: string;
}) {
  const color =
    accent === "up" ? "var(--up)" : accent === "down" ? "var(--down)" : accent === "acc" ? "var(--acc)" : "var(--fg)";
  return (
    <div className="panel" style={{ flex: "1 1 150px", minWidth: 150 }}>
      <span className="tag">{label}</span>
      <div className="mono" style={{ fontSize: 30, fontWeight: 700, color, marginTop: 8, lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (
        <span className="caption" style={{ marginTop: 4, display: "block" }}>
          {sub}
        </span>
      )}
    </div>
  );
}

export default function OpsPage() {
  const [m, setM] = useState<OpsMetrics | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const data = await fetchMetrics();
        if (alive) {
          setM(data);
          setErr(false);
        }
      } catch {
        if (alive) setErr(true);
      }
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const ready = m?.available === true;

  return (
    <div>
      <div className="eyebrow" style={{ marginTop: 24 }}>
        <span className="idx">SCREEN 05</span>
        <span className="gk">λ</span>
        <span className="nm">Live Ops — production observability</span>
        <span className="job">real telemetry · powered by Logfire</span>
      </div>

      <div
        className="row"
        style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}
      >
        <span className="chip acc">/api/chat</span>
        <span className="chip">OpenTelemetry → Logfire</span>
        <span className="chip">cached ~60s</span>
        {m?.updated_at && (
          <span className="chip paper">updated {new Date(m.updated_at).toLocaleTimeString()}</span>
        )}
      </div>

      <p style={{ color: "var(--muted)", fontSize: 13.5, maxWidth: 720, marginTop: 0 }}>
        Every chat request is traced end-to-end — retrieval, the LLM call, and the guardrail
        decision. Below are <strong>safe aggregates</strong> queried back from Logfire: no user
        text, no IPs, no raw logs — only counts, latency, cost, and guardrail blocks.
      </p>

      {!ready ? (
        <div className="disc strong" style={{ marginTop: 16 }}>
          {err
            ? "Telemetry endpoint unreachable — the backend may be waking from sleep. This panel retries automatically."
            : m && !m.available
            ? "Telemetry is warming up. Once the chatbot handles a few requests, live numbers appear here."
            : "Loading live telemetry…"}
        </div>
      ) : (
        <>
          {/* headline stats */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
            <Stat label="queries served" value={String(m!.queries_served ?? 0)} accent="acc" />
            <Stat
              label="attacks blocked"
              value={String(m!.attacks_blocked ?? 0)}
              accent="up"
              sub="IP-extraction / injection"
            />
            <Stat label="IP leaks" value={String(m!.leaks ?? 0)} accent={m!.leaks ? "down" : "up"} sub="red-team target: 0" />
            <Stat label="p95 latency" value={fmtMs(m!.p95_ms)} sub={`p50 ${fmtMs(m!.p50_ms)}`} />
            <Stat label="avg cost / query" value={fmtCost(m!.avg_cost_usd)} sub={`total ${fmtCost(m!.total_cost_usd)}`} />
          </div>

          <div className="two-col">
            {/* event feed */}
            <div className="panel flat">
              <span className="tag">recent events · sanitized</span>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 10 }}>
                {(m!.recent_events ?? []).length === 0 ? (
                  <span className="caption">no events yet</span>
                ) : (
                  m!.recent_events!.map((e, i) => (
                    <div
                      key={i}
                      className="row"
                      style={{ display: "flex", alignItems: "center", gap: 10, justifyContent: "space-between" }}
                    >
                      <span className="mono caption" style={{ minWidth: 44 }}>
                        {e.ts}
                      </span>
                      <span style={{ flex: 1, fontSize: 13 }}>
                        {e.type === "blocked" ? "🛡️ guardrail blocked a " : "answered · "}
                        {e.detail}
                      </span>
                      <span className={e.type === "blocked" ? "chip down" : "chip up"}>
                        {e.type === "blocked" ? "BLOCKED" : "OK"}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* what we track */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div className="panel">
                <span className="tag">traced per request</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 9 }}>
                  <span className="caption">▸ retrieval latency (Qdrant) vs LLM latency</span>
                  <span className="caption">▸ input/output tokens → estimated $ cost</span>
                  <span className="caption">▸ guardrail verdict (answered / refused + reason)</span>
                  <span className="caption">▸ cold-start flag (scale-to-zero wake)</span>
                </div>
              </div>
              <div className="disc strong">
                This is the <strong>public</strong> view. A private Logfire dashboard behind it holds
                full traces, latency waterfalls, and alerting.
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
