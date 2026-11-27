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
import time


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
    """Retry only transient read-only IMAP failures; never retry an upload."""
    if connection is not None:
        return _fetch_reel_once(approval, target, connection=connection)
    for attempt in range(3):
        try:
            return _fetch_reel_once(approval, target)
        except (TimeoutError, ConnectionError, imaplib.IMAP4.abort) as exc:
            if attempt == 2:
                raise RuntimeError('Gmail original retrieval failed after three attempts; no publication') from None
            print('Transient Gmail retrieval failure; retrying:', type(exc).__name__)
            time.sleep(2 ** (attempt + 1))


def _fetch_reel_once(approval: dict, target: Path, *, connection=None) -> tuple[dict, Path]:
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
        connection = imaplib.IMAP4_SSL('imap.gmail.com', 993, timeout=120)
    try:
        if own:
            connection.login(address, password)
        typ, _ = connection.select(_sent_mailbox(connection), readonly=True)
        if typ != 'OK':
            raise RuntimeError('Cannot access Gmail Sent mailbox')
        typ, ids = connection.search(None, 'X-GM-RAW', f'"rfc822msgid:{msg_id}"')
        if typ != 'OK' or not ids or len(ids[0].split()) != 1:
            raise RuntimeError('Exactly one matching review email must exist in Gmail Sent')
        typ, items = connection.fetch(ids[0].split()[0], '(BODY.PEEK[])')
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
    # Email parsers may preserve whitespace from folded long custom headers.
    # Remove folding whitespace only; never relax the 64-character digest check.
    header_sha = re.sub(r'\s+', '', str(msg.get('X-CarleCool-SHA256', '')))
    if not re.fullmatch(r'[0-9a-f]{64}', header_sha) or header_sha != approval['sha256']:
        raise ValueError('Approval SHA differs from Gmail message')
    attachments = [part for part in msg.iter_attachments()]
    metadatas = [part for part in attachments if part.get_filename() == 'reel_metadata.json']
    if len(metadatas) != 1:
        raise RuntimeError('Reel metadata must be attached exactly once')
    metadata = json.loads(metadatas[0].get_payload(decode=True))
    if metadata.get('sha256') != approval['sha256'] or str(metadata.get('track_id')) != str(approval['track_id']):
        raise ValueError('Attached metadata disagrees with approval')
    output = str(metadata.get('output', ''))
    if not re.fullmatch(r'output/carlecool_[0-9]+\.mp4', output):
        raise ValueError('Metadata contains an unsafe original file path')
    target.mkdir(parents=True, exist_ok=True)
    reel = target / output
    reel.parent.mkdir(parents=True, exist_ok=True)
    storage = approval.get('master_storage')
    if storage:
        # Full-quality master lives in private object storage; the email (still
        # required, so deleting it cancels the approval) carries only a preview.
        if metadata.get('master_storage') != storage:
            raise ValueError('Master storage location differs between email and approval')
        from .masterstore import download_master
        try:
            download_master(storage, reel, expected_sha256=approval['sha256'])
        except FileNotFoundError:
            # Actions-cache master expired (> 7 days unused): publish the e-mailed preview
            # instead of failing — verified against the preview digest in the mailed metadata.
            previews = [p for p in attachments if p.get_filename() == 'CarleCool-Preview.mp4']
            data = previews[0].get_payload(decode=True) if len(previews) == 1 else b''
            if not data or not metadata.get('preview_sha256') or \
                    hashlib.sha256(data).hexdigest() != metadata['preview_sha256']:
                raise
            print('Master expired in the Actions cache; publishing the verified e-mail preview')
            reel.write_bytes(data)
    else:
        videos = [part for part in attachments if part.get_filename() == 'CarleCool-Original.mp4']
        if len(videos) != 1:
            raise RuntimeError('Original Reel and metadata must be attached exactly once')
        video_bytes = videos[0].get_payload(decode=True)
        if not video_bytes or len(video_bytes) > MAX_ATTACHMENT_BYTES:
            raise ValueError('Email Reel attachment is absent or exceeds the safe size limit')
        if hashlib.sha256(video_bytes).hexdigest() != approval['sha256']:
            raise ValueError('Original Reel Gmail attachment SHA-256 mismatch')
        reel.write_bytes(video_bytes)
    (target / 'output/reel_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
    return metadata, reel



def fetch_owned_audio_from_sent(track_id: str, destination: Path, *, connection=None) -> Path:
    """Get an owner's manually emailed song master from the private Gmail Sent mailbox.

    Owner sends an email to themself with exact subject CARLECOOL_AUDIO_<track_id>
    and exactly one attachment named <track_id>.mp3/.wav/.flac/.m4a.
    Credentials stay in GitHub Secrets and file bytes never enter GitHub artifacts.
    """
    if not re.fullmatch(r"[0-9]{1,22}", str(track_id)):
        raise ValueError("SoundCloud track ID must be numeric")
    address = os.getenv("GMAIL_ADDRESS", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not address or not password:
        raise FileNotFoundError("Gmail credentials are missing for private master audio")
    own = connection is None
    if own:
        connection = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=45)
    try:
        if own:
            connection.login(address, password)
        typ, _ = connection.select(_sent_mailbox(connection), readonly=True)
        if typ != "OK":
            raise RuntimeError("Cannot access Gmail Sent mailbox for audio masters")
        subject = f"CARLECOOL_AUDIO_{track_id}"
        typ, ids = connection.search(None, "X-GM-RAW", f'"subject:{subject}"')
        if typ != "OK":
            raise RuntimeError("Gmail search failed")
        matching = (ids[0].split() if ids else [])
        if not matching:
            raise FileNotFoundError("No matching private audio master email in Gmail Sent")
        # Reject ambiguous email matches rather than using an unintended old master.
        if len(matching) != 1:
            raise RuntimeError("Multiple master emails found; keep one exact original per track")
        typ, items = connection.fetch(matching[0], "(RFC822)")
        if typ != "OK" or not items:
            raise RuntimeError("Gmail master message fetch failed")
        raw = next((item[1] for item in items if isinstance(item, tuple)
                    and isinstance(item[1], bytes)), None)
        if raw is None:
            raise RuntimeError("Gmail master email has no message content")
    finally:
        if own:
            try:
                connection.logout()
            except Exception:
                pass
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if str(message["Subject"] or "").strip() != subject:
        raise ValueError("Gmail master subject does not match SoundCloud track ID")
    if parseaddr(str(message["From"] or ""))[1].lower() != address.lower():
        raise ValueError("Gmail master was not sent from the configured owner account")
    if address.lower() not in [a.strip().lower() for _, a in __import__("email.utils", fromlist=["getaddresses"]).getaddresses(message.get_all("To", []))]:
        raise ValueError("Gmail master must have been sent to the owner's own Gmail address")
    allowed = {f"{track_id}.{ext}" for ext in ("mp3", "wav", "flac", "m4a")}
    parts = [a for a in message.iter_attachments()
             if (a.get_filename() or "").lower() in allowed]
    if len(parts) != 1:
        raise RuntimeError("Expected one exact SoundCloud-ID-named audio attachment")
    data = parts[0].get_payload(decode=True)
    if not data or len(data) > 23_000_000 or len(data) < 4096:
        raise RuntimeError("Original audio attachment missing, suspicious, or too large (max 23 MB)")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination
