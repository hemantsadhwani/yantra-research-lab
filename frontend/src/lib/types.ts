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
  tables: number;
  has_math: boolean;
  ocr_used: boolean;
  chunks_indexed: number;
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
    tables: number;
    with_math: number;
    indexed: number;
    spent_usd: number;
    duration_s: number;
  };
  rejects_by_reason: Record<string, number>;
  budget_usd: number;
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
