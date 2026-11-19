"""Pexels portrait source, Pexels credits and the end title card (offline)."""
from unittest.mock import MagicMock

import pytest

from carlecool import pexels
from carlecool.approve import validate_footage_rights
from carlecool.main import caption_for
from carlecool.soundcloud import Track
from carlecool.video import Video, gather_videos


def _hit(i, w=1080, h=1920, name="Ana"):
    return {"id": i, "url": f"https://www.pexels.com/video/x-{i}/", "image": f"https://images.pexels.com/{i}.jpg",
            "duration": 14, "user": {"name": name, "url": "https://www.pexels.com/@ana"},
            "video_files": [
                {"quality": "hd", "file_type": "video/mp4", "width": 2160, "height": 3840,
                 "link": f"https://videos.pexels.com/video-files/{i}/4k.mp4"},
                {"quality": "hd", "file_type": "video/mp4", "width": w, "height": h,
                 "link": f"https://videos.pexels.com/video-files/{i}/hd.mp4"},
                {"quality": "sd", "file_type": "video/mp4", "width": 540, "height": 960,
                 "link": f"https://videos.pexels.com/video-files/{i}/sd.mp4"}]}


def _session(videos):
    session = MagicMock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = {"videos": videos}
    return session


def test_portrait_query_picks_1080p_file_and_credits_creator():
    session = _session([_hit(1), _hit(2)])
    found = pexels.search_pexels("key", ["palm trees golden hour"], set(), session=session)
    assert [v.id for v in found] == ["px-1", "px-2"]
    assert found[0].url.endswith("/1/hd.mp4") and found[0].vertical and found[0].source == "pexels"
    assert found[0].creator_name == "Ana" and found[0].query == "palm trees golden hour"
    params = session.get.call_args_list[0].kwargs["params"]
    assert params["orientation"] == "portrait" and params["query"] == "palm trees golden hour"
    assert session.get.call_args_list[0].kwargs["headers"] == {"Authorization": "key"}


def test_landscape_files_and_recent_ids_are_skipped():
    session = _session([_hit(3, w=1920, h=1080), _hit(4)])
    found = pexels.search_pexels("key", ["river flowing natural light"], {"px-4"}, session=session)
    # Item 3 still has a portrait 4K file but no 1080p portrait; 4K is accepted only as last choice.
    assert [v.id for v in found] == ["px-3"] and found[0].url.endswith("4k.mp4")


def test_pexels_first_then_coverr_only_when_key_set(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "assets/stock").mkdir(parents=True)
    (tmp_path / "assets/stock/manifest.json").write_text('{"clips": []}')
    monkeypatch.setattr(pexels, "search_pexels", lambda *a, **k: [Video("px-9", "pexels", url="https://videos.pexels.com/v.mp4")])
    monkeypatch.setattr("carlecool.video.search_coverr", lambda *a, **k: [Video("c1", "coverr", url="https://storage.coverr.co/a.mp4")])
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert [v.id for v in gather_videos("k", "calm", set(), keywords=["river"])] == ["c1"]
    monkeypatch.setenv("PEXELS_API_KEY", "abc")
    assert [v.id for v in gather_videos("k", "calm", set(), keywords=["river"])] == ["px-9", "c1"]


def test_caption_link_in_bio_and_pexels_credit_passes_rights_check(monkeypatch):
    monkeypatch.delenv("CARLECOOL_ARTIST_NAME", raising=False)
    track = Track(id="1", title="mikosh", permalink_url="https://soundcloud.com/carlecool/mikosh")
    videos = [Video("px-1", "pexels", creator_name="Ana"), Video("px-2", "pexels", creator_name="Ana")]
    caption = caption_for(track, videos)
    assert caption.startswith("🎧 carl e cool - mikosh\n🎶 Full track: Link in Bio\n")
    assert "https://www.pexels.com" in caption and caption.count("Video by Ana on Pexels") == 1
    validate_footage_rights({"caption": caption, "footage_sources": [{"provider": "pexels"}]})
    with pytest.raises(RuntimeError, match="Pexels"):
        validate_footage_rights({"caption": "no credit", "footage_sources": [{"provider": "pexels"}]})


def test_title_card_png_is_transparent_and_centred(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    from carlecool.titlecard import make_title_card
    path = make_title_card("carl e cool", "nastro azzuro: 'take 2'", 270, 480, tmp_path / "c.png")
    with Image.open(path) as img:
        assert img.size == (270, 480) and img.mode == "RGBA"
        alpha = img.getchannel("A")
        assert alpha.getpixel((5, 5)) == 0 and alpha.getpixel((5, 470)) == 0  # corners clear
        box = alpha.getbbox()
        assert box and 150 < (box[1] + box[3]) / 2 < 270  # text block slightly above centre
    assert make_title_card("carl e cool", "   ", 270, 480, tmp_path / "x.png") is None
