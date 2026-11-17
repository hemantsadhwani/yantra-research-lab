import { promises as fs } from "fs";
import path from "path";

// public/data/bench.json is written by scripts/export_bench_replays.py from real research-bench
// runs (public data only) and from results/planted_benchmark_*.json. Read at build time.

export type Family = {
  id: string;
  template: string;
  trials: number;
  in_sample_sharpe: number;
  oos_sharpe: number;
  positive_folds: number;
  passed_walk_forward: boolean;
  buy_hold_oos_sharpe: number;
  best_params: Record<string, number>;
};

export type Round = {
  round: number;
  by: string;
  diagnosis: string;
  hypothesis: string;
  experiments: { template: string; params: Record<string, number[]>; rationale: string }[];
  families: Family[];
  refused_by_code: string[];
  critic: { verdict: string; concerns: string[] } | null;
};

export type Study = {
  id: string;
  idea: string;
  source: string;
  source_label: string;
  dataset: { rows: number; start: string; end: string; sha256: string; passed: boolean };
  spec: { style: string; summary: string };
  plan: { hypothesis: string; templates: string[]; trial_budget: number; rounds: number; rationale: string };
  plan_review: { approve: boolean; changes: string } | null;
  plan_revisions: number;
  rounds: Round[];
  stop_reason: string;
  verdict: { decision: string; reason: string; family: string | null; required_oos_sharpe: number; agent_failures?: number };
  holdout: { sharpe: number; return_pct: number; buy_hold_sharpe: number; passed: boolean; window: string[] } | null;
  trials: number;
  looks: number;
  report: { title: string; summary: string; findings: string[]; verdict: string } | null;
  report_check: { unsupported_numbers: string[]; passed: boolean } | null;
  spend: { usd: number; calls: number; by_role: Record<string, { calls: number; usd: number; model: string }> };
  seconds: number;
  human: string | null;
};

export type Arm = {
  label: string;
  edges: string;
  noise: string;
  trials: number;
  usd: number;
  median_seconds: number | null;
  file: string | null;
};

export type BenchData = { studies: Study[]; benchmark: { markets: string; arms: Arm[] } };

export async function getBench(): Promise<BenchData> {
  const raw = await fs.readFile(path.join(process.cwd(), "public", "data", "bench.json"), "utf-8");
  return JSON.parse(raw) as BenchData;
}

/** The headline arm (LLM agents v2) and the full-grid protocol arm it is compared with. */
export function headline(b: BenchData) {
  const arms = b.benchmark.arms;
  const v2 = arms.find((a) => a.label === "LLM agents v2")!;
  const grid = arms.find((a) => a.label.startsWith("Grid search + walk-forward"))!;
  const naive = arms[0];
  return { v2, grid, naive, fewer: Math.round(grid.trials / v2.trials), perStudy: v2.usd / 20 };
}

export const REPO = "https://github.com/hemantsadhwani/yantra-research-lab";
