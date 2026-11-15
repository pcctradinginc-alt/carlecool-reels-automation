import hashlib
import json
from pathlib import Path

import pytest

from carlecool.approve import verify_artifact
from carlecool.keywords import VIDEO_KEYWORDS, select_keywords
from carlecool.review import encode_issue_data, decode_issue_data, send_review_email


def test_keywords_cover_every_requested_cluster():
    assert len(VIDEO_KEYWORDS) == 40
    for fragment in ['skateboarding', 'graffiti', 'gen z', 'alleyway', 'night drive', 'vhs']:
        assert any(fragment in x for x in VIDEO_KEYWORDS)
    queries = select_keywords('nightdrive', .91, 143, seed='123')
    assert len(queries) == 3 and len(set(queries)) == 3
    assert set(queries).issubset(set(VIDEO_KEYWORDS))
    assert queries == select_keywords('nightdrive', .91, 143, seed='123')


def test_approval_payload_and_tamper_protection(tmp_path):
    original = tmp_path / 'reel.mp4'
    original.write_bytes(b'REAL_FILE_BYTES')
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    info = {'run_id': 44, 'sha256': sha, 'track_id': '123', 'video_ids': [str(i) for i in range(5)],
            'footage_sources': [], 'caption': 'Original caption'}
    body = 'test\n' + encode_issue_data(info)
    issue = {'state': 'open', 'labels': [{'name': 'carlecool-review'}], 'body': body}
    meta = {**info}
    assert decode_issue_data(body) == info
    assert verify_artifact(issue, meta, original, run_id=44)['track_id'] == '123'
    with pytest.raises(ValueError, match='run ID'):
        verify_artifact(issue, meta, original, run_id=45)
    original.write_bytes(b'TAMPERED')
    with pytest.raises(ValueError, match='SHA-256'):
        verify_artifact(issue, meta, original, run_id=44)
    with pytest.raises(ValueError):
        decode_issue_data('no approval payload')


def test_email_missing_secrets_never_sends(monkeypatch):
    for key in ('GMAIL_ADDRESS', 'GMAIL_APP_PASSWORD', 'REVIEW_EMAIL'):
        monkeypatch.delenv(key, raising=False)
    assert send_review_email('https://github.com/example/repo/issues/1', {'title': 'demo'}) is False
