import { getPerformance } from "@/lib/data";
import { PerfLabels, Disclaimer } from "@/components/Disclaimer";
import type { StrategyPerf, PlanVsActualWeek } from "@/lib/types";

export const metadata = {
  title: "Strategy Explorer — yantra-research-lab (paper/simulated)",
};

// Small deterministic sparkline so cards look alive without implying real data.
const SPARKS: Record<string, string> = {
  "NIFTY weekday": "0,26 14,22 28,23 42,15 56,17 70,10 84,11 100,4",
  "NIFTY expiry": "0,24 14,20 28,22 42,16 56,14 70,12 84,9 100,7",
  "SENSEX expiry": "0,27 14,24 28,20 42,18 56,12 70,13 84,6 100,3",
};

function pct(n: number) {
  return `${n.toFixed(1)}%`;
}

export default async function StrategiesPage() {
  const perf = await getPerformance();
  const { strategies, plan_vs_actual } = perf;

  return (
    <div>
      <div className="eyebrow" style={{ marginTop: 24 }}>
        <span className="idx">SCREEN 02</span>
        <span className="gk">β</span>
        <span className="nm">Strategy Explorer</span>
        <span className="job">3 paper strategies · plan-vs-actual capture factor</span>
      </div>

      <div
        className="row"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}
      >
        <span className="tag">product: Options · 3 live strategies</span>
        <span className="chip paper">ALL PAPER / SIMULATED</span>
      </div>

      {/* strategy cards */}
      <div className="grid-3">
        {strategies.map((s) => (
          <StrategyCard key={s.name} s={s} />
        ))}
      </div>

      <div style={{ marginTop: 10 }}>
        <PerfLabels />
      </div>

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

function StrategyCard({ s }: { s: StrategyPerf }) {
  const points = SPARKS[s.name] ?? "0,20 100,10";
  return (
    <div className="panel solid">
      <div className="row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <b className="mono" style={{ fontSize: 13 }}>
          {s.name}
        </b>
        <span className="chip paper">PAPER</span>
      </div>
      <svg className="spark" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
        <polyline points={points} fill="none" stroke="var(--up)" strokeWidth={2} />
      </svg>
      <div className="row" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <span className="chip up">BT {pct(s.backtest_return_pct)}</span>
        <span className="chip">win {(s.win_rate * 100).toFixed(1)}%</span>
        <span className="chip">{s.trades} tr</span>
      </div>
      <span className="caption" style={{ marginTop: 4 }}>
        placeholder — % summed, not compounded
      </span>
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
