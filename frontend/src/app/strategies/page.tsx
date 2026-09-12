import { getBooksIndex, getAllBooks, getPerformance, getRiskGates } from "@/lib/data";
import { PerfLabels, Disclaimer } from "@/components/Disclaimer";
import StrategyExplorer from "@/components/strategies/StrategyExplorer";
import type { PlanVsActualWeek } from "@/lib/types";

export const metadata = {
  title: "Strategy Explorer — yantra-research-lab (backtest/simulated)",
};

export default async function StrategiesPage() {
  const [index, books, riskGates, perf] = await Promise.all([
    getBooksIndex(),
    getAllBooks(),
    getRiskGates(),
    getPerformance(),
  ]);
  const { plan_vs_actual } = perf;

  const bookCount = index.products.reduce((n, p) => n + p.books.length, 0);

  return (
    <div>
      <div className="eyebrow" style={{ marginTop: 24 }}>
        <span className="idx">SCREEN 02</span>
        <span className="gk">β</span>
        <span className="nm">Strategy Explorer</span>
        <span className="job">
          {index.products.length} products · {bookCount} books · 12-month backtest, labeled
        </span>
      </div>

      <div
        className="row"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}
      >
        <span className="tag">product: Options · 3 products · backtest outputs only</span>
        <span className="chip paper">BACKTEST · SIMULATED FILLS</span>
      </div>

      <StrategyExplorer index={index} books={books} riskGates={riskGates} />

      {/* plan vs actual */}
      <section style={{ marginTop: 28 }}>
        <div className="eyebrow">
          <span className="idx">CAPTURE FACTOR</span>
          <span className="gk">f</span>
          <span className="nm">Plan vs Actual</span>
          <span className="job">backtest expectation vs live paper</span>
        </div>

        <div className="panel flat">
          <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 0 }}>
            <strong>Capture factor = live ÷ backtest.</strong> It is deliberately shown as an{" "}
            <em>honesty</em> feature: a backtest is a promise, live paper is what actually printed.
            A capture factor below 1.0 says the live edge is a fraction of the backtest — parity
            discipline, stated out loud rather than hidden.
          </p>

          <div
            className="row"
            style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginTop: 6 }}
          >
            <span className="tag">weekly plan vs realized</span>
            <span className="chip acc">capture·f ≈ {plan_vs_actual.capture_factor.toFixed(2)}</span>
          </div>

          <div className="scroll" style={{ marginTop: 10 }}>
            <table className="pva">
              <thead>
                <tr>
                  <th>week</th>
                  <th>BT plan</th>
                  <th>live actual</th>
                  <th>realized</th>
                  <th>capture f</th>
                </tr>
              </thead>
              <tbody>
                {plan_vs_actual.weeks.map((w) => (
                  <WeekRow key={w.week} w={w} />
                ))}
              </tbody>
            </table>
          </div>

          <span className="caption" style={{ display: "block", marginTop: 9 }}>
            Placeholder values — owner fills real labeled numbers from the private master.
          </span>
        </div>

        <div style={{ marginTop: 12 }}>
          <PerfLabels />
        </div>
      </section>

      <div style={{ marginTop: 16 }}>
        <Disclaimer>{perf.disclaimer}</Disclaimer>
      </div>
    </div>
  );
}

function WeekRow({ w }: { w: PlanVsActualWeek }) {
  const live = w.live_actual_pct;
  const liveCls = live > 0 ? "var(--up)" : live < 0 ? "var(--down)" : "var(--muted)";
  const fClass = w.capture_f < 0.5 ? "fchip lo" : "fchip mid";
  return (
    <tr>
      <td>{w.week}</td>
      <td>{w.bt_plan_pct.toFixed(2)}%</td>
      <td style={{ color: liveCls }}>{live.toFixed(2)}%</td>
      <td>{w.realized.toFixed(0)}</td>
      <td>
        <span className={fClass}>{w.capture_f.toFixed(2)}</span>
      </td>
    </tr>
  );
}
