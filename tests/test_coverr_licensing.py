"""Coverage for Coverr Demo API license and public-log redaction."""
from unittest.mock import MagicMock
import pytest

from carlecool.video import _coverr_creator_metadata, record_coverr_download, Video
from carlecool.main import caption_for
from carlecool.soundcloud import Track


def test_coverr_creator_credit_from_canonical_profile():
    name, url = _coverr_creator_metadata({
        "creator": {"name": "J. Creator", "profile_url": "https://coverr.co/@j-creator"}
    })
    assert (name, url) == ("J. Creator", "https://coverr.co/@j-creator")
    assert _coverr_creator_metadata({"creator": {"name": "Fake", "profile_url": "https://evil.example/"}}) == ("", "")


def test_caption_credits_coverr_and_named_creators():
    reel = caption_for(
        Track(id="123", title="CarleCool Track", permalink_url="https://soundcloud.com/carlecool/test"),
        [Video("vid1", "coverr", creator_name="J. Creator", creator_url="https://coverr.co/@j-creator"),
         Video("vid2", "coverr", creator_name="J. Creator", creator_url="https://coverr.co/@j-creator")],
    )
    assert "https://coverr.co" in reel
    assert reel.count("Video by J. Creator") == 1
    assert "Link in Bio" not in reel and "soundcloud.com" not in reel


def test_download_tracking_only_acknowledged_on_204():
    session = MagicMock()
    session.patch.return_value.status_code = 204
    session.patch.return_value.raise_for_status.return_value = None
    record_coverr_download("abc_123", "fake-api-key", session=session)
    url = session.patch.call_args.args[0]
    assert url == "https://api.coverr.co/videos/abc_123/stats/downloads"
    assert session.patch.call_args.kwargs["headers"]["x-api-key"] == "fake-api-key"
    session.patch.return_value.status_code = 200
    with pytest.raises(RuntimeError, match="did not acknowledge"):
        record_coverr_download("abc_123", "fake-api-key", session=session)


def test_coverr_download_tracking_rejects_path_injection():
    with pytest.raises(ValueError, match="Unsafe"):
        record_coverr_download("../../test", "fake-api-key", session=MagicMock())
