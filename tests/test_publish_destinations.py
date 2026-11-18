"""Explicit platform selection must be owner-confirmed and fail closed."""
import pytest

from carlecool.approve import resolve_publish_target, ensure_target_ready
from carlecool.review import review_html, review_plain_text

ISSUE = "https://github.com/pcctradinginc-alt/carlecool-reels-automation/issues/99"
META = {
    "title": "Sample Reel",
    "duration": 30,
    "caption": "#CarleCool",
    "creative_profile": {"preset": "rubin_analog_lana_skate", "pace": "medium", "analog": 65},
}


@pytest.mark.parametrize(("command", "target"), [
    ("/approve", "instagram"),
    ("/publish", "instagram"),
    ("/publish instagram", "instagram"),
    ("/publish tiktok", "tiktok"),
    ("/publish both", "both"),
])
def test_exact_owner_commands_resolve_to_single_target(command, target):
    assert resolve_publish_target(command) == target


@pytest.mark.parametrize("command", [
    "/publish all", "/publish tiktok instagram", "/publish both ",
    "/publish tiktok\n/publish instagram", "/publish instagram extra", "/reject",
])
def test_reject_ambiguous_commands(command):
    with pytest.raises(ValueError):
        resolve_publish_target(command)


def test_tiktok_and_both_fail_before_any_platform_call():
    ensure_target_ready("instagram")
    for target in ("tiktok", "both"):
        with pytest.raises(RuntimeError, match="Neither TikTok nor Instagram"):
            ensure_target_ready(target)


def test_all_choices_are_visible_in_review_email_and_issue_stays_required():
    html = review_html(ISSUE, META)
    plain = review_plain_text(ISSUE, META)
    for command, label in [
        ("/publish instagram", "Nur Instagram"),
        ("/publish tiktok", "Nur TikTok"),
        ("/publish both", "TikTok &amp; Instagram"),
    ]:
        assert command in html and command in plain
        assert label in html
    assert html.count('href="' + ISSUE + '"') >= 3
    assert "Nur der Kommentar ist die Freigabe" in html
    assert "bis zur API-Einrichtung gesperrt" in html


def test_dry_run_does_not_pretend_it_can_publish():
    html = review_html("", META)
    assert "/publish instagram" not in html
    assert "kein Freigabelink" in html
