"""Licence proof per clip (owner, 24 Nov).

For every clip in a Reel: source, clip ID, title, page of the clip, the licence that
applied when it was used, a link to that licence and the date of use. Stored twice:
in the approval issue (footage_sources) and, never trimmed, in data/licence-log.json
in the repository. With it a Content-ID or copyright claim on TikTok / Instagram /
YouTube can be answered right away. No download URLs (they can carry tokens), no
personal data.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import time

import requests

LOG_PATH = "data/licence-log.json"
DEFAULTS = {
    "coverr": ("Coverr License (free for commercial use)", "https://coverr.co/license"),
    "pexels": ("Pexels License (free for commercial use)", "https://www.pexels.com/license/"),
    "nasa": ("NASA media usage guidelines (not copyrighted)",
             "https://www.nasa.gov/nasa-brand-center/images-and-media/"),
    "prelinger": ("Public domain (Internet Archive)", "https://creativecommons.org/publicdomain/mark/1.0/"),
    "wikimedia": ("Wikimedia Commons free licence", "https://commons.wikimedia.org/wiki/Commons:Licensing"),
    "owned": ("Own footage (CarleCool)", ""),
    "ai": ("AI-generated footage (LTX-2.3); distribution subject to applicable terms", "https://huggingface.co/Lightricks/LTX-2.3/blob/main/LICENSE"),
}


def proof(video, used_at: str | None = None) -> dict:
    """Licence record of one clip (also the issue's footage_sources entry)."""
    licence, licence_url = DEFAULTS.get(video.source, ("unknown", ""))
    page = video.page_url or video.creator_url or ""
    if video.source == "prelinger" and not page and str(video.id).startswith("pl-"):
        page = "https://archive.org/details/" + str(video.id)[3:]
    return {"id": video.id, "provider": video.source, "title": video.title,
            "page": page, "creator": video.creator_name or "",
            "licence": video.licence or licence, "licence_url": video.licence_url or licence_url,
            "used_at": used_at or datetime.now(timezone.utc).date().isoformat()}


def record_licence_log(metadata: dict, *, run_id: int, token: str, repo: str, session=None) -> bool:
    """Append this Reel's clips to data/licence-log.json (never trimmed); duplicate run = no-op."""
    from .review import github_request
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": run_id,
             "song": metadata.get("song_label") or str(metadata.get("track_id") or ""),
             "sha256": metadata.get("sha256"), "caption_credits": [
                 line for line in str(metadata.get("caption") or "").splitlines() if line.startswith("🎬")],
             "clips": metadata.get("footage_sources") or []}
    for attempt in range(4):
        try:
            current = github_request("GET", f"contents/{LOG_PATH}?ref=main", token=token, repo=repo,
                                     session=session)
            document, sha = json.loads(base64.b64decode(current["content"]).decode("utf-8")), current["sha"]
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise
            document, sha = {"version": 1, "reels": []}, None
        reels = list(document.get("reels") or [])
        if any(r.get("run_id") == run_id for r in reels):
            return False
        body = {"message": f"licences: record clips of run {run_id} [skip ci]",
                "content": base64.b64encode((json.dumps({"version": 1, "reels": reels + [entry]},
                                                        ensure_ascii=False, indent=1) + "\n").encode()).decode(),
                "branch": "main"}
        if sha:
            body["sha"] = sha
        try:
            github_request("PUT", f"contents/{LOG_PATH}", json_body=body, token=token, repo=repo, session=session)
            return True
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in (409, 422) or attempt == 3:
                raise
            time.sleep(min(2 ** attempt, 4))
    raise RuntimeError("Licence log update failed after concurrent writes")
