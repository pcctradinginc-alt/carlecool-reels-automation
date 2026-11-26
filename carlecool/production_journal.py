"""Daily delivery journal using existing GitHub contents API; no new paid service.

SMTP is not transactional. An ambiguous delivery must be reconciled against Sent,
never blindly retried. Only non-secret identifiers are persisted.
"""
import base64
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests

def day():
    return datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()

def path_for(date):
    if len(date) != 10 or datetime.strptime(date, "%Y-%m-%d").date().isoformat() != date:
        raise ValueError("invalid production date")
    return "data/production/" + date + ".json"

def read(date):
    from .review import github_request
    try:
        item = github_request("GET", "contents/" + path_for(date) + "?ref=main")
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None, None
        raise
    return json.loads(base64.b64decode(item["content"])), item["sha"]

def write(date, record, sha):
    from .review import github_request
    payload = {"message": "production journal " + date,
               "content": base64.b64encode(json.dumps(record, sort_keys=True).encode()).decode(),
               "branch": "main"}
    if sha:
        payload["sha"] = sha
    github_request("PUT", "contents/" + path_for(date), json_body=payload)

def sent_exists(record):
    """Read-only exact Message-ID, run and digest check. Unknown => raise."""
    import imaplib
    from email import policy
    from email.parser import BytesParser
    from email.utils import parseaddr
    from .mailstore import _sent_mailbox
    import re
    message_id = record["message_id"]
    if not re.fullmatch(r"<[A-Za-z0-9_.@-]{6,200}>", message_id):
        raise ValueError("invalid journal message id")
    with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=45) as conn:
        conn.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
        if conn.select(_sent_mailbox(conn), readonly=True)[0] != "OK":
            raise RuntimeError("Sent mailbox unavailable")
        typ, ids = conn.search(None, "X-GM-RAW", '"rfc822msgid:' + message_id + '"')
        if typ != "OK":
            raise RuntimeError("Sent search failed")
        matches = ids[0].split() if ids else []
        if not matches:
            return False
        if len(matches) != 1:
            raise RuntimeError("ambiguous Sent match")
        typ, items = conn.fetch(matches[0], "(BODY.PEEK[HEADER])")
        raw = next((x[1] for x in items if isinstance(x, tuple)), None)
        if typ != "OK" or not raw:
            raise RuntimeError("Sent header unavailable")
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        if (msg.get("Message-ID") != message_id or
            parseaddr(msg.get("From", ""))[1].lower() != os.environ["GMAIL_ADDRESS"].lower() or
            msg.get("X-CarleCool-Run-ID") != str(record["run_id"]) or
            re.sub(r"\s+", "", str(msg.get("X-CarleCool-SHA256", ""))) != record["sha256"]):
            raise RuntimeError("Sent identity mismatch")
        return True

def check(date):
    record, sha = read(date)
    if not record:
        return False
    if record["status"] == "EMAIL_SENT":
        return True
    if record["status"] == "SENDING":
        if sent_exists(record):
            record["status"] = "EMAIL_SENT"
            write(date, record, sha)
            return True
        raise RuntimeError("Delivery uncertain; manual reconciliation required; no duplicate send")
    raise RuntimeError("Unknown journal state")

def begin(date, run_id, message_id, digest):
    if check(date):
        return False
    record = {"status": "SENDING", "run_id": run_id, "message_id": message_id,
              "sha256": digest, "at": datetime.now(timezone.utc).isoformat()}
    write(date, record, None)
    return True

def complete(date, run_id):
    record, sha = read(date)
    if not record or record["run_id"] != run_id:
        raise RuntimeError("production journal ownership mismatch")
    record["status"] = "EMAIL_SENT"
    write(date, record, sha)
