"""Signed email actions must not be guessable, reusable or auto-post on click."""
import hashlib
import hmac
import re
from urllib.parse import urlsplit

import pytest

from carlecool.approval_links import approval_links
from carlecool.review import review_html, review_plain_text

ISSUE = "https://github.com/pcctradinginc-alt/carlecool-reels-automation/issues/57"
META = {"title": "See Clear", "sha256": "f" * 64, "duration": 30,
        "caption": "Artist own track", "creative_profile": {"pace": "medium", "analog": 65}}
SECRET = "use-at-least-32-random-characters-as-secret-for-tests"


def test_four_links_are_distinct_and_match_worker_hmac_protocol():
    links = approval_links(ISSUE, META, 42, base_url="https://carlecool-approval.example.workers.dev",
                           secret=SECRET, now=1780000000)
    assert set(links) == {"instagram", "tiktok", "both", "discard"}
    assert len(set(links.values())) == 4
    for choice, link in links.items():
        path = urlsplit(link).path.removeprefix("/")
        assert path.startswith("review/57/42/" + "f" * 64 + "/" + choice + "/")
        payload, signature = path.rsplit("/", 1)
        assert hmac.compare_digest(hmac.new(SECRET.encode(), payload.encode(),
                                            hashlib.sha256).hexdigest(), signature)


def test_buttons_open_distinct_safe_links_and_offer_discard_option():
    links = approval_links(ISSUE, META, 42, base_url="https://carlecool-approval.example.workers.dev",
                           secret=SECRET, now=1780000000)
    html = review_html(ISSUE, META, direct_links=links)
    plain = review_plain_text(ISSUE, META, direct_links=links)
    for choice, link in links.items():
        assert link in html and link in plain
    assert "Nicht veröffentlichen – Entwurf löschen" in html
    assert "Ein Linkklick allein löst nichts aus" in html
    assert "Entwurf löschen bedeutet Freigabe verwerfen" in plain


@pytest.mark.parametrize(("base", "key"), [
    ("http://bad.example", SECRET),
    ("https://real.example.evil.com/path", SECRET),
    ("https://real.example", "short"),
    ("https://real.example", ""),
    ("", SECRET),
    ("https://real.example/?redirect=evil", SECRET),
])
def test_invalid_or_partial_worker_config_is_fail_closed(base, key):
    with pytest.raises((RuntimeError, ValueError)):
        approval_links(ISSUE, META, 42, base_url=base, secret=key)


def test_no_worker_config_preserves_fallback_without_forged_links():
    assert approval_links(ISSUE, META, 42, base_url="", secret="") == {}
    content = review_html(ISSUE, META)
    assert "Nicht veröffentlichen – Entwurf löschen" in content
    assert "href=\"" + ISSUE + "\"" in content
    assert "/reject" in review_plain_text(ISSUE, META)


def test_bad_issue_or_sha_fails_closed():
    with pytest.raises(ValueError):
        approval_links("https://bad.example/issues/4", META, 42,
                       base_url="https://worker.example", secret=SECRET)
    with pytest.raises(ValueError):
        approval_links(ISSUE, dict(META, sha256="invalid"), 42,
                       base_url="https://worker.example", secret=SECRET)
