"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PerfLabels } from "@/components/Disclaimer";
import type {
  Book,
  BooksIndex,
  MonthPoint,
  ProductDef,
  RiskGateRow,
  RiskGatesData,
} from "@/lib/types";

const GATES_TAB = "risk-gates";

/* ---- formatting helpers -------------------------------------------------- */

/** Indian digit grouping: 2214089 -> 22,14,089 */
function inrGroup(n: number): string {
  const neg = n < 0;
  const s = String(Math.round(Math.abs(n)));
  let out: string;
  if (s.length <= 3) {
    out = s;
  } else {
    const tail = s.slice(-3);
    let head = s.slice(0, -3);
    const parts: string[] = [];
    while (head.length > 2) {
      parts.unshift(head.slice(-2));
      head = head.slice(0, -2);
    }
    if (head) parts.unshift(head);
    out = `${parts.join(",")},${tail}`;
  }
  return `${neg ? "−" : ""}₹${out}`;
}

/** Signed number with a real minus sign, fixed decimals. */
function signed(n: number, digits = 2): string {
  const body = Math.abs(n).toFixed(digits);
  if (n > 0) return `+${body}`;
  if (n < 0) return `−${body}`;
  return body;
}

function signedPct(n: number, digits = 0): string {
  const sign = n < 0 ? "−" : n > 0 ? "+" : "";
  return `${sign}${Math.abs(n).toFixed(digits)}%`;
}

function toneOf(n: number): "up" | "down" | "" {
  return n > 0 ? "up" : n < 0 ? "down" : "";
}

function toneColor(n: number): string {
  return n > 0 ? "var(--up)" : n < 0 ? "var(--down)" : "var(--muted)";
}

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2025-10" -> "Oct 25" */
function shortMonth(month: string): string {
  const [y, m] = month.split("-");
  const name = MONTH_ABBR[Number(m) - 1] ?? m;
  return `${name} ${(y ?? "").slice(2)}`;
}

function pctOf(part: number, whole: number): string {
  if (!whole) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}

/* ---- small presentational pieces ---------------------------------------- */

function Tile({ k, v, sub, tone }: { k: string; v: string; sub?: string; tone?: number }) {
  const cls = tone === undefined ? "" : toneOf(tone);
  return (
    <div className="sx-tile">
      <span className="k">{k}</span>
      <span className={`v mono${cls ? ` ${cls}` : ""}`}>{v}</span>
      {sub && <span className="sub mono">{sub}</span>}
    </div>
  );
}

function SubHead({ children }: { children: React.ReactNode }) {
  return <div className="sx-subhead">{children}</div>;
}

/* ---- charts (inline SVG, no library) ------------------------------------ */

