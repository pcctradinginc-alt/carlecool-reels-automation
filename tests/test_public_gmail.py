"""Mocked transport tests: never talk to real Gmail, Instagram, or GitHub."""
from email.message import EmailMessage
from email.utils import make_msgid
import hashlib
import json
from unittest.mock import patch

import pytest

from carlecool.mailstore import MAX_ATTACHMENT_BYTES, fetch_reel_from_sent
from carlecool.review import send_review_email


class FakeSMTP:
    outgoing = None
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def login(self, sender, password):
        assert sender == 'artist@example.com'
        assert password == 'apppassword'
    def send_message(self, msg):
        self.outgoing = msg
        FakeSMTP.outgoing = msg


class FakeIMAP:
    def __init__(self, email_bytes):
        self.email_bytes = email_bytes
    def list(self):
        return ('OK', [b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"'])
    def select(self, mailbox, readonly):
        assert mailbox == '"[Gmail]/Sent Mail"'
        assert readonly is True
        return ('OK', [b'1'])
    def search(self, charset, name, query):
        assert name == 'X-GM-RAW' and query.startswith('"rfc822msgid:')
        return ('OK', [b'42'])
    def fetch(self, which, fields):
        assert which == b'42' and fields == '(BODY.PEEK[])'
        return ('OK', [(b'42 (RFC822 {1000}', self.email_bytes), b')'])


def make_video_email(tmp_path, monkeypatch):
    monkeypatch.setenv('GMAIL_ADDRESS', 'artist@example.com')
    monkeypatch.setenv('GMAIL_APP_PASSWORD', 'app password')
    monkeypatch.setenv('REVIEW_EMAIL', 'artist@example.com')
    reel = tmp_path / 'carlecool_111.mp4'
    reel.write_bytes(b'ORIGINAL PRIVATE AUDIO VIDEO FILE')
    digest = hashlib.sha256(reel.read_bytes()).hexdigest()
    metadata = {'sha256': digest, 'track_id': '111', 'title': 'private mock',
                'output': 'output/carlecool_111.mp4', 'caption': 'test'}
    message_id = make_msgid(domain='carlecool.invalid')
    with patch('carlecool.review.smtplib.SMTP_SSL', FakeSMTP):
        assert send_review_email('https://github.com/test/repo/issues/1', metadata, reel,
                                 message_id=message_id, run_id=222)
    approval = {'sha256': digest, 'track_id': '111', 'run_id': 222, 'mail_message_id': message_id}
    return approval, FakeSMTP.outgoing


def test_public_repo_mail_original_is_private_and_exact(tmp_path, monkeypatch):
    approval, message = make_video_email(tmp_path, monkeypatch)
    result, restored = fetch_reel_from_sent(approval, tmp_path / 'approval',
                                           connection=FakeIMAP(message.as_bytes()))
    assert restored.read_bytes() == b'ORIGINAL PRIVATE AUDIO VIDEO FILE'
    assert result['sha256'] == hashlib.sha256(restored.read_bytes()).hexdigest()
    assert (tmp_path / 'approval/output/reel_metadata.json').exists()


def test_tampered_email_attachment_is_rejected(tmp_path, monkeypatch):
    approval, original = make_video_email(tmp_path, monkeypatch)
    changed = EmailMessage()
    for k, v in original.items():
        if k.lower() not in ('mime-version', 'content-type'):
            changed[k] = v
    changed.set_content('tampered')
    changed.add_attachment(b'MODIFIED AUDIO', maintype='video', subtype='mp4', filename='CarleCool-Original.mp4')
    changed.add_attachment(json.dumps({'sha256': approval['sha256'], 'track_id': '111',
        'output': 'output/carlecool_111.mp4'}).encode(), maintype='application', subtype='json', filename='reel_metadata.json')
    with pytest.raises(ValueError, match='SHA-256'):
        fetch_reel_from_sent(approval, tmp_path / 'approval', connection=FakeIMAP(changed.as_bytes()))


def test_missing_mail_identity_is_rejected(tmp_path, monkeypatch):
    approval, msg = make_video_email(tmp_path, monkeypatch)
    approval['mail_message_id'] = '<unrelated@carlecool.invalid>'
    with pytest.raises(ValueError, match='identity'):
        fetch_reel_from_sent(approval, tmp_path / 'approval', connection=FakeIMAP(msg.as_bytes()))


def test_invalid_mail_id_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('GMAIL_ADDRESS', 'artist@example.com')
    monkeypatch.setenv('GMAIL_APP_PASSWORD', 'app-password')
    with pytest.raises(ValueError, match='Message-ID'):
        fetch_reel_from_sent({'mail_message_id': 'BAD'}, tmp_path / 'approval')


def test_oversize_original_rejected_before_smtp(tmp_path, monkeypatch):
    monkeypatch.setenv('GMAIL_ADDRESS', 'artist@example.com')
    monkeypatch.setenv('GMAIL_APP_PASSWORD', 'app-password')
    monkeypatch.setenv('REVIEW_EMAIL', 'artist@example.com')
    reel = tmp_path / 'big.mp4'
    reel.write_bytes(b'x' * (MAX_ATTACHMENT_BYTES + 1))
    with pytest.raises(RuntimeError, match='too large'):
        send_review_email('https://github.com/a/b/issues/1', {'title': 'test'}, reel,
                          message_id=make_msgid(domain='carlecool.invalid'), run_id=1)


def test_transient_gmail_login_retries(monkeypatch, tmp_path):
    from carlecool import mailstore
    from unittest.mock import Mock
    fetch = Mock(side_effect=[TimeoutError(), ConnectionResetError(), ({}, tmp_path / 'video.mp4')])
    monkeypatch.setattr(mailstore, '_fetch_reel_once', fetch)
    monkeypatch.setattr(mailstore.time, 'sleep', lambda _: None)
    assert mailstore.fetch_reel_from_sent({}, tmp_path)[1] == tmp_path / 'video.mp4'
    assert fetch.call_count == 3

def test_invalid_gmail_identity_never_retried(monkeypatch, tmp_path):
    from carlecool import mailstore
    from unittest.mock import Mock
    fetch = Mock(side_effect=ValueError('SHA mismatch'))
    monkeypatch.setattr(mailstore, '_fetch_reel_once', fetch)
    with pytest.raises(ValueError, match='SHA mismatch'):
        mailstore.fetch_reel_from_sent({}, tmp_path)
    assert fetch.call_count == 1
