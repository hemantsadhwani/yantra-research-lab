"""Build ``track_record.json``: locally, or as the daily Lambda.

    python -m track_record.build --feed-dir <public_feed folder> --out site/data/track_record.json
    python -m track_record.build --feed-s3 <bucket> [--prefix public_feed/] --out ...
    python -m track_record.build --ledger-dir <folder of ledger *.csv> --out ...   (live, private)

The public page shows the BACKTEST feed. The trading system exports it after its daily
backtest update (``tools/export_public_feed.py`` in the private repo): one CSV per strategy
(``date, n_trades, day_pnl_pct, wins``) plus ``manifest.json``, under one S3 prefix.

The Lambda (``handler``) runs at 17:00 IST on weekdays. Its role can read that one prefix and
write one object in the site bucket, nothing else. boto3 is imported only on the S3 path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from track_record.ledger import STRATEGIES, backtest_record, read_csv, track_record

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FEED_FILES = {s["id"]: f"{s['id'].replace('-', '_')}.csv" for s in STRATEGIES}


def now_ist() -> str:
    return dt.datetime.now(IST).isoformat(timespec="minutes")


def s3_client(client=None):
    if client is None:
        import boto3
        client = boto3.client("s3")
    return client


def s3_text(client, bucket: str, key: str) -> str:
    return client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")


# ---------- backtest feed (public) ----------
def feed_from_dir(folder: Path) -> tuple[dict[str, str], dict]:
    books = {sid: (folder / name).read_text(encoding="utf-8") for sid, name in FEED_FILES.items()}
    return books, json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def feed_from_s3(bucket: str, prefix: str, client=None) -> tuple[dict[str, str], dict]:
    client = s3_client(client)
    books = {sid: s3_text(client, bucket, prefix + name) for sid, name in FEED_FILES.items()}
    return books, json.loads(s3_text(client, bucket, prefix + "manifest.json"))


def feed_document(books: dict[str, str], manifest: dict) -> dict:
    return backtest_record(books, manifest.get("generated_at") or now_ist())


# ---------- live ledger (private screen-share) ----------
def rows_from_dir(folder: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for f in sorted(folder.glob("*.csv")):
        rows += read_csv(f.read_text(encoding="utf-8"))
    return rows


def rows_from_s3(bucket: str, prefix: str, client=None) -> list[dict[str, str]]:
    client = s3_client(client)
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    keys = sorted(o["Key"] for p in pages for o in p.get("Contents", []))
    rows: list[dict[str, str]] = []
    for key in keys:
        # only the ledger files directly under the prefix: nifty_YYYY-MM.csv, sensex_YYYY-MM.csv
        if key.endswith(".csv") and "/" not in key[len(prefix):]:
            rows += read_csv(s3_text(client, bucket, key))
    return rows


def to_json(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False)


def handler(event: dict, context: object, client=None) -> dict:
    client = s3_client(client)
    books, manifest = feed_from_s3(os.environ["FEED_BUCKET"], os.environ["FEED_PREFIX"], client)
    doc = feed_document(books, manifest)
    client.put_object(Bucket=os.environ["SITE_BUCKET"],
                      Key=os.environ.get("SITE_KEY", "data/track_record.json"),
                      Body=to_json(doc).encode("utf-8"),
                      ContentType="application/json", CacheControl="max-age=300")
    return {"kind": doc["kind"], "as_of": doc["as_of"], "updated": doc["generated_at"],
            "days": {s["id"]: s["summary"]["days_traded"] for s in doc["strategies"]}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--feed-dir", type=Path, help="local copy of the public_feed/ prefix")
    src.add_argument("--feed-s3", metavar="BUCKET", help="read the feed from S3")
    src.add_argument("--ledger-dir", type=Path, help="live ledger CSVs (private use)")
    ap.add_argument("--prefix", default="public_feed/")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.ledger_dir:
        doc = track_record(rows_from_dir(a.ledger_dir), now_ist())
    else:
        books, manifest = feed_from_dir(a.feed_dir) if a.feed_dir else feed_from_s3(a.feed_s3, a.prefix)
        doc = feed_document(books, manifest)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(to_json(doc), encoding="utf-8")
    print(f"wrote {a.out}: {doc['kind']}, {doc['first_day']} to {doc['as_of']}, "
          + ", ".join(f"{s['id']} {s['summary']['days_traded']}d/{s['summary']['trades']}t"
                      for s in doc["strategies"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
