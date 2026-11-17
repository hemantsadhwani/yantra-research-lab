import { REPO } from "@/lib/bench";

export default function Footer() {
  return (
    <footer className="sitefooter">
      <p>
        <strong>yantra</strong>: an agentic strategy research platform. Agents decide what to test, code decides what is
        true, a person decides what is promoted. <a href={REPO}>Source, benchmark and infrastructure on GitHub</a>.
      </p>
      <p style={{ marginTop: 10 }}>
        Research software, not investment advice. Results are backtests on public data or synthetic markets, labelled as
        such. No funds are held, moved or managed. Hosted on AWS (S3 + CloudFront, Mumbai).
      </p>
    </footer>
  );
}
