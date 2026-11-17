import { getBench, headline } from "@/lib/bench";

// Ticker tape of measured facts only, read from public/data/bench.json at build time.
export default async function Ticker() {
  const b = await getBench();
  const h = headline(b);
  const items = [
    { label: "EDGES FOUND", value: h.v2.edges, cls: "g", suffix: "planted benchmark" },
    { label: "NOISE PROMOTED", value: h.v2.noise, cls: "g" },
    { label: "UNGUARDED SEARCH", value: h.naive.noise, cls: "r", suffix: "noise promoted" },
    { label: "TRIALS", value: `${h.fewer}× fewer`, labelCls: "a" },
    { label: "$/STUDY", value: h.perStudy.toFixed(3), labelCls: "a" },
    { label: "HOLDOUT", value: "opened once", suffix: "per study, by code" },
    { label: "MODELS", value: "Gemma 3 12B · DeepSeek V3.2", suffix: "Bedrock ap-south-1" },
    { label: "TRACK RECORD", value: "17:00 IST", suffix: "every weekday" },
  ];
  const row = (hidden?: boolean) =>
    items.map((it, i) => (
      <span className="tk" key={`${hidden ? "b" : "a"}-${i}`} aria-hidden={hidden}>
        {it.labelCls ? <span className={it.labelCls}>{it.label}</span> : it.label} <b>{it.value}</b>
        {it.suffix ? <span className={it.cls}> {it.suffix}</span> : null}
      </span>
    ));
  return (
    <div className="ticker" role="marquee" aria-label="Measured results">
      <div className="tk-track">
        {row()}
        {row(true)}
      </div>
    </div>
  );
}
