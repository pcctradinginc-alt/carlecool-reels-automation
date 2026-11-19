"""Regression checks for archival reconciliation of a former Zernio pending upload."""
from datetime import datetime, timezone

from carlecool.soundcloud import Track
from carlecool.state import is_already_attempted_sha, load_state, pick_track


def test_reconciled_pending_archived_and_history_preserved():
    state = load_state()
    assert state["pending"] is None
    assert all(x["approval_issue"] != 5 for x in state["published"])  # Historical #5 is not claimed published.
    archived = state["reconciled"][0]
    assert archived["provider"] == "zernio"
    assert archived["issue_number"] == 5
    assert archived["provider_post_id"] == "6afe0ad51aa26586507fb314"
    assert archived["platform_status"]["tiktok"] == "uploading"
    assert archived["reconciliation_status"] == "historical_attempt_archived_publication_not_verified"
    assert is_already_attempted_sha(state, archived["sha256"])
    assert not is_already_attempted_sha(state, "0" * 64)


def test_archived_attempt_cooldown_does_not_block_other_track():
    state = load_state()
    prior = Track(id="2373071753", title="old", permalink_url="https://soundcloud.com/example/old")
    fresh = Track(id="2419839138", title="new", permalink_url="https://soundcloud.com/example/new")
    selected = pick_track([prior, fresh], state, cooldown_days=19,
                          now=datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc))
    assert selected.id == fresh.id


def test_old_duplicate_bytes_blocked_in_zernio_and_instagram_guards():
    from inspect import getsource
    from carlecool.approve import publish, publish_via_zernio

    assert "is_already_attempted_sha(state, approval['sha256'])" in getsource(publish)
    assert "is_already_attempted_sha(state, approval['sha256'])" in getsource(publish_via_zernio)
