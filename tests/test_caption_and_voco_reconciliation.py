"""Caption formatting and live TikTok reconciliation regression checks."""
from types import SimpleNamespace

from carlecool.main import caption_for
from carlecool.soundcloud import Track
from carlecool.state import load_state, is_already_attempted_sha


def test_requested_coverr_caption_and_hashtags():
    track = Track(id="2437525038", title="voco babie", permalink_url="https://soundcloud.com/carlecool/voco-babie")
    clip = SimpleNamespace(source="coverr", creator_name="", creator_url="")
    assert caption_for(track, [clip]) == (
        "🎧 carl e cool - voco babie\n"
        "🎬 Footage by Coverr: https://coverr.co\n\n"
        "#carlecool #instrumental #electronic #rap #producer"
    )


def test_pexels_credits_not_lost_when_switching_hashtags():
    track = Track(id="12", title="voco babie", permalink_url="https://soundcloud.com/carlecool/voco-babie")
    clip = SimpleNamespace(source="pexels", creator_name="Jane", creator_url="")
    caption = caption_for(track, [clip])
    assert "🎬 Videos provided by Pexels: https://www.pexels.com" in caption
    assert "Video by Jane on Pexels" in caption
    assert caption.endswith("#carlecool #instrumental #electronic #rap #producer")


def test_published_voco_journal_and_duplicate_guard():
    state = load_state()
    assert state["pending"] is None
    entry = next(x for x in state["published"] if x["approval_issue"] == 22)
    assert entry["provider_post_id"] == "6aff53bc0f2ada679bf1efcb"
    assert entry["platform_status"]["tiktok"] == "published"
    assert entry["platform_post_url"] == "https://www.tiktok.com/@carl_e_cool/video/7709973233797270817"
    assert entry["original_api_status"] == "uploading"
    assert is_already_attempted_sha(state, entry["sha256"])
    assert len(state["reconciled"]) == 1  # Previous uncertain Zernio attempt retained
