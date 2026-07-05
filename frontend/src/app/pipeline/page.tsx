import { getIngestion } from "@/lib/data";
import type { IngestDoc } from "@/lib/types";

export const metadata = {
  title: "Ingestion Pipeline — yantra-research-lab (Tier-3)",
};

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="panel" style={{ flex: "1 1 140px", minWidth: 140 }}>
      <span className="tag">{label}</span>
      <div className="mono" style={{ fontSize: 26, fontWeight: 700, marginTop: 6, lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && <span className="caption" style={{ marginTop: 3, display: "block" }}>{sub}</span>}
    </div>
  );
}

export default async function PipelinePage() {
  const m = await getIngestion();
  const s = m.stats;

  return (
    <div>
      <div className="eyebrow" style={{ marginTop: 24 }}>
        <span className="idx">SCREEN 06</span>
        <span className="gk">⛓</span>
        <span className="nm">Ingestion Pipeline — Tier-3 (agentic, multimodal)</span>
        <span className="job">run {m.run_id} · LangGraph · Logfire-traced</span>
      </div>

      <div className="row" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <span className="chip acc">arXiv q-fin</span>
        <span className="chip">→ {m.collection}</span>
        <span className="chip">{m.embed_model}</span>
        <span className="chip paper">spent ${s.spent_usd.toFixed(4)}</span>
        <span className="chip">{s.duration_s}s</span>
      </div>

      <p style={{ color: "var(--muted)", fontSize: 13.5, maxWidth: 760, marginTop: 0 }}>
        A near-zero-cost, agentic data pipeline: it discovers open-access quant research,
        fetches raw PDFs to an <strong>S3 bronze layer</strong>, parses text + tables + formulas,
        enriches and quality-gates each doc with bounded LLM agents, and indexes the survivors
        into Qdrant — orchestrated as a <strong>LangGraph StateGraph</strong> with retries, a
        dead-letter quarantine, lineage, and a human approval gate. Incremental + content-hashed,
        so a daily refresh costs pennies.
      </p>

      {/* DAG */}
      <div className="panel" style={{ marginBottom: 14 }}>
        <span className="tag">pipeline DAG · discover → … → index</span>
        <div className="row" style={{ display: "flex", alignItems: "stretch", gap: 8, marginTop: 12, flexWrap: "nowrap", overflowX: "auto" }}>
          {m.dag.map((n, i) => (
            <div key={n.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div className={n.id === "gate" ? "node sup" : "node ai"} style={{ minWidth: 128 }}>
                <div style={{ fontWeight: 600 }}>{n.label}</div>
                <div className="caption" style={{ fontSize: 10.5, marginTop: 4 }}>{n.desc}</div>
              </div>
              <span className="arrow">{i === m.dag.length - 1 ? "↦" : "→"}</span>
            </div>
          ))}
        </div>
      </div>

      {/* headline stats */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        <Stat label="papers ingested" value={String(s.parsed)} sub={`of ${s.discovered} discovered`} />
        <Stat label="tables extracted" value={String(s.tables)} />
        <Stat label="papers with formulas" value={String(s.with_math)} />
        <Stat label="chunks indexed" value={String(s.indexed)} sub={`${s.rejected} rejected at gate`} />
        <Stat label="cost this run" value={`$${s.spent_usd.toFixed(4)}`} sub={`budget $${m.budget_usd}`} />
      </div>

      <div className="two-col">
        {/* medallion + governance */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel flat">
            <span className="tag">medallion architecture</span>
            <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 9 }}>
              <span className="caption">▸ <strong>bronze</strong> — raw PDFs in S3, content-hashed (idempotent)</span>
              <span className="caption">▸ <strong>silver</strong> — parsed text · tables · images · formulas</span>
              <span className="caption">▸ <strong>gold</strong> — enriched chunks in Qdrant + lineage catalog</span>
            </div>
          </div>
          <div className="panel flat">
            <span className="tag">quality gate · dead-letter</span>
            {Object.keys(m.rejects_by_reason).length === 0 ? (
              <span className="caption" style={{ marginTop: 8, display: "block" }}>no rejects this run</span>
            ) : (
              <div className="row" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 9 }}>
                {Object.entries(m.rejects_by_reason).map(([reason, n]) => (
                  <span key={reason} className="chip down">{reason}: {n}</span>
                ))}
              </div>
            )}
            <span className="caption" style={{ marginTop: 8, display: "block" }}>
              Rejects are quarantined with a reason — never dropped silently. The IP-leak gate
              enforces the privacy boundary for future private sources.
            </span>
          </div>
        </div>

        {/* lineage table */}
        <div className="panel flat">
          <span className="tag">lineage · per document</span>
          <div style={{ overflowX: "auto", marginTop: 10 }}>
            <table className="tbl" style={{ width: "100%", fontSize: 12.5, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th style={{ padding: "4px 8px 4px 0" }}>paper</th>
                  <th style={{ padding: "4px 8px" }}>pg</th>
                  <th style={{ padding: "4px 8px" }}>tbl</th>
                  <th style={{ padding: "4px 8px" }}>∑</th>
                  <th style={{ padding: "4px 8px" }}>chunks</th>
                </tr>
              </thead>
              <tbody>
                {m.docs.map((d: IngestDoc) => (
                  <tr key={d.id} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={{ padding: "6px 8px 6px 0", maxWidth: 320 }}>
                      <a href={d.source} target="_blank" rel="noopener noreferrer">
                        {d.title.length > 64 ? d.title.slice(0, 64) + "…" : d.title}
                      </a>
                    </td>
                    <td className="mono" style={{ padding: "6px 8px" }}>{d.pages}</td>
                    <td className="mono" style={{ padding: "6px 8px" }}>{d.tables}</td>
                    <td style={{ padding: "6px 8px" }}>{d.has_math ? "✓" : ""}</td>
                    <td className="mono" style={{ padding: "6px 8px" }}>{d.chunks_indexed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="disc strong" style={{ marginTop: 14 }}>
        Runs offline on a <strong>GitHub Actions cron</strong> (near-zero cost). Images extracted to
        S3; <strong>vision-captioning</strong> and <strong>tables → Text-to-SQL</strong> are the next
        multimodal sub-projects. Sources are public arXiv; the same framework will feed private
        strategy metrics through the IP guardrail into the honesty panel.
      </div>
    </div>
  );
}
