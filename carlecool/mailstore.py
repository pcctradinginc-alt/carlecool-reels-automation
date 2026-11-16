"""Private Reel transport over the owner's Gmail Sent mailbox; no GitHub media artifacts.

Uses the same Gmail App Password as SMTP. Never logs attachment bytes or credentials.
"""
from __future__ import annotations

from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import hashlib
import imaplib
import json
import os
from pathlib import Path
import re


MAX_ATTACHMENT_BYTES = 16_000_000  # Gmail's ~25 MB MIME limit includes base64 overhead


def _sent_mailbox(connection) -> str:
    typ, lines = connection.list()
    if typ != 'OK':
        raise RuntimeError('Cannot list Gmail mailboxes via IMAP')
    for line in lines or []:
        value = line.decode('utf-8', 'replace') if isinstance(line, bytes) else str(line)
        if re.search(r'\\Sent\b', value, flags=re.I):
            found = re.search(r'"([^"]+)"\s*$', value)
            if not found:
                raise RuntimeError('Cannot parse Gmail Sent mailbox name')
            return '"' + found.group(1).replace('"', '') + '"'
    raise RuntimeError('Gmail Sent mailbox not found; enable IMAP for this account')


def fetch_reel_from_sent(approval: dict, target: Path, *, connection=None) -> tuple[dict, Path]:
    """Find immutable original sent by this account and verify all hashes and headers."""
    msg_id = approval.get('mail_message_id', '')
    if not re.fullmatch(r'<[A-Za-z0-9_.@-]{6,200}>', msg_id):
        raise ValueError('Missing or invalid email Message-ID in approval payload')
    address = os.environ['GMAIL_ADDRESS'].strip()
    password = os.environ['GMAIL_APP_PASSWORD'].replace(' ', '')
    if not address or not password:
        raise RuntimeError('Gmail credentials are missing')
    own = connection is None
    if own:
        connection = imaplib.IMAP4_SSL('imap.gmail.com', 993, timeout=45)
    try:
        if own:
            connection.login(address, password)
        typ, _ = connection.select(_sent_mailbox(connection), readonly=True)
        if typ != 'OK':
            raise RuntimeError('Cannot access Gmail Sent mailbox')
        typ, ids = connection.search(None, 'X-GM-RAW', f'"rfc822msgid:{msg_id}"')
        if typ != 'OK' or not ids or len(ids[0].split()) != 1:
            raise RuntimeError('Exactly one matching review email must exist in Gmail Sent')
        typ, items = connection.fetch(ids[0].split()[0], '(RFC822)')
        if typ != 'OK' or not items:
            raise RuntimeError('Cannot fetch original Gmail message')
        raw = next((x[1] for x in items if isinstance(x, tuple) and isinstance(x[1], bytes)), None)
        if raw is None:
            raise RuntimeError('Gmail did not return RFC822 email bytes')
    finally:
        if own:
            try:
                connection.logout()
            except Exception:
                pass
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    if msg['Message-ID'] != msg_id or parseaddr(msg['From'])[1].lower() != address.lower():
        raise ValueError('Gmail message identity or sender mismatch')
    if msg.get('X-CarleCool-Run-ID') != str(approval['run_id']):
        raise ValueError('Approval run identity differs from Gmail message')
    if msg.get('X-CarleCool-SHA256') != approval['sha256']:
        raise ValueError('Approval SHA differs from Gmail message')
    attachments = [part for part in msg.iter_attachments()]
    videos = [part for part in attachments if part.get_filename() == 'CarleCool-Original.mp4']
    metadatas = [part for part in attachments if part.get_filename() == 'reel_metadata.json']
    if len(videos) != 1 or len(metadatas) != 1:
        raise RuntimeError('Original Reel and metadata must be attached exactly once')
    video_bytes = videos[0].get_payload(decode=True)
    if not video_bytes or len(video_bytes) > MAX_ATTACHMENT_BYTES:
        raise ValueError('Email Reel attachment is absent or exceeds the safe size limit')
    if hashlib.sha256(video_bytes).hexdigest() != approval['sha256']:
        raise ValueError('Original Reel Gmail attachment SHA-256 mismatch')
    metadata = json.loads(metadatas[0].get_payload(decode=True))
    if metadata.get('sha256') != approval['sha256'] or str(metadata.get('track_id')) != str(approval['track_id']):
        raise ValueError('Attached metadata disagrees with approval')
    output = str(metadata.get('output', ''))
    if not re.fullmatch(r'output/carlecool_[0-9]+\.mp4', output):
        raise ValueError('Metadata contains an unsafe original file path')
    target.mkdir(parents=True, exist_ok=True)
    reel = target / output
    reel.parent.mkdir(parents=True, exist_ok=True)
    reel.write_bytes(video_bytes)
    (target / 'output/reel_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
    return metadata, reel
