"""Wikimedia Commons source (offline, mocked API)."""
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from carlecool import wikimedia
from carlecool.approve import validate_footage_rights
from carlecool.main import caption_for
from carlecool.soundcloud import Track
from carlecool.video import Video


@pytest.mark.parametrize("name,restr,ok", [
    ("Public domain", "", True), ("CC0", "", True), ("CC BY 4.0", "", True), ("CC BY 2.0", "", True),
    ("CC BY-SA 4.0", "", False), ("CC BY-SA 3.0 nl", "", False), ("CC BY-NC 2.0", "", False),
    ("CC BY-ND 4.0", "", False), ("CC BY 4.0", "personality rights", False), ("GFDL", "", False),
])
def test_license_gate(name, restr, ok):
    assert wikimedia.license_ok(name, restr) is ok


def _page(title, lic, *, restr="", h=1080, mime="video/webm", artist="<a href='x'>Jane Doe</a>"):
    return {"title": f"File:{title}", "imageinfo": [{
        "url": f"https://upload.wikimedia.org/x/{title}", "thumburl": f"https://upload.wikimedia.org/t/{title}",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{title}", "mime": mime,
        "width": 1920, "height": h, "extmetadata": {
            "LicenseShortName": {"value": lic}, "Restrictions": {"value": restr}, "Artist": {"value": artist}}}]}


