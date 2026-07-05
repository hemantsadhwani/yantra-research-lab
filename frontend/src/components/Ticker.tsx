// Decorative ticker tape. Every figure here is a fake placeholder — not market data.
const ITEMS = [
  { label: "NIFTY", value: "24,812.30", cls: "g", suffix: "▲0.42%" },
  { label: "α", value: "0.86", labelCls: "a" },
  { label: "σ", value: "12.1", labelCls: "a" },
  { label: "AGENTS", value: "3", cls: "g", suffix: "paper" },
  { label: "RUN", value: "#42", suffix: "· budget 60%" },
  { label: "LEAK-RATE", value: "0.0%", cls: "g" },
  { label: "CAPTURE·f", value: "≈0.N", cls: "a" },
  { label: "PAPER P&L·MTD", value: "+N.N%", cls: "g" },
];

function Row({ hidden }: { hidden?: boolean }) {
  return (
    <>
      {ITEMS.map((it, i) => (
        <span className="tk" key={`${hidden ? "b" : "a"}-${i}`} aria-hidden={hidden}>
          {it.labelCls ? <span className={it.labelCls}>{it.label}</span> : it.label}{" "}
          <b>{it.value}</b>
          {it.suffix ? <span className={it.cls}> {it.suffix}</span> : null}
        </span>
      ))}
    </>
  );
}

export default function Ticker() {
  return (
    <div className="ticker" role="marquee" aria-label="Placeholder market ticker (simulated values)">
      <div className="tk-track">
        <Row />
        <Row hidden />
      </div>
    </div>
  );
}
