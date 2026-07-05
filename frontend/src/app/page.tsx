import Link from "next/link";
import { Disclaimer, PAPER_LABEL } from "@/components/Disclaimer";

const LOOP = [
  { k: "propose", d: "an LLM proposer drafts N strategy variants — some exploit the best-so-far, some explore." },
  { k: "backtest", d: "each variant is backtested on a synthetic engine — no live execution." },
  { k: "judge", d: "an evaluator scores every variant against a fixed baseline." },
  { k: "rank", d: "variants are ranked; the top candidate is surfaced." },
  { k: "remember", d: "what worked is written to memory so the next iteration compounds." },
];

const PILLARS = [
  {
    tag: "Σ propose · backtest · rank",
    title: "A loop, not a script",
    body: "A supervisor coordinates proposer, backtester and evaluator workers over several iterations — the topology is the product.",
  },
  {
    tag: "μ memory that compounds",
    title: "Bounded autonomy",
    body: "Every run is capped by an explicit iteration + variant budget. You pay for autonomy only as far as the budget allows.",
  },
  {
    tag: "Δ guardrails · protects edge",
    title: "Human approval gate",
    body: "Nothing is promoted autonomously. The top variant is surfaced as ‘promote?’ and waits for a human.",
  },
];

export default function LandingPage() {
  return (
    <div>
      <p className="kicker" style={{ marginTop: 24 }}>
        {"// agentic quant · signal desk"}
      </p>
      <h1 className="h1">
        Autonomous <span className="hl">strategy research</span>
        <span className="cursor">▊</span>
      </h1>
      <p className="lede">
        An autonomous loop that <strong>proposes N variants</strong>, backtests each, judges them
        against a baseline, ranks the survivors, and <strong>remembers</strong> what worked —
        iterating under a fixed budget, with a human approval gate before anything is promoted.
      </p>

      <div className="row" style={{ display: "flex", gap: 10, marginTop: 22, flexWrap: "wrap" }}>
        <Link href="/research-lab" className="btn pri">
          Watch the agents work →
        </Link>
        <Link href="/strategies" className="btn">
          Explore strategies
        </Link>
        <Link href="/chat" className="btn">
          Ask the guardrail bot ▚
        </Link>
      </div>

      <div style={{ marginTop: 20 }}>
        <Disclaimer strong>
          {PAPER_LABEL}. Not a solicitation of funds. Every number on this site is a placeholder or
          a simulated result.
        </Disclaimer>
      </div>

      {/* the loop */}
      <section style={{ marginTop: 44 }}>
        <div className="eyebrow">
          <span className="idx">THE LOOP</span>
          <span className="gk">α</span>
          <span className="nm">propose → backtest → judge → rank → remember</span>
          <span className="job">bounded by a budget · human gate before promotion</span>
        </div>
        <div className="panel">
          <div
            className="row"
            style={{
              display: "flex",
              alignItems: "stretch",
              gap: 10,
              flexWrap: "nowrap",
              overflowX: "auto",
            }}
          >
            {LOOP.map((s, i) => (
              <div key={s.k} style={{ display: "flex", alignItems: "stretch", gap: 10 }}>
                <div className="node ai" style={{ minWidth: 150, textAlign: "left" }}>
                  <div style={{ fontWeight: 700 }}>
                    {i + 1}. {s.k}
                  </div>
                  <div style={{ color: "var(--muted)", fontSize: 10.5, whiteSpace: "normal", marginTop: 4 }}>
                    {s.d}
                  </div>
                </div>
                <span className="arrow">{i === LOOP.length - 1 ? "↺" : "→"}</span>
              </div>
            ))}
            <div className="node dashed" style={{ alignSelf: "center" }}>
              Memory
            </div>
          </div>
        </div>
      </section>

      {/* pillars */}
      <section style={{ marginTop: 32 }}>
        <div className="grid-3">
          {PILLARS.map((p) => (
            <div className="panel solid" key={p.tag}>
              <span className="tag">{p.tag}</span>
              <div style={{ fontWeight: 700, marginTop: 10, fontSize: 15 }}>{p.title}</div>
              <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 6, marginBottom: 0 }}>
                {p.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* nav cards */}
      <section style={{ marginTop: 32 }}>
        <div className="grid-3">
          <NavCard
            href="/strategies"
            eyebrow="β · explorer"
            title="Strategy Explorer"
            body="Three paper strategies + a plan-vs-actual capture-factor panel: live ÷ backtest, shown as an honesty feature."
          />
          <NavCard
            href="/research-lab"
            eyebrow="Σ · agentic core"
            title="Research Lab"
            body="The supervisor→proposer→backtester→evaluator pipeline, the budget, the baseline, a ranked-variants table, and the promote? gate."
          />
          <NavCard
            href="/chat"
            eyebrow="Δ · guardrails"
            title="Guardrail Chatbot"
            body="Answers methodology, refuses proprietary IP and protects PII. Leak-rate on screen. Try to break it."
          />
        </div>
      </section>
    </div>
  );
}

function NavCard({
  href,
  eyebrow,
  title,
  body,
}: {
  href: string;
  eyebrow: string;
  title: string;
  body: string;
}) {
  return (
    <Link href={href} className="panel" style={{ textDecoration: "none", display: "block" }}>
      <span className="tag">{eyebrow}</span>
      <div style={{ fontWeight: 700, marginTop: 10, fontSize: 15, color: "var(--ink)" }}>
        {title} <span style={{ color: "var(--accent)" }}>→</span>
      </div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 6, marginBottom: 0 }}>{body}</p>
    </Link>
  );
}