def test_category_parsing_filters_and_strips_html(monkeypatch):
    monkeypatch.setattr(wikimedia.time, "sleep", lambda s: None)
    session = MagicMock(headers={})
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"query": {"pages": {
        "1": _page("skate.webm", "CC BY 3.0"), "2": _page("sa.webm", "CC BY-SA 4.0"),
        "3": _page("pr.webm", "Public domain", restr="personality"),
        "4": {"title": "File:evil.webm", "imageinfo": [{"url": "https://evil.example/x.webm",
                                                       "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]}}}}
    session.get.return_value = resp
    items = wikimedia.category_files("Videos of skateboarding", session=session)
    assert [i["title"] for i in items] == ["skate.webm"]
    assert items[0]["artist"] == "Jane Doe"
    assert wikimedia.credit_line(items[0]) == "Jane Doe / Wikimedia Commons (CC BY 3.0)"
    assert "User-Agent" in session.headers and "@" not in session.headers["User-Agent"]


def test_throttling_is_skipped_not_fatal(monkeypatch):
    monkeypatch.setattr(wikimedia.time, "sleep", lambda s: None)
    session = MagicMock(headers={})
    session.get.return_value = MagicMock(status_code=429, headers={"Retry-After": "1"})
    assert wikimedia.category_files("Videos of horses", session=session) == []
    assert session.get.call_count == 2  # one polite retry, then skip


def test_caption_and_rights_require_wikimedia_credit():
    track = Track(id="1", title="mikosh", permalink_url="")
    clips = [Video("wm-1", "wikimedia", creator_name="Jane Doe / Wikimedia Commons (CC BY 3.0)"),
             Video("wm-2", "wikimedia", creator_name="Wikimedia Commons (public domain)")]
    caption = caption_for(track, clips)
    assert "Jane Doe / Wikimedia Commons (CC BY 3.0); Wikimedia Commons (public domain)" in caption
    validate_footage_rights({"caption": caption, "footage_sources": [{"provider": "wikimedia"}]})
    with pytest.raises(RuntimeError, match="Wikimedia"):
        validate_footage_rights({"caption": "x", "footage_sources": [{"provider": "wikimedia"}]})


def test_ken_burns_turns_a_photo_into_a_5s_clip(tmp_path, monkeypatch):
    photo = tmp_path / "fsa.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1600x1200:d=1",
                    "-frames:v", "1", str(photo)], check=True)
    monkeypatch.setattr(wikimedia, "urlparse", lambda u: SimpleNamespace(hostname=wikimedia.MEDIA_HOST))
    out = wikimedia._ken_burns(str(photo), tmp_path / "kb.mp4", "k")
    from carlecool.render import probe_dimensions, probe_duration
    assert probe_dimensions(out) == (1920, 1440)
    assert abs(probe_duration(out) - wikimedia.PHOTO_SECONDS) < 0.1


def test_disabled_or_unknown_role(monkeypatch, tmp_path):
    assert wikimedia.fetch_wikimedia("night", set(), tmp_path) == []
    monkeypatch.setenv("CARLECOOL_WIKIMEDIA", "false")
    assert wikimedia.fetch_wikimedia("lana", set(), tmp_path) == []


def test_sensitive_historical_titles_are_excluded(monkeypatch):
    monkeypatch.setattr(wikimedia.time, "sleep", lambda s: None)
    session = MagicMock(headers={})
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"query": {"pages": {
        "1": _page("A negro Farm Security Administration borrower.jpg", "Public domain", mime="image/jpeg"),
        "2": _page("Migrant camp, California.jpg", "Public domain", mime="image/jpeg"),
        "3": _page("Highway 66 gas station, Texas.jpg", "Public domain", mime="image/jpeg")}}}
    session.get.return_value = resp
    titles = [i["title"] for i in wikimedia.category_files("x", session=session)]
    assert titles == ["Highway 66 gas station, Texas.jpg"]


def test_photos_from_the_thumb_host_are_accepted_and_others_refused(tmp_path, monkeypatch):
    import pytest
    calls = []
    monkeypatch.setattr(wikimedia.subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr("carlecool.httpbridge.local_url", lambda u, ua=None: "http://127.0.0.1:1/x")
    wikimedia._ken_burns("https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/x.jpg/1920px-x.jpg",
                         tmp_path / "k.mp4", "k")
    assert calls
    with pytest.raises(ValueError):
        wikimedia._ken_burns("https://evil.example.org/x.jpg", tmp_path / "k.mp4", "k")


def test_sensitive_period_captions_are_filtered():
    from carlecool.archives import _blocked
    for title in ('"Backstage" at the "girlie" show at the Vermont state fair',
                  "1940 African American children Natchitoches Louisiana"):
        assert _blocked(title.lower(), wikimedia.SENSITIVE)
    assert not _blocked("40 days lincoln, nebraska.jpg", wikimedia.SENSITIVE)


class _Resp:
    def __init__(self, status, body=b"", url="https://upload.wikimedia.org/a.webm", headers=None):
        self.status_code, self._body, self.url, self.headers = status, body, url, headers or {}
    def iter_content(self, n):
        yield self._body
    def close(self):
        pass


def test_video_is_fetched_in_one_request_with_one_retry_on_429(tmp_path, monkeypatch):
    monkeypatch.setattr(wikimedia.time, "sleep", lambda s: None)
    session = MagicMock(headers={})
    session.get.side_effect = [_Resp(429, headers={"Retry-After": "3"}), _Resp(200, b"x" * 5000)]
    item = {"url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Skate.webm", "bytes": 5000}
    out = wikimedia.download_video(item, tmp_path / "v.webm", session=session)
    assert out.read_bytes() == b"x" * 5000 and session.get.call_count == 2
    assert "Range" not in (session.get.call_args.kwargs.get("headers") or {})


def test_video_download_refuses_big_unknown_or_foreign_files(tmp_path):
    import pytest
    base = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Doc.webm"
    for item in ({"url": base, "bytes": wikimedia.MAX_VIDEO_BYTES + 1}, {"url": base, "bytes": 0},
                 {"url": "https://evil.example.org/x.webm", "bytes": 10}):
        with pytest.raises(ValueError):
            wikimedia.download_video(item, tmp_path / "v.webm", session=MagicMock(headers={}))
    session = MagicMock(headers={})
    session.get.return_value = _Resp(200, b"x", url="https://evil.example.org/x.webm")
    with pytest.raises(ValueError, match="foreign"):
        wikimedia.download_video({"url": base, "bytes": 10}, tmp_path / "v.webm", session=session)
