import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from carlecool.analysis import beat_cut_lengths
from carlecool.main import caption_for
from carlecool.soundcloud import Track
from carlecool.state import pick_track
from carlecool.video import Video, fallback_videos, search_coverr, _check_host


def tr(id, date="2026-11-01T00:00:00Z"):
    return Track(id=id, title="House " + id, permalink_url=f"https://soundcloud.com/carlecool/{id}", created_at=date)


def test_beat_cut_lengths_add_up():
    for bpm in (65, 90, 120, 145, 180):
        lengths = beat_cut_lengths(bpm, 30)
        assert 5 <= len(lengths) <= 11
        assert sum(lengths) == pytest.approx(30, abs=.01)
        assert min(lengths) >= 1


def test_rotation_and_pending_gate():
    state = {"published": [{"track_id": "1", "at": "2026-11-14T10:00:00+00:00"}], "pending": None}
    assert pick_track([tr("1"), tr("2")], state, now=datetime(2026, 11, 15, tzinfo=timezone.utc)).id == "2"
    state["pending"] = {"track_id": "2"}
    with pytest.raises(RuntimeError, match="pending"):
        pick_track([tr("1"), tr("2")], state)


def test_repost_cooldown():
    state = {"published": [{"track_id": "1", "at": "2026-11-14T10:00:00+00:00"}], "pending": None}
    with pytest.raises(RuntimeError, match="cooldown"):
        pick_track([tr("1")], state, 19, datetime(2026, 11, 15, tzinfo=timezone.utc))


def _coverr_session():
    session = MagicMock()
    session.get.return_value.json.return_value = {"hits": [
        {"id": "a", "title": "vertical", "views": 10, "is_vertical": True,
         "thumbnail": "https://storage.coverr.co/t/a.jpg", "tags": ["Sunset"],
         "max_width": 1080, "max_height": 1920, "duration": 12,
         "urls": {"mp4_download": "https://storage.coverr.co/a.mp4"}},
        {"id": "b", "title": "horizontal", "views": 1000, "is_vertical": False,
         "max_width": 1920, "max_height": 1080,
         "urls": {"mp4_download": "https://storage.coverr.co/b.mp4"}},
    ]}
    return session


def test_coverr_real_phrases_portrait_first(monkeypatch):
    monkeypatch.delenv("CARLECOOL_PORTRAIT_ONLY", raising=False)
    session = _coverr_session()
    phrases = ["MPC 2000 XL sampler closeup", "vintage roadside motel dusk", "night drive coastal road"]
    result = search_coverr("fakekey", "nightdrive", set(), session=session, wanted=4, keywords=phrases)
    # Portrait leads; landscape is only kept as a later fill-in candidate.
    assert [x.id for x in result] == ["a", "b"]
    assert result[0].vertical and not result[1].vertical and result[0].query == phrases[0]
    assert result[0].thumb_url.endswith("a.jpg") and result[0].tags == ("sunset",)
    queries = [call.kwargs["params"]["query"] for call in session.get.call_args_list]
    # Full phrase, then its core words, broad term last; at most 9 requests.
    assert queries[:3] == [phrases[0], "sampler", "music"]
    assert session.get.call_count <= 9


def test_coverr_strict_portrait_mode(monkeypatch):
    monkeypatch.setenv("CARLECOOL_PORTRAIT_ONLY", "true")
    result = search_coverr("fakekey", "nightdrive", set(), session=_coverr_session(), wanted=2,
                           keywords=["sunset"])
    assert [x.id for x in result] == ["a"]


def test_caption_credit_present():
    text = caption_for(tr("7"), [Video("a", "coverr")])
    assert "Coverr" in text and "Link in Bio" not in text and "soundcloud.com" not in text


def test_no_unapproved_local_footage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "assets" / "stock"
    root.mkdir(parents=True)
    (root / "test.mp4").write_bytes(b"fake")
    (root / "manifest.json").write_text(json.dumps({"clips": [{"id": "1", "file": "test.mp4", "license_confirmed": False,
                                                               "commercial_social_allowed": True}]}))
    assert fallback_videos(set()) == []


def test_no_insecure_downloads():
    for bad in ("http://coverr.co/test.mp4", "https://localhost/foo", "file:///etc/passwd", "https://127.0.0.1/x"):
        with pytest.raises(ValueError):
            _check_host(bad)


def test_track_id_parsing():
    a = Track.parse({"urn": "soundcloud:tracks:1234", "title": "test"})
    assert a.id == "1234"


def test_meta_container_flow_mocked(tmp_path):
    from carlecool.instagram import Instagram
    mock = MagicMock()
    creation = MagicMock()
    creation.json.return_value = {"id": "12345", "uri": "https://rupload.facebook.com/ig-api-upload/v24.0/12345"}
    creation.raise_for_status.return_value = None
    upload = MagicMock()
    upload.json.return_value = {"success": True}
    upload.raise_for_status.return_value = None
    identity = MagicMock()
    identity.json.return_value = {"data": [{"id": "1001", "username": "test"}]}
    mock.request.side_effect = [identity, creation]
    mock.post.return_value = upload
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake_mp4_for_mock")
    publisher = Instagram("1001", "fake-token", session=mock)
    assert publisher.create_and_upload(path, "a caption") == "12345"
    assert mock.post.call_args.args[0].startswith("https://rupload.facebook.com/")


def test_no_unconfirmed_meta_upload(tmp_path):
    from carlecool.instagram import Instagram
    mock = MagicMock()
    creation = MagicMock()
    creation.json.return_value = {"id": "12345", "uri": "https://attacker.example.net/upload"}
    identity = MagicMock()
    identity.json.return_value = {"data": [{"id": "123", "username": "test"}]}
    mock.request.side_effect = [identity, creation]
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake")
    with pytest.raises(ValueError, match="upload host"):
        Instagram("123", "fake-token", session=mock).create_and_upload(path, "x")
    mock.post.assert_not_called()


def test_every_art_direction_phrase_has_a_short_coverr_query():
    from carlecool.creative import CUES
    from carlecool.video import SHORT_QUERIES, query_ladder, short_query
    for phrases in CUES.values():
        for phrase in phrases:
            assert phrase in SHORT_QUERIES
            assert 1 <= len(short_query(phrase).split()) <= 2
    assert query_ladder("faded Super 8 summer film") == ["faded Super 8 summer film", "vintage summer", "sunset"]
    assert short_query("lonely neon gas station at night") == "neon gas"
