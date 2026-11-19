"""Zernio publishNow answers 'uploading'; the final status must be polled (offline)."""
from unittest.mock import MagicMock

import pytest
import requests

from carlecool import approve
from carlecool.zernio import Zernio, wait_for_result


def _post(status, url=""):
    entry = {"platform": "tiktok", "status": status}
    if url:
        entry["platformPostUrl"] = url
    return {"post": {"_id": "6aff53bc0f2ada679bf1efcb", "status": status, "platforms": [entry]}}


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _client(responses):
    session = MagicMock()
    replies = []
    for item in responses:
        if isinstance(item, Exception):
            replies.append(item)
        else:
            r = MagicMock()
            r.json.return_value = item
            r.raise_for_status.return_value = None
            replies.append(r)
    session.get.side_effect = replies
    return Zernio("zrk_test_long_secret", session=session), session


def test_uploading_is_polled_until_published():
    client, session = _client([_post("uploading"), requests.ConnectionError(), _post("published", "https://www.tiktok.com/@carl_e_cool/video/1")])
    clock = FakeClock()
    final, finished = wait_for_result(client, _post("uploading"), "tiktok", sleep=clock.sleep, clock=clock)
    assert finished and final["post"]["platforms"][0]["status"] == "published"
    assert session.get.call_count == 3
    assert session.get.call_args.args[0].endswith("/v1/posts/6aff53bc0f2ada679bf1efcb")


def test_polling_gives_up_after_deadline():
    client, _ = _client([_post("processing")] * 100)
    clock = FakeClock()
    _, finished = wait_for_result(client, _post("uploading"), "tiktok", timeout=60, interval=15,
                                  sleep=clock.sleep, clock=clock)
    assert not finished and clock.now >= 60


def _publish_setup(monkeypatch, polled):
    commits, comments = [], []
    monkeypatch.setattr(approve, "save_state", lambda s: None)
    monkeypatch.setattr(approve, "commit_state", lambda m: commits.append(m))
    monkeypatch.setattr(approve, "github_request", lambda method, path, json_body=None: comments.append((method, path, json_body)))
    monkeypatch.setattr(Zernio, "verify_connections", lambda self, accounts: {n: True for n in accounts})
    monkeypatch.setattr(Zernio, "preflight_tiktok", lambda self, account_id: None)
    monkeypatch.setattr(Zernio, "upload", lambda self, video: "https://media.zernio.com/temp/x.mp4")
    monkeypatch.setattr(Zernio, "publish", lambda self, **kwargs: _post("uploading"))
    monkeypatch.setattr("carlecool.zernio.wait_for_result", lambda client, response, target: polled)
    monkeypatch.setenv("ZERNIO_API_KEY", "zrk_test_long_secret")
    monkeypatch.setenv("ZERNIO_TIKTOK_ACCOUNT_ID", "tt1")
    approval = {"track_id": "2437525038", "sha256": "b" * 64, "video_ids": [str(i) for i in range(5)],
                "caption": "c", "footage_sources": [{"provider": "coverr"}]}
    return approval, commits, comments


def test_publish_records_url_and_closes_issue_after_polling(monkeypatch, tmp_path):
    url = "https://www.tiktok.com/@carl_e_cool/video/7709973233797270817"
    approval, commits, comments = _publish_setup(monkeypatch, (_post("published", url), True))
    state = {"pending": None, "published": []}
    approve.publish_via_zernio(22, approval, approval, tmp_path / "x.mp4", "tiktok", state)
    assert state["pending"] is None
    record = state["published"][0]
    assert record["platform_status"] == {"tiktok": "published"}
    assert record["platform_post_urls"] == {"tiktok": url}
    assert commits[-1].startswith("journal: published zernio reel 22")
    assert url in comments[0][2]["body"] and comments[1][2] == {"state": "closed"}


def test_still_processing_keeps_pending_and_never_reposts(monkeypatch, tmp_path):
    approval, commits, comments = _publish_setup(monkeypatch, (_post("uploading"), False))
    state = {"pending": None, "published": []}
    with pytest.raises(RuntimeError, match="still processing"):
        approve.publish_via_zernio(23, approval, approval, tmp_path / "x.mp4", "tiktok", state)
    assert state["pending"]["platform_status"] == {"tiktok": "uploading"}
    assert state["published"] == [] and comments == []
