"""Private owned-audio Gmail roundtrip tests; no real provider calls."""
from email.message import EmailMessage
from unittest.mock import patch
import pytest

from carlecool.mailstore import fetch_owned_audio_from_sent
from carlecool.audio import locate_original
from carlecool.soundcloud import Track

class FakeIMAP:
    def __init__(self, raw, matches=b"42"):
        self.raw, self.matches = raw, matches
    def list(self):
        return ("OK", [b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"'])
    def select(self, mailbox, readonly):
        assert readonly
        return ("OK", [b"1"])
    def search(self, charset, name, query):
        assert name == "X-GM-RAW" and query.startswith('"subject:CARLECOOL_AUDIO_')
        return ("OK", [self.matches])
    def fetch(self, uid, what):
        return ("OK", [(b"RFC822", self.raw)])

def make_message(*, track_id="123", sender="owner@example.com", recipient="owner@example.com",
                 subject=None, filename=None, attachment=None):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject or f"CARLECOOL_AUDIO_{track_id}"
    msg.set_content("My original composition for CarleCool reels")
    msg.add_attachment(attachment or (b"Owned master audio" * 500), maintype="audio",
                       subtype="mpeg", filename=filename or f"{track_id}.mp3")
    return msg.as_bytes()

def test_owned_gmail_master_is_restored(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "owner@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-secret")
    path = tmp_path / "private.mp3"
    result = fetch_owned_audio_from_sent("123", path, connection=FakeIMAP(make_message()))
    assert result == path
    assert result.read_bytes().startswith(b"Owned master")

def test_reject_wrong_or_forged_master(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "owner@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-secret")
    cases = [
        make_message(sender="outsider@example.com"),
        make_message(recipient="outsider@example.com"),
        make_message(subject="CARLECOOL_AUDIO_999"),
        make_message(filename="123.txt"),
    ]
    for msg in cases:
        with pytest.raises((ValueError, RuntimeError)):
            fetch_owned_audio_from_sent("123", tmp_path / "private.mp3",
                                        connection=FakeIMAP(msg))

def test_missing_and_duplicate_master_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "owner@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-secret")
    for matches, exc in [(b"", FileNotFoundError), (b"1 2", RuntimeError)]:
        with pytest.raises(exc):
            fetch_owned_audio_from_sent("123", tmp_path / "private.mp3",
                                        connection=FakeIMAP(make_message(), matches))

def test_soundcloud_master_fallback_calls_gmail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GMAIL_ADDRESS", "owner@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-secret")
    monkeypatch.delenv("AUDIO_S3_BUCKET", raising=False)
    from carlecool import mailstore
    destination = tmp_path / "output" / "original.mp3"
    with patch.object(mailstore, "fetch_owned_audio_from_sent", return_value=destination) as m:
        assert locate_original(Track(id="123", title="my song", permalink_url=""), destination) == destination
        m.assert_called_once_with("123", destination)
