import Link from "next/link";
import { getBench, headline, REPO } from "@/lib/bench";

export default async function LandingPage() {
  const bench = await getBench();
  const h = headline(bench);

  const KPIS = [
    { k: "planted edges found", v: h.v2.edges, note: `noise promoted ${h.v2.noise} · unguarded search: ${h.naive.noise}` },
    { k: "fewer trials", v: `${h.fewer}×`, note: `${h.v2.trials.toLocaleString("en-US")} vs ${h.grid.trials.toLocaleString("en-US")} for the full grid, same verdicts` },
    { k: "model cost per study", v: `$${h.perStudy.toFixed(3)}`, note: `median ${h.v2.median_seconds} s · open models on AWS Bedrock` },
    { k: "idea → verdict", v: "< 1 min", note: "public-data study; real-backtest studies take minutes. Manual: 1–3 weeks (owner's estimate)" },
  ];

  return (
    <div>
      <p className="kicker" style={{ marginTop: 24 }}>
        {"// agentic strategy research platform"}
      </p>
      <h1 className="h1">
        Research that <span className="hl">refuses to fool itself</span>
        <span className="cursor">▊</span>
      </h1>
      <p className="lede">
        A team of AI agents turns a trading idea into a tested verdict. Most optimisation finds patterns in noise. Here
        agents decide <strong>what</strong> to test, code decides <strong>what is true</strong>, and a person decides what
        gets promoted. Every number is counted, checked and reproducible.
      </p>

      <div className="row" style={{ display: "flex", gap: 10, marginTop: 22, flexWrap: "wrap" }}>
        <Link href="/research-lab/" className="btn pri">
          Watch a study, step by step →
        </Link>
        <a href="/track-record/" className="btn">
          Daily backtest record
        </a>
        <a href={REPO} className="btn">
          Code on GitHub
        </a>
      </div>

      {/* business objective + KPIs */}
      <section style={{ marginTop: 36 }}>
        <div className="eyebrow">
          <span className="idx">OBJECTIVE</span>
          <span className="gk">α</span>
          <span className="nm">Cut research time and cost, and stop overfit strategies before they reach capital</span>
          <span className="job">measured on a planted-edge benchmark · results/README.md</span>
        </div>
        <div className="grid-4">
          {KPIS.map((x) => (
            <div className="panel solid kpi" key={x.k}>
              <div className="kv">{x.v}</div>
              <div className="kk">{x.k}</div>
              <p className="small">{x.note}</p>
            </div>
          ))}
        </div>
        <p className="small" style={{ marginTop: 10 }}>
          Benchmark: {bench.benchmark.markets}. The right answer is known for every market, so a false discovery is
          visible. Both agent versions are published, including the first one, which found only {bench.benchmark.arms.find((a) => a.label === "LLM agents v1")?.edges}.
        </p>
      </section>

      {/* how it works */}
      <section style={{ marginTop: 32 }}>
        <div className="grid-3">
          <div className="panel solid">
            <span className="tag">Σ six agents · one supervisor</span>
            <div className="ptitle">Agents decide</div>
            <p className="small">
              Intake, planner, plan critic, researcher, critic and reporter, run as a LangGraph state machine with
              checkpoints, budgets and stop rules. Each agent has one job and a short brief built from the study&apos;s
              ledger.
            </p>
          </div>
          <div className="panel solid">
            <span className="tag">✓ the ledger is the truth</span>
            <div className="ptitle">Code verifies</div>
            <p className="small">
              Walk-forward over five blocks. A bar that rises with every look. A two-year holdout opened once by code.
              Every number in the report checked against the ledger.
            </p>
          </div>
          <div className="panel solid" style={{ borderColor: "var(--accent)" }}>
            <span className="tag" style={{ color: "var(--accent-ink)" }}>
              Δ human gate
            </span>
            <div className="ptitle">A person promotes</div>
            <p className="small">
              A study that passes stops at <em>promote?</em> and waits. On real NIFTY data the bench has promoted nothing
              so far, and the replays show why.
            </p>
          </div>
        </div>
      </section>

      {/* one contract */}
      <section style={{ marginTop: 32 }}>
        <div className="eyebrow">
          <span className="idx">ONE CONTRACT</span>
          <span className="gk">μ</span>
          <span className="nm">The same agents, any engine</span>
          <span className="job">MCP tool boundary · the IP stays behind it</span>
        </div>
        <div className="panel">
          <div className="flow wide">
            <div className="flowstep">
              <div className="node sup">Research bench</div>
              <span className="arrow">⇄</span>
            </div>
            <div className="flowstep">
              <div className="node ai">MCP tools</div>
              <span className="arrow">⇄</span>
            </div>
            <div className="flowstep">
              <div className="node">public engine · NIFTY 50 + VIX daily</div>
            </div>
            <div className="flowstep">
              <div className="node dashed">private engine · real options books, aggregates only</div>
            </div>
          </div>
          <p className="small" style={{ marginTop: 12, marginBottom: 0 }}>
            The bench calls the same eight tools in both cases: catalogue, data card, run family, diagnostics,
            neighbourhood, protocol, open holdout and seal log. The engine owns the success test and the holdout seal.
            The private engine runs real backtests in a sandbox and returns only aggregates. Its code and trades never
            leave it.
          </p>
        </div>
      </section>

      {/* track record */}
      <section style={{ marginTop: 32 }}>
        <div className="grid-3">
          <Card
            href="/research-lab/"
            eyebrow="▶ replays"
            title="Research Lab"
            body="Three recorded studies: one rejected at walk-forward, one that passed walk-forward and failed the sealed holdout, and one stopped at the human gate."
          />
          <Card
            href="/track-record/"
            eyebrow="◆ daily"
            title="Backtest record"
            body="Three NIFTY and SENSEX options strategies, daily totals in % from the backtest, refreshed every weekday at 17:00 IST by an AWS Lambda. In-sample, and labelled as such."
            plain
          />
          <Card
            href={REPO}
            eyebrow="⌘ code"
            title="Reproduce it"
            body="Engine, agents, benchmark and infrastructure as code. Clone it, then run one command for a study or for the whole benchmark."
            plain
          />
        </div>
      </section>

      <div className="disc" style={{ marginTop: 22 }}>
        Research software, not investment advice. Results are backtests and synthetic markets; nothing here is live
        trading or a solicitation of funds.
      </div>
    </div>
  );
}

function Card({ href, eyebrow, title, body, plain }: { href: string; eyebrow: string; title: string; body: string; plain?: boolean }) {
  const inner = (
    <>
      <span className="tag">{eyebrow}</span>
      <div className="ptitle" style={{ color: "var(--ink)" }}>
        {title} <span style={{ color: "var(--accent)" }}>→</span>
      </div>
      <p className="small">{body}</p>
    </>
  );
  return plain ? (
    <a href={href} className="panel" style={{ textDecoration: "none", display: "block" }}>
      {inner}
    </a>
  ) : (
    <Link href={href} className="panel" style={{ textDecoration: "none", display: "block" }}>
      {inner}
    </Link>
  );
}
