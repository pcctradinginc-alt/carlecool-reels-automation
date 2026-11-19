"""Public song naming: 'carl e cool - <title>' on Instagram audio, captions and reviews."""
from pathlib import Path
from unittest.mock import MagicMock

from carlecool.main import caption_for
from carlecool.naming import song_label
from carlecool.soundcloud import Track
from carlecool.video import Video
from carlecool.zernio import Zernio


def test_label_format_and_sanitising(monkeypatch):
    monkeypatch.delenv("CARLECOOL_ARTIST_NAME", raising=False)
    assert song_label("nastro azzuro") == "carl e cool - nastro azzuro"
    assert song_label("  do\nya  ") == "carl e cool - do ya"
    assert len(song_label("x" * 300)) <= 90
    monkeypatch.setenv("CARLECOOL_ARTIST_NAME", "Carl E Cool")
    assert song_label("mikosh") == "Carl E Cool - mikosh"


def test_caption_starts_with_artist_and_title(monkeypatch):
    monkeypatch.delenv("CARLECOOL_ARTIST_NAME", raising=False)
    track = Track(id="1", title="voco babie", permalink_url="https://soundcloud.com/carlecool/x")
    assert caption_for(track, [Video("a", "coverr")]).startswith("🎧 carl e cool - voco babie\n")


def test_instagram_audio_name_is_sent_at_container_creation(tmp_path):
    from carlecool.instagram import Instagram
    mock = MagicMock()
    identity = MagicMock(); identity.json.return_value = {"data": [{"id": "1001", "username": "t"}]}
    creation = MagicMock(); creation.json.return_value = {"id": "5", "uri": "https://rupload.facebook.com/ig-api-upload/v24.0/5"}
    upload = MagicMock(); upload.json.return_value = {"success": True}
    mock.request.side_effect = [identity, creation]
    mock.post.return_value = upload
    clip = tmp_path / "c.mp4"; clip.write_bytes(b"x" * 10)
    Instagram("1001", "tok", session=mock).create_and_upload(clip, "cap", audio_name="carl e cool - mikosh")
    assert mock.request.call_args_list[1].kwargs["data"]["audio_name"] == "carl e cool - mikosh"


def test_zernio_instagram_audio_name_only_on_instagram():
    session = MagicMock()
    response = MagicMock(); response.status_code = 200
    response.json.return_value = {"post": {"_id": "p"}}
    session.post.return_value = response
    Zernio("zrk_test_long_secret", session=session).publish(
        media_url="https://media.zernio.com/temp/x.mp4", caption="c", target="both",
        instagram_id="ig", tiktok_id="tt", ai_generated=False, sha256="a" * 64,
        issue_number=3, audio_name="carl e cool - mikosh")
    platforms = {p["platform"]: p for p in session.post.call_args.kwargs["json"]["platforms"]}
    assert platforms["instagram"]["platformSpecificData"] == {"audioName": "carl e cool - mikosh"}
    assert "platformSpecificData" not in platforms["tiktok"]