function CumulativeChart({ monthly }: { monthly: MonthPoint[] }) {
  const W = 620;
  const H = 170;
  const PAD_X = 8;
  const PAD_T = 14;
  const PAD_B = 14;

  // running total after each month, seeded at zero
  const cum: number[] = [];
  let running = 0;
  for (const m of monthly) {
    running += m.pnl_points;
    cum.push(running);
  }
  const values = [0, ...cum];
  const hi = Math.max(...values);
  const lo = Math.min(...values);
  const span = hi - lo || 1;

  const innerW = W - PAD_X * 2;
  const innerH = H - PAD_T - PAD_B;
  const x = (i: number) =>
    PAD_X + (values.length === 1 ? innerW / 2 : (i / (values.length - 1)) * innerW);
  const y = (v: number) => PAD_T + innerH - ((v - lo) / span) * innerH;

  const line = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");
  const zeroY = y(0);
  const lastX = x(values.length - 1);
  const area = `${line} L${lastX.toFixed(1)},${zeroY.toFixed(1)} L${x(0).toFixed(1)},${zeroY.toFixed(1)} Z`;
  const last = values[values.length - 1];
  const tone = toneColor(last);

  return (
    <div className="sx-chart">
      <span className="tag">cumulative P&amp;L &middot; points</span>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Cumulative profit and loss across ${monthly.length} months, ending at ${signed(
          last
        )} points`}
      >
        <path d={area} fill={last < 0 ? "var(--down-soft)" : "var(--up-soft)"} />
        <line x1={PAD_X} x2={W - PAD_X} y1={zeroY} y2={zeroY} stroke="var(--line-strong)" strokeWidth={1} />
        <path d={line} fill="none" stroke={tone} strokeWidth={2} strokeLinejoin="round" />
        <circle cx={lastX} cy={y(last)} r={3.5} fill={tone} />
      </svg>
      <div className="sx-axis mono">
        {monthly.map((m) => (
          <span key={m.month}>{shortMonth(m.month)}</span>
        ))}
      </div>
    </div>
  );
}

function MonthlyBars({ monthly }: { monthly: MonthPoint[] }) {
  const W = 620;
  const H = 170;
  const PAD_T = 18;
  const PAD_B = 18;
  const innerH = H - PAD_T - PAD_B;

  const hi = Math.max(0, ...monthly.map((m) => m.pnl_points));
  const lo = Math.min(0, ...monthly.map((m) => m.pnl_points));
  const span = hi - lo || 1;
  const zeroY = PAD_T + innerH - ((0 - lo) / span) * innerH;

  const slot = W / Math.max(monthly.length, 1);
  const barW = Math.min(slot * 0.62, 44);

  const best = monthly.reduce((a, b) => (b.pnl_points > a.pnl_points ? b : a), monthly[0]);
  const worst = monthly.reduce((a, b) => (b.pnl_points < a.pnl_points ? b : a), monthly[0]);

  return (
    <div className="sx-chart">
      <span className="tag">P&amp;L by month &middot; points</span>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Profit and loss by month. Best ${shortMonth(best.month)} at ${signed(
          best.pnl_points
        )} points, worst ${shortMonth(worst.month)} at ${signed(worst.pnl_points)} points`}
      >
        {monthly.map((m, i) => {
          const v = m.pnl_points;
          const h = Math.max((Math.abs(v) / span) * innerH, 1);
          const yTop = v >= 0 ? zeroY - h : zeroY;
          const cx = i * slot + slot / 2;
          const labelled = m.month === best.month || m.month === worst.month;
          return (
            <g key={m.month}>
              <rect
                x={cx - barW / 2}
                y={yTop}
                width={barW}
                height={h}
                rx={2}
                fill={v < 0 ? "var(--down)" : "var(--up)"}
                opacity={labelled ? 1 : 0.7}
              />
              {labelled && (
                <text
                  x={cx}
                  y={v >= 0 ? yTop - 5 : yTop + h + 13}
                  textAnchor="middle"
                  fontSize={11}
                  fill={v < 0 ? "var(--down)" : "var(--up)"}
                >
                  {signed(v, 0)}
                </text>
              )}
            </g>
          );
        })}
        <line x1={0} x2={W} y1={zeroY} y2={zeroY} stroke="var(--line-strong)" strokeWidth={1} />
      </svg>
      <div className="sx-axis mono">
        {monthly.map((m) => (
          <span key={m.month}>{shortMonth(m.month)}</span>
        ))}
      </div>
    </div>
  );
}

function SeriesPending() {
  return (
    <div className="sx-pending">
      <span className="tag">series pending</span>
      <p>
        Monthly &amp; daily series pending export — the headline numbers above are transcribed
        from the monthly report. Run <code>scripts/export_books.py</code> in the private repo to
        fill these charts. Nothing synthetic is drawn here, on purpose.
      </p>
    </div>
  );
}

/* ---- selected book ------------------------------------------------------ */

