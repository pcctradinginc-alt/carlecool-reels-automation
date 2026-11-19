"""Cover-aware visual selection tests; no real network or accounts."""
import numpy as np

from carlecool.cover_visual import _allowed_cover_url, _fingerprint, fetch_cover, rank_by_cover


def test_only_official_soundcloud_image_hosts():
    assert _allowed_cover_url("https://i1.sndcdn.com/artworks-test-large.jpg")
    assert _allowed_cover_url("https://i4.sndcdn.com/artworks-test.jpg")
    assert not _allowed_cover_url("http://i1.sndcdn.com/artwork.jpg")
    assert not _allowed_cover_url("https://i1.sndcdn.com.evil.test/art.jpg")
    assert not _allowed_cover_url("https://127.0.0.1/image")
    assert not _allowed_cover_url("https://i1.sndcdn.com:444/image")


def test_invalid_url_does_not_touch_network_or_destination(tmp_path):
    class ForbiddenSession:
        def get(self, *args, **kwargs):
            raise AssertionError("Must not call network")
    path = tmp_path / "cover"
    assert not fetch_cover("https://localhost/a", path, session=ForbiddenSession())
    assert not path.exists()


def test_palette_fingerprint_is_deterministic():
    red = np.zeros((32, 32, 3), dtype=np.uint8)
    red[:, :, 0] = 255
    blue = np.zeros((32, 32, 3), dtype=np.uint8)
    blue[:, :, 2] = 255
    assert np.allclose(_fingerprint(red), _fingerprint(red))
    assert not np.allclose(_fingerprint(red), _fingerprint(blue))


def test_missing_art_retains_source_order(tmp_path):
    order, scores = rank_by_cover(tmp_path / "missing.jpg", [tmp_path / "a.mp4", tmp_path / "b.mp4"])
    assert order == [0, 1]
    assert scores == []
