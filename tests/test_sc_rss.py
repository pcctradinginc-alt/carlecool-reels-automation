import pytest
from carlecool.sc_rss import inspect_feed, public_rss_url

RSS = b'''<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><guid>tag:soundcloud,2010:tracks/100</guid><enclosure url="https://feeds.soundcloud.com/stream/100.mp3" type="audio/mpeg"/></item>
<item><guid>tag:soundcloud,2010:tracks/101</guid><enclosure url="https://feeds.soundcloud.com/stream/101.mp3" type="audio/mpeg"/></item>
<item><guid>tag:soundcloud,2010:tracks/999</guid><enclosure url="http://unsafe/999.mp3" type="audio/mpeg"/></item>
</channel></rss>'''


def test_rss_index_only_matches_tracks_with_valid_audio_enclosures():
    assert inspect_feed(RSS, {"100", "123"}) == {"rss_audio_entries": 2, "newest_20_matched": 1}


def test_invalid_xml_and_id_rejected():
    with pytest.raises(ValueError):
        inspect_feed(b"<broken>", {"100"})
    with pytest.raises(ValueError):
        public_rss_url("../unsafe")
    assert public_rss_url("123").endswith("soundcloud:users:123/sounds.rss")


def test_rss_inspection_never_downloads_audio():
    import inspect
    import carlecool.sc_rss as module
    source = inspect.getsource(module)
    assert "requests.get" not in source and "download_url" not in source



def test_find_specific_rss_enclosure(monkeypatch):
    import carlecool.sc_rss as rss
    monkeypatch.setattr(rss, "_safe_audio_url", lambda url: None)
    assert rss.matching_rss_audio_url(RSS, "100").endswith("/stream/100.mp3")
    with pytest.raises(FileNotFoundError):
        rss.matching_rss_audio_url(RSS, "700")


def test_private_urls_and_unsafe_ids_are_rejected():
    import carlecool.sc_rss as rss
    with pytest.raises(ValueError):
        rss._safe_audio_url("https://127.0.0.1/track.mp3")
    with pytest.raises(ValueError):
        rss._safe_audio_url("https://evil.example/track.mp3")
    with pytest.raises(ValueError):
        rss.matching_rss_audio_url(RSS, "../../secret")
