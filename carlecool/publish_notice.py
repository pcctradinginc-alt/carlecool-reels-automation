"""Private owner status notification. Never creates or retries a social post."""
from __future__ import annotations

import base64
from email.message import EmailMessage
import json
import os
import smtplib
from urllib.parse import urlparse

from .approve import resolve_publish_target
from .review import github_request


def _safe_link(value, platform):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    hosts = {"tiktok": {"www.tiktok.com", "tiktok.com"}, "instagram": {"www.instagram.com", "instagram.com"}}
    if parsed.scheme == "https" and parsed.hostname in hosts.get(platform, set()) and not parsed.username and not parsed.password and not parsed.port:
        return parsed._replace(query="", fragment="").geturl()
    return None


def describe(state, issue, target, outcomes, ai_unconfirmed=False):
    requested = {"tiktok": ["tiktok"], "instagram": ["instagram"], "both": ["tiktok", "instagram"]}[target]
    record = next((r for r in reversed(state.get("published", [])) if r.get("approval_issue") == issue), None)
    if record:
        statuses = record.get("platform_status") or ({"instagram": "published"} if record.get("instagram_media_id") else {})
        if all(statuses.get(p) == "published" for p in requested):
            lines = ["Der Anbieter meldet die Veröffentlichung als abgeschlossen."]
            urls = record.get("platform_post_urls") or {}
            for platform in requested:
                url = _safe_link(urls.get(platform), platform)
                lines.append(f"{platform}: {url or 'veröffentlicht laut Anbieter; öffentliche Post-URL fehlt'}")
            lines.append("Eine unabhängige Prüfung der Sichtbarkeit auf der Plattform wurde nicht durchgeführt.")
            return "Veröffentlichung bestätigt (Anbieter)", "\n".join(lines)
    pending = state.get("pending") or {}
    if pending.get("issue_number") == issue:
        return "Veröffentlichung ungeklärt", "Ein Upload wurde reserviert oder gestartet. Bitte Zernio prüfen; keine automatische Wiederholung."
    for key, reason in (
        ("preflight", "Veröffentlichungsziel oder Zugang nicht freigegeben."),
        ("source", "Freigabe oder Original-Referenz konnte nicht bestätigt werden."),
        ("restore", "Originalvideo konnte nicht sicher aus Gmail wiederhergestellt werden."),
        ("rights", "KI-Vertriebsfreigabe fehlt oder Original/Lizenzprüfung nicht bestanden." if ai_unconfirmed else "Original- oder Lizenzprüfung fehlgeschlagen."),
    ):
        if outcomes.get(key) == "failure":
            return "Nicht veröffentlicht", reason + " Es wurde in diesem Lauf kein Upload gestartet."
    return "Veröffentlichung nicht bestätigt", "Bitte Workflow und Zernio prüfen. Keine automatische Wiederholung eines möglicherweise gestarteten Uploads."


def main():
    issue = int(os.environ["REVIEW_ISSUE"])
    target = resolve_publish_target(os.environ["PUBLISH_COMMAND"])
    sender = os.environ["GMAIL_ADDRESS"].strip()
    recipient = os.environ["REVIEW_EMAIL"].strip()
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    if not sender or not recipient or not password:
        raise RuntimeError("Publication outcome email credentials missing")
    outcomes = {k: os.getenv(k.upper() + "_OUTCOME", "") for k in ("preflight", "source", "restore", "rights", "publish")}
    try:
        item = github_request("GET", "contents/data/state.json?ref=main")
        state = json.loads(base64.b64decode(item["content"]))
    except Exception:
        state = {}
    subject, body = describe(state, issue, target, outcomes, os.getenv("AI_LICENSE_CONFIRMED") != "true")
    repo = os.environ["GITHUB_REPOSITORY"]
    run = int(os.environ["GITHUB_RUN_ID"])
    msg = EmailMessage()
    msg["From"], msg["To"] = sender, recipient
    msg["Subject"] = f"CarleCool – {target}: {subject}"
    msg.set_content(f"{body}\n\nFreigabe #{issue}\nWorkflow: https://github.com/{repo}/actions/runs/{run}\n")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
        smtp.login(sender, password)
        if smtp.send_message(msg):
            raise RuntimeError("Publication notification recipient refused")
    print("Private publication outcome notification sent")


if __name__ == "__main__":
    main()
