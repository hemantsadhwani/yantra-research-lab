"""Pluggable object storage for the bronze layer (raw PDFs) and extracted images.

One interface, two backends — chosen by env so local dev and cloud/CI share code:
  - ``LocalStorage``  (default): a directory on disk. No credentials.
  - ``S3Storage``     : any S3-API store (AWS S3, or S3-compatible via ``S3_ENDPOINT_URL``
                        for R2/Tigris/MinIO). Activated by setting ``S3_BUCKET``.

Parsers always work on a *local file path*, so ``local_file(key)`` transparently
downloads-and-caches from S3 when needed. This is why swapping local↔S3 is a one-env
change with zero pipeline-code churn.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ingestion import config


class Storage:
    def exists(self, key: str) -> bool: ...
    def put_bytes(self, key: str, data: bytes) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def local_file(self, key: str) -> Path:
        """Return a local filesystem path for ``key`` (downloading/caching if remote)."""
        ...

    def uri(self, key: str) -> str:
        """A stable identifier for lineage (s3://… or file://…). Not necessarily public."""
        ...


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    def put_bytes(self, key: str, data: bytes) -> None:
        self._p(key).write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._p(key).read_bytes()

    def local_file(self, key: str) -> Path:
        return self._p(key)

    def uri(self, key: str) -> str:
        return f"file://{self._p(key)}"


class S3Storage(Storage):
    def __init__(self, bucket: str, prefix: str = "", endpoint_url: Optional[str] = None,
                 region: Optional[str] = None, cache_dir: Optional[Path] = None):
        import boto3  # imported lazily so local runs don't need boto3

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.endpoint_url = endpoint_url
        self._cache = Path(cache_dir or (config.DATA_DIR / "s3cache"))
        self._cache.mkdir(parents=True, exist_ok=True)
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    def _k(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._k(key))
            return True
        except ClientError:
            return False

    def put_bytes(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._k(key), Body=data)

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self._k(key))["Body"].read()

    def local_file(self, key: str) -> Path:
        dst = self._cache / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            dst.write_bytes(self.get_bytes(key))
        return dst

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._k(key)}"


def get_storage() -> Storage:
    """Factory: S3 if ``S3_BUCKET`` is set, else local bronze dir."""
    bucket = os.environ.get("S3_BUCKET")
    if bucket:
        return S3Storage(
            bucket=bucket,
            prefix=os.environ.get("S3_PREFIX", "yantra-corpus"),
            endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,  # unset = real AWS S3
            region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        )
    return LocalStorage(config.DATA_DIR)
