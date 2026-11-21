"""Local bridge: FFmpeg reads 127.0.0.1, Python fetches the real URL (offline)."""
import urllib.request
from unittest.mock import MagicMock

import pytest

from carlecool import httpbridge


def test_only_known_hosts_and_passthrough_for_files():
    assert httpbridge.local_url("/tmp/clip.mp4") == "/tmp/clip.mp4"
    with pytest.raises(ValueError):
        httpbridge.local_url("https://evil.example/x.mp4")
    assert httpbridge._allowed("https://ia800.us.archive.org/1/x.mp4")
    assert httpbridge._allowed("https://upload.wikimedia.org/a.webm")
    assert httpbridge._allowed("https://images-assets.nasa.gov/v/a.mp4")
    assert not httpbridge._allowed("http://archive.org/x.mp4")  # https only


def test_range_requests_and_user_agent_are_forwarded(monkeypatch):
    seen = {}

    def fake_request(method, url, headers, **kw):
        seen.update(method=method, url=url, headers=headers)
        r = MagicMock(status_code=206, url="https://ia800.us.archive.org/x.mp4",
                      headers={"Content-Type": "video/mp4", "Content-Range": "bytes 10-13/100",
                               "Content-Length": "4", "Accept-Ranges": "bytes"})
        r.iter_content.return_value = [b"DATA"]
        return r

    monkeypatch.setattr(httpbridge.requests, "request", fake_request)
    local = httpbridge.local_url("https://archive.org/download/x/x.mp4", "UA-with-contact")
    assert local.startswith("http://127.0.0.1:")
    req = urllib.request.Request(local, headers={"Range": "bytes=10-13"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 206 and resp.read() == b"DATA"
        assert resp.headers["Content-Range"] == "bytes 10-13/100"
    assert seen["headers"]["Range"] == "bytes=10-13"
    assert seen["headers"]["User-Agent"] == "UA-with-contact"


def test_unknown_route_and_foreign_redirect_are_refused(monkeypatch):
    local = httpbridge.local_url("https://archive.org/download/y/y.mp4")
    bogus = local.rsplit("/", 1)[0] + "/doesnotexist"
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(bogus, timeout=10)
    assert err.value.code == 404
    redirected = MagicMock(status_code=200, url="https://evil.example/y.mp4", headers={})
    monkeypatch.setattr(httpbridge.requests, "request", lambda *a, **k: redirected)
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(local, timeout=10)
    assert err.value.code == 403