function BookView({ book, disclaimer }: { book: Book; disclaimer: string }) {
  const h = book.headline;
  const c = book.cost;
  const s = book.sizing;
  const hasSeries = !book.series_pending && book.monthly.length > 0;

  const sizingRows: [string, string][] = [
    ["Per leg", inrGroup(s.per_leg_inr)],
    ["Lot", String(s.lot)],
    ["Lots per leg", `${s.lots_per_leg_min}–${s.lots_per_leg_max}`],
    ["Avg deployed", inrGroup(s.avg_deployed_inr)],
    ["Peak reserve", inrGroup(s.peak_reserve_inr)],
    ["Net P&L", inrGroup(s.net_pnl_inr)],
    ["Slippage", s.slippage_pct_per_trade === null ? "—" : `${s.slippage_pct_per_trade}%/trade`],
  ];

  return (
    <div className="sx-book">
      <p className="sx-blurb">{book.blurb}</p>

      <div className="sx-tiles">
        <Tile
          k="book P&L"
          v={`${signed(h.pnl_points)} pts`}
          sub={`${h.trades} trades · ${h.sessions} sessions`}
          tone={h.pnl_points}
        />
        <Tile k="win rate" v={`${h.win_rate_pct.toFixed(1)}%`} sub={`${h.wins}W / ${h.losses}L`} />
        <Tile
          k="per trade"
          v={signed(h.per_trade_points)}
          sub={`${signed(h.per_session_points)} per session`}
          tone={h.per_trade_points}
        />
        <Tile k="months up" v={`${h.months_up}/${h.months_traded}`} sub="of the months it traded" />
      </div>

      <PerfLabels />
      <div className="disc" style={{ marginTop: 8 }}>
        {disclaimer}
      </div>

      <div className="sx-charts">
        {hasSeries ? (
          <>
            <CumulativeChart monthly={book.monthly} />
            <MonthlyBars monthly={book.monthly} />
          </>
        ) : (
          <SeriesPending />
        )}
      </div>

      <SubHead>What it costs</SubHead>
      <div className="sx-tiles">
        <Tile
          k="worst day"
          v={signed(c.worst_day_points)}
          sub={inrGroup(c.worst_day_inr)}
          tone={c.worst_day_points}
        />
        <Tile
          k="max drawdown"
          v={signed(c.max_drawdown_points)}
          sub={inrGroup(c.max_drawdown_inr)}
          tone={c.max_drawdown_points}
        />
        <Tile
          k="best day"
          v={signed(c.best_day_points)}
          sub={inrGroup(c.best_day_inr)}
          tone={c.best_day_points}
        />
        <Tile
          k="days up"
          v={`${c.days_up}/${c.days_traded}`}
          sub={`${pctOf(c.days_up, c.days_traded)} of traded days`}
        />
      </div>
      <span className="caption sx-gateline">
        Day gate: M2M halt at {signedPct(c.day_gate_pct)} of the book&apos;s own base
      </span>

      <SubHead>Sizing</SubHead>
      <div className="scroll">
        <table className="sx-sizing mono">
          <tbody>
            {sizingRows.map(([k, v]) => (
              <tr key={k}>
                <th scope="row">{k}</th>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="sx-callout">
        <p>
          <strong>Top 5 trades are {h.top5_share_pct}% of this book.</strong> Concentration is
          stated rather than smoothed: a stretch without one of them reads flat.
        </p>
        {book.caveat && <p className="sx-caveat">{book.caveat}</p>}
      </div>
    </div>
  );
}

/* ---- per-product comparison --------------------------------------------- */

function CompareTable({ books }: { books: Book[] }) {
  return (
    <div className="scroll">
      <table className="pva sx-compare">
        <thead>
          <tr>
            <th>book</th>
            <th>status</th>
            <th>P&amp;L pts</th>
            <th>win rate</th>
            <th>trades</th>
            <th>max DD</th>
            <th>months up</th>
          </tr>
        </thead>
        <tbody>
          {books.map((b) => (
            <tr key={b.id}>
              <td>{b.label}</td>
              <td>
                <span className={`chip ${b.status === "LIVE" ? "acc" : "paper"}`}>{b.status}</span>
              </td>
              <td style={{ color: toneColor(b.headline.pnl_points) }}>
                {signed(b.headline.pnl_points)}
              </td>
              <td>{b.headline.win_rate_pct.toFixed(1)}%</td>
              <td>{b.headline.trades}</td>
              <td style={{ color: toneColor(b.cost.max_drawdown_points) }}>
                {signed(b.cost.max_drawdown_points)}
              </td>
              <td>
                {b.headline.months_up}/{b.headline.months_traded}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---- risk gates --------------------------------------------------------- */

function groupByProfile(rows: RiskGateRow[]): { profile: string; rows: RiskGateRow[] }[] {
  const order: string[] = [];
  const map = new Map<string, RiskGateRow[]>();
  for (const r of rows) {
    if (!map.has(r.profile)) {
      map.set(r.profile, []);
      order.push(r.profile);
    }
    map.get(r.profile)!.push(r);
  }
  return order.map((profile) => ({ profile, rows: map.get(profile)! }));
}

function RiskGatesPanel({ data }: { data: RiskGatesData }) {
  const groups = useMemo(() => groupByProfile(data.armed), [data.armed]);

  return (
    <div className="sx-gates">
      <p className="sx-blurb">
        Automatic stops sit above the strategy and watch different stretches of time. Only one of
        them can interrupt a day already running.
      </p>

      <SubHead>How to read any threshold</SubHead>
      <div className="sx-terms">
        {data.how_to_read.map((t) => (
          <div key={t.term} className="sx-term">
            <span className="t mono">{t.term}</span>
            <span className="m">{t.meaning}</span>
          </div>
        ))}
      </div>

      <SubHead>What each profile puts at risk</SubHead>
      <div className="scroll">
        <table className="pva">
          <thead>
            <tr>
              <th>profile</th>
              <th>M2M base</th>
              <th>sizes</th>
              <th>armed gates</th>
            </tr>
          </thead>
          <tbody>
            {data.profiles.map((p) => (
              <tr key={p.profile}>
                <td>{p.profile}</td>
                <td>{inrGroup(p.m2m_base_inr)}</td>
                <td>{p.sizes}</td>
                <td>{p.armed_gates}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SubHead>Every armed gate, every profile</SubHead>
      <div className="scroll">
        <table className="pva sx-armed">
          <thead>
            <tr>
              <th>profile</th>
              <th>gate</th>
              <th>trips at</th>
              <th>in &#8377;</th>
              <th>checked</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) =>
              g.rows.map((r, i) => (
                <tr key={`${g.profile}::${r.gate}`} className={i === 0 ? "grp" : undefined}>
                  <td>{i === 0 ? g.profile : ""}</td>
                  <td>{r.gate}</td>
                  <td style={{ color: "var(--down)" }}>{signedPct(r.trips_at_pct)}</td>
                  <td style={{ color: "var(--down)" }}>{inrGroup(r.in_inr)}</td>
                  <td>{r.checked}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <SubHead>What each gate actually cancels</SubHead>
      <div className="scroll">
        <table className="pva">
          <thead>
            <tr>
              <th>gate</th>
              <th>counts from</th>
              <th>blocks</th>
              <th>open trades</th>
            </tr>
          </thead>
          <tbody>
            {data.cancels.map((c) => (
              <tr key={c.gate}>
                <td>{c.gate}</td>
                <td>{c.counts_from}</td>
                <td>{c.blocks}</td>
                <td>{c.open_trades}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SubHead>Written in the config, switched off</SubHead>
      <div className="scroll">
        <table className="pva">
          <thead>
            <tr>
              <th>profile</th>
              <th>present but inert</th>
            </tr>
          </thead>
          <tbody>
            {data.inert.map((r) => (
              <tr key={r.profile}>
                <td>{r.profile}</td>
                <td>{r.present_but_inert}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SubHead>The paper sub-books have their own brake</SubHead>
      <div className="scroll">
        <table className="pva">
          <thead>
            <tr>
              <th>profile</th>
              <th>book base</th>
              <th>floor</th>
              <th>floor &#8377;</th>
              <th>worst day</th>
            </tr>
          </thead>
          <tbody>
            {data.paper_brakes.map((p) => (
              <tr key={p.profile}>
                <td>{p.profile}</td>
                <td>{inrGroup(p.book_base_inr)}</td>
                <td style={{ color: "var(--down)" }}>{signedPct(p.floor_pct)}</td>
                <td style={{ color: "var(--down)" }}>{inrGroup(p.floor_inr)}</td>
                <td style={{ color: "var(--down)" }}>{inrGroup(p.worst_day_inr)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SubHead>What this stack will not save you from</SubHead>
      <div className="sx-warns">
        {data.will_not_save_you_from.map((w) => (
          <div key={w.title} className="sx-callout">
            <p>
              <strong>{w.title}</strong>
            </p>
            <p className="sx-caveat">{w.body}</p>
          </div>
        ))}
      </div>

      <span className="caption sx-gateline">Gate configuration as of {data.as_of}.</span>
    </div>
  );
}

/* ---- explorer shell ----------------------------------------------------- */

export default function StrategyExplorer({
  index,
  books,
  riskGates,
}: {
  index: BooksIndex;
  books: Record<string, Book>;
  riskGates: RiskGatesData;
}) {
  const products = index.products;
  const first = products[0];
  const [tab, setTab] = useState<string>(first?.id ?? GATES_TAB);
  const [bookId, setBookId] = useState<string>(first?.books[0] ?? "");
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const tabIds = useMemo(() => [...products.map((p) => p.id), GATES_TAB], [products]);

  // Read the hash once on mount so #nifty-expiry/low-vix links are shareable.
  useEffect(() => {
    const raw = window.location.hash.replace(/^#/, "");
    if (!raw) return;
    const [wantTab, wantBook] = raw.split("/");
    if (wantTab === GATES_TAB) {
      setTab(GATES_TAB);
      return;
    }
    const p = products.find((x) => x.id === wantTab);
    if (!p) return;
    setTab(p.id);
    const hit = wantBook
      ? p.books.find((id) => id === wantBook || id === `${p.id}-${wantBook}`)
      : undefined;
    setBookId(hit ?? p.books[0]);
    // `products` comes from static props; this is intentionally mount-only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const syncHash = useCallback((nextTab: string, nextBook?: string) => {
    const hash = nextTab === GATES_TAB ? `#${GATES_TAB}` : `#${nextTab}/${nextBook ?? ""}`;
    window.history.replaceState(null, "", hash);
  }, []);

  const selectTab = useCallback(
    (id: string) => {
      setTab(id);
      if (id === GATES_TAB) {
        syncHash(id);
        return;
      }
      const p = products.find((x) => x.id === id);
      const nextBook = p?.books.includes(bookId) ? bookId : p?.books[0] ?? "";
      setBookId(nextBook);
      syncHash(id, nextBook);
    },
    [bookId, products, syncHash]
  );

  const selectBook = useCallback(
    (id: string) => {
      setBookId(id);
      syncHash(tab, id);
    },
    [syncHash, tab]
  );

  const onTabKey = (e: React.KeyboardEvent, id: string) => {
    const i = tabIds.indexOf(id);
    let next = -1;
    if (e.key === "ArrowRight") next = (i + 1) % tabIds.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + tabIds.length) % tabIds.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabIds.length - 1;
    if (next < 0) return;
    e.preventDefault();
    const nextId = tabIds[next];
    selectTab(nextId);
    tabRefs.current[nextId]?.focus();
  };

  const product: ProductDef | undefined = products.find((p) => p.id === tab);
  const productBooks = product ? product.books.map((id) => books[id]).filter(Boolean) : [];
  const active = books[bookId] ?? productBooks[0];

  return (
    <div className="sx">
      <div className="sx-tabs" role="tablist" aria-label="Strategy products">
        {[...products.map((p) => ({ id: p.id, name: p.name })), { id: GATES_TAB, name: "Risk gates" }].map(
          (t) => (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[t.id] = el;
              }}
              role="tab"
              id={`sx-tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`sx-panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1}
              className={`sx-tab${tab === t.id ? " on" : ""}`}
              onClick={() => selectTab(t.id)}
              onKeyDown={(e) => onTabKey(e, t.id)}
            >
              {t.name}
            </button>
          )
        )}
      </div>

      {product && (
        <div
          role="tabpanel"
          id={`sx-panel-${product.id}`}
          aria-labelledby={`sx-tab-${product.id}`}
          tabIndex={0}
          className="panel flat sx-panel"
        >
          <p className="sx-tagline">{product.tagline}</p>

          <div className="sx-pills" role="group" aria-label={`${product.name} books`}>
            {productBooks.map((b) => (
              <button
                key={b.id}
                className={`sx-pill${b.id === active?.id ? " on" : ""}`}
                aria-pressed={b.id === active?.id}
                onClick={() => selectBook(b.id)}
              >
                <span>{b.label}</span>
                <span className={`chip ${b.status === "LIVE" ? "acc" : "paper"}`}>{b.status}</span>
              </button>
            ))}
          </div>

          <CompareTable books={productBooks} />

          {active && <BookView book={active} disclaimer={index.disclaimer} />}
        </div>
      )}

      {tab === GATES_TAB && (
        <div
          role="tabpanel"
          id={`sx-panel-${GATES_TAB}`}
          aria-labelledby={`sx-tab-${GATES_TAB}`}
          tabIndex={0}
          className="panel flat sx-panel"
        >
          <RiskGatesPanel data={riskGates} />
        </div>
      )}

      <span className="caption sx-gateline">
        Books as of {index.as_of} &middot; source {index.source_commit} &middot; {index.unit}
      </span>
    </div>
  );
}
