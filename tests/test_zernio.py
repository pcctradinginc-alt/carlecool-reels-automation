"""Zernio free tier publishing is fail-closed, audited, and recipient-specific."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from carlecool.approve import ensure_target_ready
from carlecool.zernio import Zernio, _check_media_url, published_platforms


PRESIGN = {
    "uploadUrl": "https://abc.r2.cloudflarestorage.com/temp/test.mp4?X-Amz-Signature=xyz",
    "publicUrl": "https://media.zernio.com/temp/test.mp4",
}


class Resp:
    def __init__(self, obj=None):
        self.obj = obj or {}
        self.status_code = 200
    def raise_for_status(self):
        pass
    def json(self):
        return self.obj


def test_free_provider_requires_explicit_opt_in_and_exact_connected_account_ids(monkeypatch):
    monkeypatch.delenv("ZERNIO_PUBLISH_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="Neither TikTok nor Instagram"):
        ensure_target_ready("both")
    monkeypatch.setenv("ZERNIO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("ZERNIO_API_KEY", "zrk_test_long_secret")
    monkeypatch.setenv("ZERNIO_INSTAGRAM_ACCOUNT_ID", "ig_123")
    monkeypatch.delenv("ZERNIO_TIKTOK_ACCOUNT_ID", raising=False)
    with pytest.raises(RuntimeError, match="ZERNIO_TIKTOK_ACCOUNT_ID"):
        ensure_target_ready("both")
    ensure_target_ready("instagram")
    monkeypatch.setenv("ZERNIO_TIKTOK_ACCOUNT_ID", "tt_456")
    ensure_target_ready("both")
    ensure_target_ready("tiktok")


def test_upload_must_use_safe_signed_zernio_storage_hosts(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"0" * 5000)
    session = MagicMock()
    session.post.return_value = Resp(PRESIGN)
    session.put.return_value = Resp()
    client = Zernio("zrk_test_long_secret", session=session)
    assert client.upload(path) == PRESIGN["publicUrl"]
    assert session.post.call_args.args[0].endswith("/v1/media/presign")
    assert session.put.call_args.kwargs["headers"] == {"Content-Type": "video/mp4"}
    for url in ("https://evil.example/video.mp4", "http://media.zernio.com/temp/a.mp4",
                "https://media.zernio.com/temp/a.mp4?password=1"):
        with pytest.raises(ValueError):
            _check_media_url(url, upload=False)


@pytest.mark.parametrize(("target", "expected"), [
    ("instagram", ["instagram"]),
    ("tiktok", ["tiktok"]),
    ("both", ["instagram", "tiktok"]),
])
def test_publish_request_uses_one_video_and_no_extra_destinations(target, expected):
    session = MagicMock()
    session.post.return_value = Resp({"post": {"_id": "abc", "status": "published"}})
    client = Zernio("zrk_test_long_secret", session=session)
    out = client.publish(
        media_url=PRESIGN["publicUrl"], caption="#CarleCool", target=target,
        instagram_id="ig1", tiktok_id="tt1", ai_generated=True,
        sha256="a" * 64, issue_number=8,
    )
    assert out["post"]["_id"] == "abc"
    kwargs = session.post.call_args.kwargs
    body = kwargs["json"]
    assert [entry["platform"] for entry in body["platforms"]] == expected
    assert body["mediaItems"] == [{"url": PRESIGN["publicUrl"], "type": "video"}]
    assert body["publishNow"] is True
    assert "Idempotency-Key" in kwargs["headers"]
    if "tiktok" in expected:
        settings = body["tiktokSettings"]
        assert settings["content_preview_confirmed"] is True
        assert settings["express_consent_given"] is True
        assert settings["privacy_level"] == "PUBLIC_TO_EVERYONE"
        assert settings["video_made_with_ai"] is True
    else:
        assert "tiktokSettings" not in body


def test_partial_multiplatform_status_is_not_misreported():
    payload = {"post": {"status": "partial", "platforms": [
        {"platform": "tiktok", "status": "failed"},
        {"platform": "instagram", "status": "published"},
    ]}}
    statuses = published_platforms(payload, "both")
    assert statuses["tiktok"]["status"] == "failed"
    assert statuses["instagram"]["status"] == "published"
    with pytest.raises(RuntimeError, match="each requested"):
        published_platforms({"post": {"platforms": [statuses["instagram"]]}}, "both")


def test_pending_journal_stays_after_partial_provider_result(tmp_path, monkeypatch):
    from carlecool import approve
    from carlecool.zernio import Zernio
    save_calls = []
    commits = []
    state = {"pending": None, "published": []}
    monkeypatch.setattr(approve, "save_state", lambda s: save_calls.append(s["pending"].copy() if s["pending"] else None))
    monkeypatch.setattr(approve, "commit_state", lambda m: commits.append(m))
    monkeypatch.setattr(Zernio, "verify_connections", lambda self, accounts: {
        name: True for name in accounts
    })
    monkeypatch.setattr(Zernio, "preflight_tiktok", lambda self, account_id: None)
    monkeypatch.setenv("ZERNIO_INSTAGRAM_ACCOUNT_ID", "ig1")
    monkeypatch.setenv("ZERNIO_TIKTOK_ACCOUNT_ID", "tt1")
    monkeypatch.setattr(Zernio, "upload", lambda self, video: PRESIGN["publicUrl"])
    monkeypatch.setattr(Zernio, "publish", lambda self, **kwargs: {"post": {
        "_id": "z123", "status": "partial",
        "platforms": [
            {"platform": "instagram", "status": "published"},
            {"platform": "tiktok", "status": "failed"},
        ],
    }})
    monkeypatch.setenv("ZERNIO_API_KEY", "zrk_test_long_secret")
    preview = {
        "track_id": "33", "sha256": "a" * 64,
        "video_ids": [str(i) for i in range(5)],
        "caption": "#CarleCool", "footage_sources": [],
    }
    with pytest.raises(RuntimeError, match="manual Zernio reconciliation"):
        approve.publish_via_zernio(9, preview, preview, tmp_path / "x.mp4", "both", state)
    assert state["pending"]["provider_post_id"] == "z123"
    assert state["pending"]["platform_status"] == {"instagram": "published", "tiktok": "failed"}
    assert len(commits) == 2
    assert state["published"] == []
