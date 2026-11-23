"""Song pool: limit the daily pick to one of the owner's SoundCloud sets."""
import json
from unittest.mock import MagicMock

import pytest

from carlecool import songpool
from carlecool.soundcloud import _playlist_tracks


def test_repo_pool_is_the_mpc2000xl_ghost_notes_ep(monkeypatch):
    monkeypatch.delenv("CARLECOOL_SONG_POOL", raising=False)
    pool = songpool.load()
    assert pool["mode"] == "playlist" and pool["playlist_url"].endswith("/sets/mpc2000xl-ghost-notes")
    monkeypatch.setenv("CARLECOOL_SONG_POOL", "all")
    assert songpool.load() == {"mode": "all"}


def test_bad_pool_url_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("CARLECOOL_SONG_POOL", raising=False)
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"mode": "playlist", "playlist_url": "https://evil.example/sets/x"}))
    with pytest.raises(ValueError):
        songpool.load(f)
    f.write_text(json.dumps({"mode": "all"}))
    assert songpool.load(f) == {"mode": "all"}


def _resp(payload):
    r = MagicMock(); r.json.return_value = payload; r.raise_for_status.return_value = None
    return r


def test_playlist_tracks_keep_only_the_owners_public_tracks():
    playlist = {"kind": "playlist", "user": {"id": 7}, "tracks": [
        {"id": 1, "title": "a", "user": {"id": 7}},
        {"id": 2, "title": "b (private)", "user": {"id": 7}, "sharing": "private"},
        {"id": 3, "title": "repost", "user": {"id": 99}},
        {"id": 4, "title": "d", "user": {"id": 7}}]}
    session = MagicMock(); session.get.return_value = _resp(playlist)
    tracks = _playlist_tracks(session, "t", {"mode": "playlist", "playlist_url": "https://soundcloud.com/x/sets/y",
                                             "label": "EP"}, "7")
    assert [t.id for t in tracks] == ["1", "4"] and all(t.uploader_id == "7" for t in tracks)


def test_foreign_or_empty_set_fails_closed():
    pool = {"mode": "playlist", "playlist_url": "https://soundcloud.com/x/sets/y", "label": "EP"}
    session = MagicMock(); session.get.return_value = _resp({"kind": "playlist", "user": {"id": 99}, "tracks": []})
    with pytest.raises(RuntimeError, match="another"):
        _playlist_tracks(session, "t", pool, "7")
    session.get.side_effect = [_resp({"kind": "playlist", "user": {"id": 7}, "urn": "soundcloud:playlists:5", "tracks": []}),
                               _resp({"collection": []})]
    with pytest.raises(RuntimeError, match="no public tracks"):
        _playlist_tracks(session, "t", pool, "7")


def test_manual_song_pick_by_title_or_id():
    import pytest
    from types import SimpleNamespace
    from carlecool.main import pick_song
    tracks = [SimpleNamespace(id="1", title="carl e cool - donkey (eah)"),
              SimpleNamespace(id="2437525044", title="carl e cool - hardcorevibes")]
    assert pick_song(tracks, "") is None
    assert pick_song(tracks, "HardcoreVibes") == "2437525044"
    assert pick_song(tracks, "1") == "1"
    with pytest.raises(ValueError):
        pick_song(tracks, "unknown song")
