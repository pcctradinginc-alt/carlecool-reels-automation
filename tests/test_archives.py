"""NASA / Prelinger archival footage (offline, mocked HTTP)."""
from unittest.mock import MagicMock

import pytest

from carlecool import archives


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def test_nasa_search_drops_talks_and_third_party_imagery():
    items = [
        {"href": "https://images-assets.nasa.gov/video/a/collection.json",
         "data": [{"nasa_id": "a", "title": "Jupiter's Hot Spots", "keywords": ["Jupiter"]}]},
        {"href": "x", "data": [{"nasa_id": "b", "title": "NASA Science Live: Mars", "keywords": []}]},
        {"href": "x", "data": [{"nasa_id": "c", "title": "Ask NASA: why the Moon"}]},
        {"href": "x", "data": [{"nasa_id": "d", "title": "Milky Way", "description": "Credit: ESA/Herschel"}]},
        {"href": "x", "data": [{"nasa_id": "e", "title": "Saturn Rings"}]},
    ]
    session = MagicMock()
    session.get.return_value = _resp({"collection": {"items": items}})
    found = archives.search_nasa(["jupiter"], {"nasa-e"}, session=session)
    assert [i["id"] for i in found] == ["nasa-a"]


def test_nasa_rendition_prefers_original_on_nasa_host():
    session = MagicMock()
    session.get.return_value = _resp([
        "http://images-assets.nasa.gov/video/a b/a b~large.mp4",
        "http://images-assets.nasa.gov/video/a b/a b~orig.mp4",
        "http://evil.example/a~orig.mp4"])
    url = archives.nasa_media_url({"manifest": "http://images-assets.nasa.gov/video/a b/collection.json"},
                                  session=session)
    assert url == "https://images-assets.nasa.gov/video/a%20b/a%20b~orig.mp4"
    with pytest.raises(ValueError):
        archives.nasa_media_url({"manifest": "https://evil.example/collection.json"}, session=session)


def test_prelinger_only_public_domain_amateur_films_without_ads_or_disasters():
    docs = [
        {"identifier": "Summersc1941", "title": "[Amateur film: San Francisco]",
         "licenseurl": "http://creativecommons.org/licenses/publicdomain/"},
        {"identifier": "nolicense", "title": "Amateur film: beach", "licenseurl": None},
        {"identifier": "Signal301959", "title": "Signal 30 (amateur film)",
         "licenseurl": "http://creativecommons.org/licenses/publicdomain/"},
        {"identifier": "Designfo1956", "title": "Amateur film: Chevrolet Motorama",
         "licenseurl": "http://creativecommons.org/licenses/publicdomain/"},
    ]
    session = MagicMock()
    session.get.return_value = _resp({"response": {"docs": docs}})
    found = archives.search_prelinger(["amateur film"], set(), session=session)
    assert [i["id"] for i in found] == ["pl-Summersc1941"]
    q = session.get.call_args.kwargs["params"]["q"]
    assert "licenseurl:*publicdomain*" in q and 'title:"amateur film"' in q


def test_prelinger_media_requires_public_domain_metadata_and_picks_largest_mp4():
    session = MagicMock()
    session.get.return_value = _resp({"metadata": {"licenseurl": "http://creativecommons.org/licenses/publicdomain/"},
                                      "files": [{"name": "a_512kb.mp4", "width": "320", "length": "600"},
                                                {"name": "a.mp4", "width": "640", "length": "600"},
                                                {"name": "a.ogv", "width": "800", "length": "600"}]})
    url, length = archives.prelinger_media({"identifier": "a"}, session=session)
    assert url == "https://archive.org/download/a/a.mp4" and length == 600
    session.get.return_value = _resp({"metadata": {}, "files": []})
    with pytest.raises(ValueError, match="public domain"):
        archives.prelinger_media({"identifier": "a"}, session=session)


def test_segment_start_skips_intro_and_outro_and_varies():
    starts = {archives.segment_start(1000, f"k{i}") for i in range(30)}
    assert all(150 <= s <= 750 for s in starts) and len(starts) > 20


def test_segment_host_allowlist():
    with pytest.raises(ValueError):
        archives.cut_segment("https://evil.example/x.mp4", 0, __import__("pathlib").Path("x.mp4"))


def test_no_model_means_no_archive_footage(monkeypatch):
    monkeypatch.setattr(archives, "_remote_frame", lambda url, at: object())
    monkeypatch.setattr(archives, "frame_margin", lambda img, source: float("nan"))
    start, _ = archives.best_offset("https://archive.org/x.mp4", 600, "prelinger", "k")
    assert start is None


def test_unknown_style_or_disabled_returns_nothing(monkeypatch, tmp_path):
    assert archives.fetch_archival(None, set(), tmp_path) == []
    monkeypatch.setenv("CARLECOOL_ARCHIVES", "false")
    assert archives.fetch_archival("rubin", set(), tmp_path) == []
