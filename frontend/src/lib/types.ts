// Shared data shapes for the yantra-research-lab frontend.
// NOTE: every number rendered by this app is a PLACEHOLDER / SIMULATED value.

export interface Baseline {
  total_return_pct: number;
  win_rate: number;
  max_drawdown_pct: number;
  trades: number;
  score: number;
}

export interface RankedVariant {
  rank: number;
  variant_id: string;
  parent_id?: string;
  params?: Record<string, number>;
  rationale?: string;
  total_return_pct: number;
  win_rate: number;
  max_drawdown_pct: number;
  sharpe?: number;
  trades: number;
  score: number;
  verdict: string;
}

export interface RunData {
  strategy: string;
  run_id: number;
  iterations: number;
  variants_per_iter: number;
  variants_tested: number;
  baseline: Baseline;
  ranked: RankedVariant[];
  best_variant_id: string;
  hitl: string;
}

export interface StrategyPerf {
  name: string;
  backtest_return_pct: number;
  win_rate: number;
  trades: number;
}

export interface PlanVsActualWeek {
  week: string;
  bt_plan_pct: number;
  live_actual_pct: number;
  realized: number;
  capture_f: number;
}

export interface PerformanceData {
  _note: string;
  disclaimer: string;
  strategies: StrategyPerf[];
  plan_vs_actual: {
    capture_factor: number;
    weeks: PlanVsActualWeek[];
  };
}

// --- Tier-3 ingestion pipeline manifest ---

export interface IngestStage {
  id: string;
  label: string;
  desc: string;
}

export interface IngestDoc {
  id: string;
  title: string;
  source: string;
  pages: number;
  images: number;
  figures_captioned?: number;
  tables: number;
  has_math: boolean;
  ocr_used: boolean;
  chunks_indexed: number;
}

export interface IngestFigure {
  doc_id: string;
  title: string;
  page: number;
  thumb: string;      // public path, e.g. /data/figures/xxx.jpg
  caption: string;    // vision caption (or the paper's printed caption as fallback)
  vision: boolean;    // true if a Claude vision call produced the caption
  source: string;
}

export interface IngestionManifest {
  _note: string;
  run_id: string;
  generated_at: string;
  collection: string;
  embed_model: string;
  dag: IngestStage[];
  stats: {
    discovered: number;
    fetched: number;
    parsed: number;
    chunks: number;
    accepted: number;
    rejected: number;
    images: number;
    figures_captioned?: number;
    tables: number;
    with_math: number;
    indexed: number;
    spent_usd: number;
    duration_s: number;
  };
  rejects_by_reason: Record<string, number>;
  budget_usd: number;
  figures?: IngestFigure[];
  docs: IngestDoc[];
}

// --- Chat API contract ---

export interface ChatSource {
  title: string;
  snippet: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  message: string;
  history: ChatTurn[];
}

export interface ChatResponse {
  answer: string;
  refused: boolean;
  sources: ChatSource[];
  leak_rate: number;
}

// ---------------------------------------------------------------------------
// Strategy books (Strategy Explorer). Real, labeled backtest OUTPUTS exported
// from the private master — never engine parameters or entry/exit logic.
// Units: P&L in "points" (option-premium points, as the monthly reports use),
// with ₹ equivalents where the report gives them. Summed, not compounded.
// ---------------------------------------------------------------------------

export type BookStatus = "LIVE" | "PAPER";
export type Regime = "high_vix" | "low_vix" | "all";

export interface BookHeadline {
  pnl_points: number;
  trades: number;
  sessions: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  per_trade_points: number;
  per_session_points: number;
  months_up: number;
  months_traded: number;
  /** share of book P&L from the top 5 trades — concentration, shown as honesty stat */
  top5_share_pct: number;
}

export interface BookCost {
  worst_day_points: number;
  worst_day_inr: number;
  max_drawdown_points: number;
  max_drawdown_inr: number;
  best_day_points: number;
  best_day_inr: number;
  days_up: number;
  days_traded: number;
  /** daily M2M halt as % of the book's own base capital (negative) */
  day_gate_pct: number;
}

export interface BookSizing {
  per_leg_inr: number;
  lot: number;
  net_pnl_inr: number;
  peak_reserve_inr: number;
  avg_deployed_inr: number;
  lots_per_leg_min: number;
  lots_per_leg_max: number;
  slippage_pct_per_trade: number | null;
}

export interface MonthPoint {
  /** YYYY-MM */
  month: string;
  pnl_points: number;
}

export interface DayPoint {
  /** YYYY-MM-DD */
  date: string;
  pnl_points: number;
}

export interface Book {
  id: string;
  product: string;
  label: string;
  regime: Regime;
  status: BookStatus;
  /** one plain sentence — what the book is, never how it decides */
  blurb: string;
  period: { from: string; to: string };
  headline: BookHeadline;
  cost: BookCost;
  sizing: BookSizing;
  /** empty until scripts/export_books.py has been run in the private repo */
  monthly: MonthPoint[];
  daily: DayPoint[];
  /** true while monthly/daily are still empty — UI must render an honest placeholder, never fake data */
  series_pending: boolean;
  /** one-line caveat lifted from the report footer, if any */
  caveat?: string;
}

export interface ProductDef {
  id: string;
  name: string;
  index: "NIFTY" | "SENSEX";
  session: "weekday" | "expiry";
  tagline: string;
  books: string[];
}

export interface BooksIndex {
  as_of: string;
  source_commit: string;
  unit: string;
  disclaimer: string;
  products: ProductDef[];
  unlisted_books: string[];
}

export interface RiskGateRow {
  profile: string;
  gate: string;
  trips_at_pct: number;
  in_inr: number;
  checked: "every tick" | "startup only";
}

export interface RiskGatesData {
  as_of: string;
  how_to_read: { term: string; meaning: string }[];
  profiles: { profile: string; m2m_base_inr: number; sizes: string; armed_gates: number }[];
  armed: RiskGateRow[];
  cancels: { gate: string; counts_from: string; blocks: string; open_trades: string }[];
  inert: { profile: string; present_but_inert: string }[];
  paper_brakes: { profile: string; book_base_inr: number; floor_pct: number; floor_inr: number; worst_day_inr: number }[];
  will_not_save_you_from: { title: string; body: string }[];
}
