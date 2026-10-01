"""Build the page-layout dataset from the real arXiv corpus in S3, split 80/10/10 by paper.

    python slm_regime_classifier/build_layout_dataset.py                    # all papers in S3 bronze
    python slm_regime_classifier/build_layout_dataset.py --max-papers 50    # a quick slice
    python slm_regime_classifier/build_layout_dataset.py --no-upload        # keep it local

Source: every ``yantra-corpus/raw/<arxiv-id>.pdf`` the daily ingest job has put in S3 (bronze).
Each PDF is parsed with the ingestion parser (``ingestion/parse.py``), but with tables scanned
on every processed page (the ingest job only scans the first 10), and each page becomes one
row: the one-line feature string, the teacher label (``layout_labels.derive_label``), the paper
and the page. Labels are what the parser saw, not human annotation (see layout_labels.py).

Split: by paper, never by page, so no paper has pages on both sides. The split is a hash of
the paper id (``split_of``), so adding papers later never moves an existing paper between
splits. train 80 / val 10 / test 10. ``test`` is the locked set: report it once per model.

Caching: the per-paper features are written to ``ml/silver/layout_features/<parser tag>/`` in
S3, so a rebuild (or the next session on a fresh box) reads them instead of re-parsing.
Parsing is bounded by ``--cap-minutes``: papers are processed in a fixed shuffled order and
the run stops starting new papers at the cap; the manifest lists exactly which papers made it.

Output (local ``slm_regime_classifier/datasets/<version>/``, git-ignored, and the same files
under ``s3://<bucket>/ml/datasets/layout/<version>/``): ``train.jsonl``, ``val.jsonl``,
``test.jsonl`` and ``manifest.json`` (paper ids per split, label counts, file sha256s, parser
settings, git sha). ``<version>`` is the first 12 hex chars of a hash over the three files.

Needs boto3 and pymupdf, and AWS credentials that can read ``yantra-corpus/*`` and write
``ml/*`` (on the dev box: the instance role). Pure helpers (split, counts) are stdlib-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

BUCKET = os.environ.get("DATA_BUCKET", "yantra-research-lab-data")
RAW_PREFIX = "yantra-corpus/raw/"
ML_PREFIX = "ml/"
OUT = HERE / "datasets"
SPLITS = (("train", 80), ("val", 90), ("test", 100))   # cumulative percent buckets
SPLIT_SALT = "layout-v1"


def split_of(paper_id: str, salt: str = SPLIT_SALT) -> str:
    """Stable split for one paper: a hash bucket 0..99, so new papers never move old ones."""
    bucket = int(hashlib.sha256(f"{salt}:{paper_id}".encode()).hexdigest(), 16) % 100
    return next(name for name, upper in SPLITS if bucket < upper)


def parser_tag(max_pages: int) -> str:
    return f"pymupdf-p{max_pages}-tables-all"


def label_counts(rows: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(r["label"] for r in rows).items()))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


class _NullStorage:
    """parse_pdf saves embedded images to storage; the dataset needs only their sizes."""

    def put_bytes(self, key: str, data: bytes) -> None:
        pass

    def uri(self, key: str) -> str:
        return f"null://{key}"


def _paper_rows(paper_id: str, max_pages: int) -> list[dict]:
    """Download one PDF, parse it, return one row per page. Runs in a worker process."""
    import boto3
    from botocore.exceptions import ClientError

    from ingestion import config
    from ingestion.layout_labels import derive_label, feature_string, page_features
    from ingestion.parse import parse_pdf
    from ingestion.state import FetchedDoc, SourceDoc

    s3 = boto3.client("s3")
    cache_key = f"{ML_PREFIX}silver/layout_features/{parser_tag(max_pages)}/{paper_id}.json"
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=cache_key)["Body"].read())
    except ClientError as e:
        # A missing key reads as 403, not 404, unless s3:ListBucket is granted without a prefix
        # condition; the role's list grant is prefix-scoped, so treat both as "not cached yet".
        if e.response["Error"]["Code"] not in ("NoSuchKey", "404", "AccessDenied", "403"):
            raise

    config.MAX_PAGES = max_pages
    config.TABLE_SCAN_MAX_PAGES = max_pages if max_pages else 10**6
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / f"{paper_id}.pdf"
        s3.download_file(BUCKET, f"{RAW_PREFIX}{paper_id}.pdf", str(pdf))
        src = SourceDoc(id=paper_id, title=paper_id, pdf_url=f"https://arxiv.org/pdf/{paper_id}")
        fetched = FetchedDoc(source=src, local_path=str(pdf), sha256=_sha256(pdf), n_bytes=pdf.stat().st_size)
        parsed = parse_pdf(fetched, _NullStorage())
    rows = [{"paper": paper_id, "page": f.page, "features": feature_string(f), "label": derive_label(f),
             "raw": {k: v for k, v in f.to_dict().items() if k != "snippet"}}
            for f in page_features(parsed)]
    s3.put_object(Bucket=BUCKET, Key=cache_key, Body=json.dumps(rows).encode())
    return rows


def _worker(args: tuple[str, int]) -> tuple[str, list[dict] | None, str]:
    paper_id, max_pages = args
    try:
        return paper_id, _paper_rows(paper_id, max_pages), ""
    except Exception as e:  # noqa: BLE001 - one bad PDF must not sink the build; it is reported
        return paper_id, None, f"{type(e).__name__}: {e}"


def list_papers() -> list[str]:
    import boto3

    pages = boto3.client("s3").get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=RAW_PREFIX)
    return sorted(o["Key"][len(RAW_PREFIX):-4] for p in pages for o in p.get("Contents", [])
                  if o["Key"].endswith(".pdf"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python slm_regime_classifier/build_layout_dataset.py")
    ap.add_argument("--max-papers", type=int, default=0, help="0 = every paper in S3 bronze")
    ap.add_argument("--max-pages", type=int, default=20, help="pages parsed per paper (0 = all)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--cap-minutes", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=0, help="order in which papers are parsed")
    ap.add_argument("--no-upload", action="store_true", help="do not copy the dataset to S3")
    args = ap.parse_args(argv)

    from multiprocessing import Pool

    papers = list_papers()
    random.Random(args.seed).shuffle(papers)
    if args.max_papers:
        papers = papers[:args.max_papers]
    print(f"{len(papers)} papers from s3://{BUCKET}/{RAW_PREFIX} · {args.workers} workers · "
          f"max {args.max_pages or 'all'} pages each · cap {args.cap_minutes:.0f} min", flush=True)

    t0, done, failed, capped = time.monotonic(), {}, {}, False
    with Pool(args.workers) as pool:
        for i, (pid, rows, err) in enumerate(
                pool.imap_unordered(_worker, [(p, args.max_pages) for p in papers]), 1):
            if rows is None:
                failed[pid] = err
            else:
                done[pid] = rows
            if i % 25 == 0:
                print(f"  {i}/{len(papers)} papers · {sum(map(len, done.values()))} pages · "
                      f"{time.monotonic() - t0:.0f}s", flush=True)
            if time.monotonic() - t0 > args.cap_minutes * 60:
                capped = True
                pool.terminate()
                break
    if capped:
        print(f"STOPPED at the {args.cap_minutes:.0f}-minute cap: {len(done)} of {len(papers)} papers parsed")
    if not done:
        first = next(iter(failed.items()), ("-", "no papers listed"))
        print(f"FAILED: no paper parsed ({len(failed)} failed). First error, {first[0]}: {first[1]}")
        return 1

    by_split: dict[str, list[dict]] = {name: [] for name, _ in SPLITS}
    for pid in sorted(done):
        by_split[split_of(pid)].extend(sorted(done[pid], key=lambda r: r["page"]))

    tmp_dir = OUT / "_building"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, rows in by_split.items():
        path = tmp_dir / f"{name}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        files[name] = _sha256(path)
    version = hashlib.sha256("".join(files[n] for n, _ in SPLITS).encode()).hexdigest()[:12]

    manifest = {
        "version": version, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": _git_sha(),
        "source": f"s3://{BUCKET}/{RAW_PREFIX}", "papers_listed": len(papers), "papers_parsed": len(done),
        "papers_failed": failed, "capped": capped, "parser": parser_tag(args.max_pages),
        "max_pages": args.max_pages, "split": {"method": "sha256(salt:paper_id) % 100",
                                               "salt": SPLIT_SALT, "buckets": dict(SPLITS)},
        "label_rule": "ingestion.layout_labels.derive_label", "files_sha256": files,
        "splits": {name: {"papers": sorted({r["paper"] for r in rows}), "pages": len(rows),
                          "labels": label_counts(rows)} for name, rows in by_split.items()},
    }
    (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    final = OUT / version
    if final.exists():
        import shutil
        shutil.rmtree(tmp_dir)
    else:
        tmp_dir.rename(final)

    print(f"\ndataset {version}: {len(done)} papers ({len(failed)} failed), "
          f"{sum(len(r) for r in by_split.values())} pages · {time.monotonic() - t0:.0f}s")
    for name, rows in by_split.items():
        info = manifest["splits"][name]
        print(f"  {name:<5} {len(info['papers']):>4} papers {info['pages']:>6} pages  {info['labels']}")

    if not args.no_upload:
        import boto3

        s3 = boto3.client("s3")
        for f in sorted(final.iterdir()):
            s3.upload_file(str(f), BUCKET, f"{ML_PREFIX}datasets/layout/{version}/{f.name}")
        print(f"uploaded to s3://{BUCKET}/{ML_PREFIX}datasets/layout/{version}/")
    print(f"local: {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
