"""Layout-router eval: code vs small model vs frontier model on the same pages, one table.

    python -m eval.layout_eval --fake              # offline (CI): rules is real, slm + frontier are FakeProviders
    python -m eval.layout_eval                     # rules + slm on a local Ollama (fails clearly if it is down)
    python -m eval.layout_eval --with-frontier     # + Haiku 4.5 via llm_gateway (needs a key; costs money)
    python -m eval.layout_eval --dataset bronze    # parse the local bronze PDFs first (caches silver JSON)

Pages: ``--dataset auto`` (default) uses the parsed silver JSON under ``INGEST_DATA_DIR/parsed``
when it holds at least 40 pages, otherwise a deterministic synthetic set of 200 page-feature
records (``layout_labels.synthetic_pages``). Labels always come from the teacher rule
``layout_labels.derive_label`` over the parser's output: free labels, not human annotation.

Columns: accuracy against those labels, agreement with the ``frontier`` row, cost per 1,000
pages (llm_gateway list-price table from token counts; ``rules`` and a local SLM are $0,
hardware excluded) and p50 / p95 latency per page in ms, measured around each ``classify``.

``--fake`` scripts the model rows: the fake SLM returns the rules label with a fixed error rate
(``--slm-error``, default 8%), the fake frontier returns the teacher label with a smaller one
(``--frontier-error``, default 3%). Their accuracy and latency are the harness, not a model;
the fake frontier's cost is Haiku 4.5 list price over the real prompt's token estimate
(chars / 4, schema tokens excluded, so a floor). The ``rules`` row is real in every mode.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
MIN_REAL_PAGES = 40
FAKE_BANNER = "fake providers: proves the harness; the rules backend numbers are real"


# --- pages -------------------------------------------------------------------------------

def _silver_pages():
    from ingestion import config
    from ingestion.layout_labels import page_features
    from ingestion.state import ParsedDoc

    pages = []
    for p in sorted(config.SILVER_DIR.glob("*.json")):
        pages.extend(page_features(ParsedDoc.model_validate_json(p.read_text(encoding="utf-8"))))
    return pages


def parse_bronze() -> int:
    """Parse every local bronze PDF (offline, PyMuPDF) and cache it as silver JSON."""
    from ingestion import config
    from ingestion.parse import parse_pdf
    from ingestion.state import FetchedDoc, SourceDoc
    from ingestion.storage import LocalStorage

    titles = {}
    if config.CATALOG_PATH.exists():
        titles = {d["id"]: d.get("title", d["id"])
                  for d in json.loads(config.CATALOG_PATH.read_text(encoding="utf-8")).get("docs", [])}
    config.SILVER_DIR.mkdir(parents=True, exist_ok=True)
    storage = LocalStorage(config.DATA_DIR)
    n = 0
    for pdf in sorted(config.BRONZE_DIR.glob("*.pdf")):
        doc_id = pdf.stem
        fd = FetchedDoc(source=SourceDoc(id=doc_id, title=titles.get(doc_id, doc_id),
                                         pdf_url=f"https://arxiv.org/pdf/{doc_id}"),
                        local_path=str(pdf), sha256="", n_bytes=pdf.stat().st_size)
        parsed = parse_pdf(fd, storage)
        (config.SILVER_DIR / f"{doc_id}.json").write_text(parsed.model_dump_json(), encoding="utf-8")
        n += 1
    return n


def load_pages(dataset: str):
    """Returns ``(pages, dataset_name)``."""
    from ingestion.layout_labels import synthetic_pages

    if dataset == "bronze":
        n = parse_bronze()
        print(f"parsed {n} bronze PDFs into silver JSON")
        dataset = "silver"
    if dataset in ("auto", "silver"):
        pages = _silver_pages()
        if len(pages) >= MIN_REAL_PAGES:
            return pages, f"silver ({len(pages)} real parsed pages)"
        if dataset == "silver":
            raise SystemExit(f"only {len(pages)} silver pages (< {MIN_REAL_PAGES}); "
                             "run with --dataset bronze or --dataset synthetic")
    pages = synthetic_pages()
    return pages, f"synthetic ({len(pages)} deterministic page-feature records, seed 2026)"


# --- backends ----------------------------------------------------------------------------

def _priced_fake(scripted, name: str, model: str):
    """A FakeProvider whose per-call cost is list price over its own token estimate."""
    from llm_gateway import FakeProvider
    from llm_gateway.pricing import estimate_cost

    class PricedFake(FakeProvider):
        def _resp(self, text, parsed, in_tok, trips, mode):
            r = super()._resp(text, parsed, in_tok, trips, mode)
            r.cost_usd = estimate_cost(self.model, r.input_tokens, r.output_tokens)
            return r

    return PricedFake(scripted, name=name, model=model)


def _noisy(truth: list[str], rate: float, seed: int) -> list[str]:
    from ingestion.layout_labels import LABELS

    rng = random.Random(seed)
    out = []
    for t in truth:
        if rng.random() < rate:
            out.append(rng.choice([lbl for lbl in LABELS if lbl != t]))
        else:
            out.append(t)
    return out


def build_backends(pages, labels, fake: bool, with_frontier: bool, slm_error: float,
                   frontier_error: float):
    from ingestion.layout_router import (
        DEFAULT_SLM_MODEL,
        FRONTIER_MODEL,
        LayoutVerdict,
        RulesClassifier,
        frontier_classifier,
        slm_classifier,
    )

    rules = RulesClassifier()
    backends = [("rules", "thresholds (code)", rules)]
    if fake:
        rules_labels = [rules.classify(f).label for f in pages]
        slm_script = [LayoutVerdict(label=lbl, confidence=0.8)
                      for lbl in _noisy(rules_labels, slm_error, seed=7)]
        fr_script = [LayoutVerdict(label=lbl, confidence=0.9)
                     for lbl in _noisy(labels, frontier_error, seed=11)]
        from llm_gateway import FakeProvider  # a local model: $0, so no pricing row needed

        backends.append(("slm", f"fake {DEFAULT_SLM_MODEL}",
                         slm_classifier(FakeProvider(slm_script, "ollama", DEFAULT_SLM_MODEL))))
        backends.append(("frontier", f"fake {FRONTIER_MODEL}",
                         frontier_classifier(_priced_fake(fr_script, "anthropic", FRONTIER_MODEL))))
        return backends
    slm = slm_classifier()
    backends.append(("slm", slm.provider.model, slm))
    if with_frontier:
        fr = frontier_classifier()
        backends.append(("frontier", fr.provider.model, fr))
    return backends


def run_backend(clf, pages) -> tuple[list[str], list[float], float]:
    preds, lat, cost = [], [], 0.0
    for f in pages:
        t0 = time.perf_counter()
        d = clf.classify(f)
        lat.append((time.perf_counter() - t0) * 1000)
        preds.append(d.label)
        cost += d.cost_usd
    return preds, lat, cost


def _pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def evaluate(pages, backends) -> list[dict]:
    from ingestion.layout_labels import derive_label

    labels = [derive_label(f) for f in pages]
    rows = []
    for name, model, clf in backends:
        preds, lat, cost = run_backend(clf, pages)
        rows.append({
            "backend": name, "model": model, "preds": preds,
            "accuracy": sum(p == t for p, t in zip(preds, labels, strict=True)) / len(pages),
            "cost_per_1k": cost / len(pages) * 1000,
            "p50_ms": statistics.median(lat), "p95_ms": _pct(lat, 0.95),
        })
    frontier = next((r["preds"] for r in rows if r["backend"] == "frontier"), None)
    for r in rows:
        r["agreement"] = (None if frontier is None else
                          sum(a == b for a, b in zip(r["preds"], frontier, strict=True)) / len(pages))
    return rows


def render_table(rows: list[dict]) -> str:
    def ms(x: float) -> str:
        return f"{x:.3f}" if x < 1 else f"{x:.1f}"

    lines = [("| backend | model | accuracy vs labels | agreement with frontier | "
              "cost / 1,000 pages | p50 ms | p95 ms |"),
             "|---|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        agree = "n/a" if r["agreement"] is None else f"{r['agreement']:.2f}"
        lines.append(f"| {r['backend']} | {r['model']} | {r['accuracy']:.2f} | {agree} | "
                     f"${r['cost_per_1k']:.4f} | {ms(r['p50_ms'])} | {ms(r['p95_ms'])} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.layout_eval")
    ap.add_argument("--fake", action="store_true", help="scripted slm + frontier (offline)")
    ap.add_argument("--with-frontier", action="store_true",
                    help="real mode only: add Haiku 4.5 (needs a key, costs money)")
    ap.add_argument("--dataset", choices=("auto", "silver", "bronze", "synthetic"), default="auto")
    ap.add_argument("--slm-error", type=float, default=0.08)
    ap.add_argument("--frontier-error", type=float, default=0.03)
    ap.add_argument("--out", type=Path, help="also write the table as a markdown file")
    args = ap.parse_args(argv)

    from ingestion.layout_labels import derive_label

    pages, dataset = load_pages(args.dataset)
    labels = [derive_label(f) for f in pages]
    backends = build_backends(pages, labels, args.fake, args.with_frontier,
                              args.slm_error, args.frontier_error)
    rows = evaluate(pages, backends)
    table = render_table(rows)
    dist = ", ".join(f"{k} {v}" for k, v in sorted(Counter(labels).items()))

    if args.fake:
        print(f"**{FAKE_BANNER}**\n")
    print(f"pages: {dataset} · labels (teacher rule): {dist}\n")
    print(table)

    if args.out:
        cmd = "python -m eval.layout_eval " + " ".join(argv if argv is not None else sys.argv[1:])
        head = f"**{FAKE_BANNER}**\n\n" if args.fake else ""
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(f"{head}Command: `{cmd.strip()}`\n\nPages: {dataset}\n\n"
                            f"Labels (teacher rule): {dist}\n\n{table}\n", encoding="utf-8")
        print(f"\nwrote {args.out}")

    from eval.mlflow_tracking import track_run

    metrics: dict[str, float] = {"pages": len(pages)}
    for r in rows:
        b = r["backend"]
        metrics.update({f"{b}_accuracy": r["accuracy"], f"{b}_cost_per_1k": r["cost_per_1k"],
                        f"{b}_p50_ms": r["p50_ms"], f"{b}_p95_ms": r["p95_ms"]})
        if r["agreement"] is not None:
            metrics[f"{b}_agreement_frontier"] = r["agreement"]
    track_run("layout_eval", params={"dataset": dataset, "fake": args.fake,
                                     "backends": ",".join(r["backend"] for r in rows)},
              metrics=metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
