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

// ---- Strategy books --------------------------------------------------------
import type { Book, BooksIndex, RiskGatesData } from "./types";

export function getBooksIndex(): Promise<BooksIndex> {
  return readJson<BooksIndex>("books/index.json");
}

export function getBook(id: string): Promise<Book> {
  return readJson<Book>(`books/${id}.json`);
}

/** All books listed in index.json (unlisted ones are skipped), keyed by id. */
export async function getAllBooks(): Promise<Record<string, Book>> {
  const idx = await getBooksIndex();
  const ids = idx.products.flatMap((p) => p.books);
  const books = await Promise.all(ids.map(getBook));
  return Object.fromEntries(books.map((b) => [b.id, b]));
}

export function getRiskGates(): Promise<RiskGatesData> {
  return readJson<RiskGatesData>("books/risk_gates.json");
}
