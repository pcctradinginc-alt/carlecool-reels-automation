"""Gmail review has a clickable but non-publishing approval link."""
from email.utils import make_msgid
from pathlib import Path
from unittest.mock import patch
import hashlib

from carlecool.review import send_review_email


def test_review_email_contains_safe_clickable_github_link(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "owner@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "notreal")
    monkeypatch.setenv("REVIEW_EMAIL", "owner@example.com")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"synthetic_media_only")
    sha = hashlib.sha256(media.read_bytes()).hexdigest()
    data = {"title": "Test Song", "sha256": sha,
            "track_id": "123", "caption": "Test",
            "output": "output/carlecool_123.mp4",
            "creative_profile": {"preset": "rubin_lana", "pace": "slow",
                                 "analog": 65, "weights": {"nature": 40}}}
    sent = []
    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, msg): sent.append(msg)
    url = "https://github.com/owner/repo/issues/123"
    with patch("carlecool.review.smtplib.SMTP_SSL", SMTP):
        assert send_review_email(url, data, media, run_id=111,
                                 message_id=make_msgid(domain="carlecool.invalid"))
    html = sent[0].get_body(preferencelist=("html",)).get_content()
    text = sent[0].get_body(preferencelist=("plain",)).get_content()
    assert f'href="{url}"' in html
    assert "/revise mehr natur, weniger skate" in html
    assert "/approve" in text
    assert url in text
    assert sorted(x.get_filename() for x in sent[0].iter_attachments()) == [
        "CarleCool-Original.mp4", "reel_metadata.json"
    ]
