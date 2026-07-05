import { getRun } from "@/lib/data";
import { Disclaimer } from "@/components/Disclaimer";
import type { RankedVariant } from "@/lib/types";

export const metadata = {
  title: "Research Lab — yantra-research-lab (agentic core)",
};

const PIPELINE = [
  { label: "Supervisor", cls: "node sup" },
  { label: "Proposer", cls: "node ai" },
  { label: "Backtester", cls: "node ai" },
  { label: "Evaluator", cls: "node ai" },
  { label: "Ranker", cls: "node ai" },
];

function verdictChip(v: string) {
  const lower = v.toLowerCase();
  if (lower.includes("promote")) return "chip up";
  if (lower.includes("reject")) return "chip down";
  return "chip";
}

export default async function ResearchLabPage() {
  const run = await getRun();
  const b = run.baseline;

  return (
    <div>
      <div className="eyebrow" style={{ marginTop: 24 }}>
        <span className="idx">SCREEN 03</span>
        <span className="gk">Σ</span>
        <span className="nm">Research Lab — the agentic core</span>
        <span className="job">run #{run.run_id} · strategy: {run.strategy}</span>
      </div>

      <div
        className="row"
        style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}
      >
        <span className="chip acc">Run #{run.run_id}</span>
        <span className="chip">iterations {run.iterations}</span>
        <span className="chip">{run.variants_per_iter} variants/iter</span>
        <span className="chip">{run.variants_tested} variants tested</span>
        <span className="chip paper">SIMULATED</span>
      </div>

      {/* pipeline */}
      <div className="panel" style={{ marginBottom: 14 }}>
        <span className="tag">supervisor → workers · bounded by budget</span>
        <div
          className="row"
          style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12, flexWrap: "nowrap", overflowX: "auto" }}
        >
          {PIPELINE.map((n, i) => (
            <div key={n.label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div className={n.cls}>{n.label}</div>
              <span className="arrow">{i === PIPELINE.length - 1 ? "↺" : "→"}</span>
            </div>
          ))}
          <div className="node dashed">Memory</div>
        </div>
        <p style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 12, marginBottom: 0 }}>
          The supervisor plans each iteration; the proposer drafts variants; the backtester runs
          them on the synthetic engine; the evaluator scores each against the baseline; the ranker
          orders survivors and writes winners to memory for the next iteration.
        </p>
      </div>

      <div className="two-col">
        {/* ranked table */}
        <div className="panel flat">
          <div className="row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span className="tag">ranked variants · run #{run.run_id}</span>
            <span className="chip">baseline +{b.total_return_pct.toFixed(1)}% · score {b.score.toFixed(1)}</span>
          </div>

          <div className="scroll" style={{ marginTop: 10 }}>
            <table className="rank">
              <thead>
                <tr>
                  <th>#</th>
                  <th>variant</th>
                  <th>return %</th>
                  <th>win %</th>
                  <th>drawdown %</th>
                  <th>score</th>
                  <th>verdict</th>
                </tr>
              </thead>
              <tbody>
                {/* baseline row for reference */}
                <tr>
                  <td>—</td>
                  <td style={{ color: "var(--muted)" }}>baseline</td>
                  <td>{b.total_return_pct.toFixed(1)}</td>
                  <td>{(b.win_rate * 100).toFixed(0)}</td>
                  <td>{b.max_drawdown_pct.toFixed(1)}</td>
                  <td>{b.score.toFixed(1)}</td>
                  <td>
                    <span className="chip">reference</span>
                  </td>
                </tr>
                {run.ranked.map((v) => (
                  <VariantRow key={v.variant_id} v={v} best={v.variant_id === run.best_variant_id} />
                ))}
              </tbody>
            </table>
          </div>
          <span className="caption" style={{ display: "block", marginTop: 9 }}>
            Return % is summed, not compounded · backtested on a synthetic engine, not live-executed.
          </span>
        </div>

        {/* budget + hitl */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel">
            <span className="tag">budget</span>
            <div className="alloc" style={{ marginTop: 10 }}>
              <span className="lab">iterations</span>
              <span className="track">
                <i style={{ width: "100%" }} />
              </span>
              <span className="pct">
                {run.iterations}/{run.iterations}
              </span>
            </div>
            <div className="alloc" style={{ marginTop: 8 }}>
              <span className="lab">variants</span>
              <span className="track">
                <i style={{ width: "100%" }} />
              </span>
              <span className="pct">{run.variants_tested}</span>
            </div>
            <p style={{ color: "var(--muted)", fontSize: 11.5, marginTop: 10, marginBottom: 0 }}>
              Autonomy is bounded — the loop stops at {run.iterations} iterations /{" "}
              {run.variants_tested} variants.
            </p>
          </div>

          <div className="panel solid" style={{ borderColor: "var(--accent)" }}>
            <span className="tag" style={{ color: "var(--accent-ink)" }}>
              human-in-the-loop · promote?
            </span>
            <p style={{ fontSize: 13, marginTop: 8, marginBottom: 8, fontWeight: 600 }}>
              Nothing is promoted autonomously.
            </p>
            <p style={{ color: "var(--muted)", fontSize: 12.5, margin: 0 }}>{run.hitl}</p>
            <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
              <span className="chip up">top: {run.best_variant_id} · promote?</span>
              <span className="chip">awaiting approval</span>
            </div>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <Disclaimer strong>
          ALL PAPER / SIMULATED — educational, not investment advice. This screen is a static render
          of a cached run; it makes zero backend calls.
        </Disclaimer>
      </div>
    </div>
  );
}

function VariantRow({ v, best }: { v: RankedVariant; best: boolean }) {
  const retCls = v.total_return_pct >= 0 ? "var(--up)" : "var(--down)";
  return (
    <tr className={best ? "best" : undefined}>
      <td>{v.rank}</td>
      <td>
        <span style={{ color: "var(--ink)", fontWeight: 700 }}>{v.variant_id}</span>
        {v.rationale ? (
          <div style={{ color: "var(--muted)", fontSize: 10.5, whiteSpace: "normal", maxWidth: 220 }}>
            {v.rationale}
          </div>
        ) : null}
      </td>
      <td style={{ color: retCls }}>{v.total_return_pct.toFixed(1)}</td>
      <td>{(v.win_rate * 100).toFixed(0)}</td>
      <td>{v.max_drawdown_pct.toFixed(1)}</td>
      <td>{v.score.toFixed(1)}</td>
      <td>
        <span className={verdictChip(v.verdict)}>{v.verdict}</span>
      </td>
    </tr>
  );
}
