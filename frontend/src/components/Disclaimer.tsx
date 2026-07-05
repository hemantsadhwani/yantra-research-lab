export const PERF_LABEL =
  "Simulation / educational · backtest not live-executed · % summed, not compounded · no performance promises.";

export const PAPER_LABEL = "ALL PAPER / SIMULATED — educational, not investment advice";

export function Disclaimer({
  children,
  strong,
}: {
  children: React.ReactNode;
  strong?: boolean;
}) {
  return <div className={`disc${strong ? " strong" : ""}`}>{children}</div>;
}

/** The mandatory labels that must sit near any performance number. */
export function PerfLabels() {
  return (
    <div className="disc" style={{ marginTop: 10 }}>
      {PERF_LABEL}
    </div>
  );
}
