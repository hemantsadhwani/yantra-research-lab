import { getBench, headline, REPO } from "@/lib/bench";
import StudyReplay from "@/components/lab/StudyReplay";

export const metadata = {
  title: "Research Lab · yantra",
  description: "Six agents and a supervisor research a trading idea; code owns every number; a human promotes.",
};

const FLOW: { label: string; cls: string; note: string }[] = [
  { label: "Intake", cls: "node ai", note: "idea → testable spec; asks only if the style is unclear" },
  { label: "Planner", cls: "node ai", note: "templates, trial budget, rounds" },
  { label: "Plan critic", cls: "node ai", note: "approves or sends the plan back once" },
  { label: "Data", cls: "node sup", note: "allow-listed source, quality checks, content hash" },
  { label: "Researcher", cls: "node ai", note: "reads the ledger, proposes ≤3 targeted families" },
  { label: "Engine", cls: "node sup", note: "walk-forward over 5 blocks; every trial and look counted" },
  { label: "Critic", cls: "node ai", note: "believable? asks for robustness checks, or stops" },
  { label: "Holdout", cls: "node sup", note: "sealed last 2 years; opened once, by code" },
  { label: "Reporter", cls: "node ai", note: "plain English; every number checked against the ledger" },
  { label: "Human gate", cls: "node dashed", note: "nothing is promoted without a person" },
];

export default async function ResearchLabPage() {
  const bench = await getBench();
  const h = headline(bench);

  return (
    <div>
      <div className="eyebrow" style={{ marginTop: 24 }}>
        <span className="idx">RESEARCH LAB</span>
        <span className="gk">Σ</span>
        <span className="nm">Six agents, one supervisor</span>
        <span className="job">agents decide what to test · code decides what is true · a human promotes</span>
      </div>

      <div className="panel" style={{ marginBottom: 14 }}>
        <span className="tag">the study graph (LangGraph) · loops until a stop rule fires</span>
        <div className="flow" style={{ marginTop: 12 }}>
          {FLOW.map((n, i) => (
            <div key={n.label} className="flowstep">
              <div className={n.cls} title={n.note}>
                {n.label}
              </div>
              <div className="flownote">{n.note}</div>
              {i < FLOW.length - 1 ? <span className="arrow">→</span> : null}
            </div>
          ))}
        </div>
        <p style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 12, marginBottom: 0 }}>
          Stop rules: planned rounds done, trial budget, dollar budget, no gain in 2 rounds, or the researcher or critic says
          stop. Every walk-forward result the agents react to is a counted <em>look</em>, and the bar rises with each one:
          OOS Sharpe ≥ 0.4 + 0.1·log2(looks). Round 1 is always a full baseline run by code; models open with textbook
          settings, so the agents refine from coverage instead of guessing.
        </p>
      </div>

      <div className="grid-3" style={{ marginBottom: 14 }}>
        <div className="panel solid">
          <span className="tag">agents decide</span>
          <p className="small">What to ask, which templates and filters to test, which families to diagnose, when to stop.</p>
        </div>
        <div className="panel solid">
          <span className="tag">code verifies</span>
          <p className="small">
            Proposals clamped to the catalogue; trials and looks counted; walk-forward; the sealed holdout opened once; every
            number in the report checked. Bad model output falls back to rules and is counted.
          </p>
        </div>
        <div className="panel solid" style={{ borderColor: "var(--accent)" }}>
          <span className="tag" style={{ color: "var(--accent-ink)" }}>
            a human promotes
          </span>
          <p className="small">A study that passes stops at promote? and waits. Approving changes nothing by itself.</p>
        </div>
      </div>

      {/* benchmark */}
      <section style={{ marginTop: 28 }}>
        <div className="eyebrow">
          <span className="idx">BENCHMARK</span>
          <span className="gk">β</span>
          <span className="nm">Does it find real edges and refuse noise?</span>
          <span className="job">{bench.benchmark.markets}</span>
        </div>
        <div className="panel flat">
          <div className="scroll">
            <table className="rank">
              <thead>
                <tr>
                  <th>arm</th>
                  <th>edges found</th>
                  <th>noise promoted</th>
                  <th>trials</th>
                  <th>model cost</th>
                  <th>median study</th>
                </tr>
              </thead>
              <tbody>
                {bench.benchmark.arms.map((a) => (
                  <tr key={a.label} className={a.label === "LLM agents v2" ? "best" : undefined}>
                    <td style={{ color: "var(--ink)", fontWeight: 700 }}>{a.label}</td>
                    <td>{a.edges}</td>
                    <td style={{ color: a.noise.startsWith("0/") ? "var(--up)" : "var(--down)" }}>{a.noise}</td>
                    <td>{a.trials.toLocaleString("en-US")}</td>
                    <td>{a.usd ? `$${a.usd.toFixed(2)}` : "$0"}</td>
                    <td>{a.median_seconds ? `${a.median_seconds} s` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 10, marginBottom: 0 }}>
            Unguarded optimisation promoted noise {h.naive.noise}. The agents kept the full protocol&apos;s verdicts with{" "}
            {h.fewer}× fewer trials, at about ${h.perStudy.toFixed(3)} a study. v1 missed three edges because the model opened
            with textbook settings; v2 starts from a code-run baseline and was checked on separate calibration seeds before
            one re-run. Both results are published, with the disclosures, in{" "}
            <a href={`${REPO}/blob/main/results/README.md`}>results/README.md</a>.
          </p>
        </div>
      </section>

      {/* replays */}
      <section style={{ marginTop: 28 }}>
        <div className="eyebrow">
          <span className="idx">REPLAYS</span>
          <span className="gk">▶</span>
          <span className="nm">Real studies, step by step</span>
          <span className="job">recorded runs · real models on AWS Bedrock · nothing invented</span>
        </div>
        <StudyReplay studies={bench.studies} />
      </section>

      <div className="disc" style={{ marginTop: 18 }}>
        Research software. Results are backtests on public daily data or synthetic markets, not live trading and not
        investment advice. This page is a static render of recorded runs; it calls no backend.
      </div>
    </div>
  );
}
