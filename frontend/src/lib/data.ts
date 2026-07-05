import { promises as fs } from "fs";
import path from "path";
import type { IngestionManifest, PerformanceData, RunData } from "./types";

// Server-side loaders. These read the static JSON in public/data at build/render
// time (the owner overwrites those files with real cached data). No backend calls.

async function readJson<T>(file: string): Promise<T> {
  const full = path.join(process.cwd(), "public", "data", file);
  const raw = await fs.readFile(full, "utf-8");
  return JSON.parse(raw) as T;
}

export function getRun(): Promise<RunData> {
  return readJson<RunData>("run.json");
}

export function getPerformance(): Promise<PerformanceData> {
  return readJson<PerformanceData>("performance.json");
}

export function getIngestion(): Promise<IngestionManifest> {
  return readJson<IngestionManifest>("ingestion.json");
}
