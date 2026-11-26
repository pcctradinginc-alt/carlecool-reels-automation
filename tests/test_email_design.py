"""CarleCool Gmail editorial review: aesthetic, accessibility and safety."""
import html
import pytest
from carlecool.review import review_html, review_plain_text

META = {
    "title": "see clear",
    "permalink": "https://soundcloud.com/carlecool/see-clear",
    "duration": 30,
    "caption": "A creative reel.",
    "creative_profile": {
        "preset": "rubin_analog_lana_skate",
        "pace": "slow",
        "analog": 65,
    },
}
URL = "https://github.com/pcctradinginc-alt/carlecool-reels-automation/issues/1"


def test_gmail_contains_clear_hero_label_and_designed_approval():
    email = review_html(URL, META)
    plain = review_plain_text(URL, META)
    assert "NEUER VIDEOENTWURF" in email
    assert "CARLECOOL" in email
    assert 'href="' + URL + '"' in email
    assert "Freigabe auf GitHub öffnen" in email
    assert "CarleCool-Original.mp4" in email
    assert "65%" in email
    assert "/revise mehr natur" not in email and "Gefällt mir" not in email and "DEINE OPTIONEN" not in email
    assert "/approve" in email
    assert "/reject" in email
    assert URL in plain
    assert "MP4 im Anhang" in plain


def test_unsafe_user_fields_escaped_and_link_restricted():
    meta = dict(META, title="<script>alert(1)</script>", caption="ok")
    content = review_html(URL, meta)
    assert "<script>" not in content
    assert "&lt;script&gt;" in content
    with pytest.raises(ValueError):
        review_html("https://evil.test/issues/1", META)
    with pytest.raises(ValueError):
        review_html("https://github.com.evil.test/issues/1", META)


def test_smoke_emails_do_not_pretend_approval_is_enabled():
    content = review_html("", META)
    assert "kein Freigabelink" in content
    assert "href=\"https://github.com" not in content
    assert "TESTVORSCHAU" in review_plain_text("", META)
