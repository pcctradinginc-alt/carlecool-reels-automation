"""Private full-quality master storage outside Gmail (Cloudflare R2 / any S3 API).

Why: a Gmail attachment must stay below ~16 MB, which forced a visible re-encode.
When `MASTER_S3_BUCKET` is configured, the uncompressed-for-email master is uploaded
to a private bucket and only a lighter preview travels by email. Publication fetches
the master from the bucket and verifies its SHA-256 against the approval issue, exactly
like the Gmail path. Nothing is public: the bucket must stay private (no public URL).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

MAX_MASTER_BYTES = 300_000_000
KEY_RE = re.compile(r"carlecool/masters/[0-9]{1,20}/[0-9a-f]{64}\.mp4")
# Phase 4 (27 Nov, audit E1): free full-quality master in the GitHub Actions cache. The
# daily workflow caches masters/<run>/<sha>.mp4 under key carlecool-master-<run>; the
# approve workflow restores it before --fetch. No new service, no cost, nothing public.
CACHE_PATH_RE = re.compile(r"masters/[0-9]{1,20}/[0-9a-f]{64}\.mp4")


def cache_mode() -> bool:
    return os.getenv("CARLECOOL_MASTER_STORE", "").strip().lower() == "actions-cache"


def configured() -> bool:
    return bool(os.getenv("MASTER_S3_BUCKET", "").strip()) or cache_mode()


def _client():
    import boto3
    return boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def upload_master(video: Path, *, run_id: int, sha256: str, client=None) -> dict:
    bucket = os.getenv("MASTER_S3_BUCKET", "").strip()
    if not bucket and cache_mode():
        if not re.fullmatch(r"[0-9a-f]{64}", sha256) or _sha256(video) != sha256:
            raise ValueError("Master SHA-256 differs from render metadata")
        path = Path("masters") / str(int(run_id)) / f"{sha256}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(video, path)
        return {"provider": "actions-cache", "key": f"carlecool-master-{int(run_id)}", "path": path.as_posix(),
                "bytes": video.stat().st_size, "sha256": sha256}
    if not bucket:
        raise RuntimeError("MASTER_S3_BUCKET is not configured")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256) or _sha256(video) != sha256:
        raise ValueError("Master SHA-256 differs from render metadata")
    size = video.stat().st_size
    if size > MAX_MASTER_BYTES:
        raise ValueError("Master exceeds storage size limit")
    key = f"carlecool/masters/{int(run_id)}/{sha256}.mp4"
    client = client or _client()
    with video.open("rb") as body:
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="video/mp4",
                          Metadata={"sha256": sha256, "run-id": str(int(run_id))})
    return {"provider": "s3", "bucket": bucket, "key": key, "bytes": size, "sha256": sha256}


def download_master(location: dict, destination: Path, *, expected_sha256: str, client=None) -> Path:
    """Fetch the approved master and fail closed on any identity mismatch."""
    if isinstance(location, dict) and location.get("provider") == "actions-cache":
        path = str(location.get("path", ""))
        if not CACHE_PATH_RE.fullmatch(path) or not path.endswith(f"/{expected_sha256}.mp4"):
            raise ValueError("Invalid cached master path")
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError("Master no longer in the Actions cache")
        if source.stat().st_size > MAX_MASTER_BYTES or _sha256(source) != expected_sha256:
            raise ValueError("Master SHA-256 mismatch: cached file differs from approved Reel")
        destination.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(source, destination)
        return destination
    if not isinstance(location, dict) or location.get("provider") != "s3":
        raise ValueError("Unsupported master storage location")
    bucket = os.getenv("MASTER_S3_BUCKET", "").strip()
    key = str(location.get("key", ""))
    if not bucket or location.get("bucket") != bucket:
        raise ValueError("Master bucket differs from configured MASTER_S3_BUCKET")
    if not KEY_RE.fullmatch(key) or not key.endswith(f"/{expected_sha256}.mp4"):
        raise ValueError("Invalid master object key")
    client = client or _client()
    head = client.head_object(Bucket=bucket, Key=key)
    if int(head.get("ContentLength", 0)) > MAX_MASTER_BYTES:
        raise ValueError("Master object too large")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".part")
    client.download_file(bucket, key, str(temp))
    if _sha256(temp) != expected_sha256:
        temp.unlink(missing_ok=True)
        raise ValueError("Master SHA-256 mismatch: stored file differs from approved Reel")
    os.replace(temp, destination)
    return destination
