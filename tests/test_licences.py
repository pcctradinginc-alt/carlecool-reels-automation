import base64
import json
from unittest.mock import MagicMock

import requests

from carlecool import licences
from carlecool.video import Video, coverr_page


def test_proof_per_source_has_page_licence_and_date():
    cov = Video("c1", "coverr", title="Land Rover on a beach", url="https://cdn.example/x.mp4?token=secret",
                page_url=coverr_page({"slug": "land-rover-on-a-beach"}))
    p = licences.proof(cov, used_at="2026-11-24")
    assert p["page"] == "https://coverr.co/videos/land-rover-on-a-beach"
    assert p["licence_url"] == "https://coverr.co/license" and p["used_at"] == "2026-11-24"
    assert "token" not in json.dumps(p)  # no download URLs in the proof
    ia = licences.proof(Video("pl-cahuca_1", "prelinger", title="Huntington Beach",
                              licence="Public domain (California Revealed)",
                              licence_url="http://creativecommons.org/publicdomain/mark/1.0/"))
    assert ia["page"] == "https://archive.org/details/cahuca_1" and "California Revealed" in ia["licence"]
    assert licences.proof(Video("x", "owned"))["licence"].startswith("Own footage")
    assert coverr_page({"slug": "../evil"}) == ""


def _resp(status, payload=None):
    r = MagicMock(status_code=status, content=b"1")
    r.json.return_value = payload or {}
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    return r


def test_licence_log_is_created_appended_and_never_duplicated():
    meta = {"song_label": "carl e cool - x", "sha256": "a" * 64, "caption": "🎧 x\n🎬 Footage by Coverr: https://coverr.co",
            "footage_sources": [{"id": "c1", "provider": "coverr", "licence": "Coverr License"}]}
    session = MagicMock()
    session.request.side_effect = [_resp(404), _resp(201)]
    assert licences.record_licence_log(meta, run_id=7, token="t", repo="o/r", session=session)
    body = session.request.call_args.kwargs["json"]
    doc = json.loads(base64.b64decode(body["content"]))
    assert doc["reels"][0]["clips"][0]["id"] == "c1" and doc["reels"][0]["caption_credits"]
    assert "sha" not in body and "[skip ci]" in body["message"]
    existing = base64.b64encode(json.dumps(doc).encode()).decode()
    session.request.side_effect = [_resp(200, {"content": existing, "sha": "s1"})]
    assert licences.record_licence_log(meta, run_id=7, token="t", repo="o/r", session=session) is False
