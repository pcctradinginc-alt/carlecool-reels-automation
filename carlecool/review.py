"""Create a GitHub approval issue and send a Gmail SMTP review email.

An email link NEVER performs a side effect. The repository owner must post the exact
/publish comment on the approval issue to trigger the separate publishing workflow.
"""
from __future__ import annotations

import argparse
from html import escape as html_escape
from email.message import EmailMessage
from email.utils import make_msgid
from .mailstore import MAX_ATTACHMENT_BYTES
import json
import os
from pathlib import Path
import smtplib
import subprocess

import requests

MARKER_START = '<!-- CARLECOOL_APPROVAL_JSON\n'
MARKER_END = '\nEND_CARLECOOL_APPROVAL_JSON -->'


def encode_issue_data(data: dict) -> str:
    return MARKER_START + json.dumps(data, ensure_ascii=False, sort_keys=True) + MARKER_END


def decode_issue_data(body: str) -> dict:
    if not body or body.count(MARKER_START) != 1 or body.count(MARKER_END) != 1:
        raise ValueError('Issue has no unique CarleCool approval payload')
    raw = body.split(MARKER_START, 1)[1].split(MARKER_END, 1)[0]
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('run_id'), int) or not str(data.get('sha256', '')):
        raise ValueError('Missing fixed approval identity')
    return data


def github_request(method: str, path: str, *, json_body=None, token=None, repo=None, session=None):
    repo = repo or os.environ['GITHUB_REPOSITORY']
    token = token or os.environ['GH_TOKEN']
    if not repo.count('/') == 1:
        raise ValueError('Invalid GitHub repository')
    session = session or requests
    response = session.request(method, f'https://api.github.com/repos/{repo}/{path.lstrip("/")}',
                               headers={'Authorization': f'Bearer {token}',
                                        'Accept': 'application/vnd.github+json',
                                        'X-GitHub-Api-Version': '2022-11-28'},
                               json=json_body, timeout=30)
    response.raise_for_status()
    return response.json() if response.content else {}


def make_preview(video: Path, destination: Path) -> Path | None:
    """Mail-friendly reduced-resolution preview, not the publishing original."""
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(video),
                    '-vf', 'scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '650k', '-maxrate', '750k',
                    '-bufsize', '1000k', '-c:a', 'aac', '-b:a', '80k', '-movflags', '+faststart',
                    str(destination)], check=True, stdout=subprocess.DEVNULL)
    return destination if destination.stat().st_size <= 10_000_000 else None


def send_review_email(issue_url: str, metadata: dict, original_path: Path | None = None,
                      *, message_id: str | None = None, run_id: int | None = None) -> bool:
    """Send exact hashed original + metadata privately; never upload a GitHub artifact."""
    sender = os.getenv('GMAIL_ADDRESS', '').strip()
    password = os.getenv('GMAIL_APP_PASSWORD', '').replace(' ', '')
    recipient = os.getenv('REVIEW_EMAIL', '').strip()
    if not all([sender, password, recipient]):
        print('Review email not sent: configure GMAIL_ADDRESS, GMAIL_APP_PASSWORD, REVIEW_EMAIL secrets.')
        return False
    if not original_path or not original_path.is_file() or not message_id or run_id is None:
        raise RuntimeError('Private review email requires original MP4, Message-ID and run ID')
    import hashlib
    video_bytes = original_path.read_bytes()
    if len(video_bytes) > MAX_ATTACHMENT_BYTES:
        raise RuntimeError('Gmail attachment is too large; cannot safely deliver original Reel')
    if hashlib.sha256(video_bytes).hexdigest() != metadata.get('sha256'):
        raise RuntimeError('Original video differs from approved review metadata')
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Message-ID'] = message_id
    msg['X-CarleCool-Run-ID'] = str(run_id)
    msg['X-CarleCool-SHA256'] = metadata['sha256']
    msg['Subject'] = f"CarleCool | Reel zur Freigabe: {metadata['title']}"
    instructions = (f"Direkt zur Freigabe und Überarbeitung: {issue_url}\n"
                    "Als Eigentümer auf GitHub kommentieren: /approve oder /publish zur Freigabe, "
                    "/reject zum Verwerfen, /revise mehr natur, weniger skate für neue Version. "
                    "Ein Klick auf den Link allein veröffentlicht nichts."
                    if issue_url else "Testvorschau ohne Freigabe-Issue: kein Instagram-Post.")
    msg.set_content(f"""CarleCool – Neuer Reel-Vorschlag

Song: {metadata['title']}
Dauer: {metadata.get('duration', '30')} Sekunden
SoundCloud: {metadata.get('permalink', '')}
Suchbegriffe: {', '.join(metadata.get('search_keywords', []))}
Bildsprache: {metadata.get('visual_direction', {}).get('name', 'Analog-Digital Nostalgia × Corecore × Zen Minimalism')}
Schnitt: {metadata.get('visual_direction', {}).get('edit_plan', 'Stillness ↔ Action')}
Stilprofil: {metadata.get('creative_profile', {}).get('preset', 'rubin_analog_lana_skate')}
Schnittgeschwindigkeit: {metadata.get('creative_profile', {}).get('pace', 'medium')}
Analog-Look: {metadata.get('creative_profile', {}).get('analog', 65)}%
Gewichtung: {metadata.get('creative_profile', {}).get('weights', {})}

Das ORIGINAL-REEL liegt ausschließlich dieser privaten E-Mail bei.
{instructions}

Kein Mail-Link allein veröffentlicht ein Video. Nur der GitHub-Eigentümer kann die
Freigabe auslösen; dann wird exakt dieser E-Mail-Anhang per SHA-256 geprüft.

Caption-Vorschlag:
{metadata.get('caption', '')}
""")
    # The issue URL is a clickable email link. It NEVER posts without an
    # authenticated owner comment and the separate publish-enabled gate.
    if issue_url:
        safe_link = html_escape(issue_url, quote=True)
        safe_title = html_escape(str(metadata['title']))
        msg.add_alternative(
            f'<html><body style="font-family:Arial,sans-serif;max-width:640px">'
            f'<h2>CarleCool – {safe_title}</h2>'
            f'<p>Das Originalvideo liegt als privater MP4-Anhang bei.</p>'
            f'<p><a href="{safe_link}" style="background:#181818;color:white;padding:14px 22px;'
            f'border-radius:8px;text-decoration:none">Freigabe &amp; Überarbeitung öffnen</a></p>'
            f'<p>Der Link öffnet nur das GitHub-Issue. Ein Kommentar <b>/approve</b> '
            f'(oder <b>/publish</b>) ist zur Freigabe nötig; die Instagram-Sperre gilt weiter.</p>'
            f'<p>Eine neue Version anfordern: <code>/revise mehr natur, weniger skate</code></p>'
            f'<p>Verwerfen: <code>/reject</code></p>'
            f'</body></html>', subtype='html')
    msg.add_attachment(video_bytes, maintype='video', subtype='mp4', filename='CarleCool-Original.mp4')
    meta_bytes = json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode('utf-8')
    msg.add_attachment(meta_bytes, maintype='application', subtype='json', filename='reel_metadata.json')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=40) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    return True


def create_review(metadata: dict, *, run_id: int, token: str, repo: str,
                  mail_message_id: str | None = None, session=None) -> dict:
    if not metadata.get('sha256') or not metadata.get('track_id'):
        raise ValueError('Render metadata incomplete')
    if run_id <= 0:
        raise ValueError('Need a real GitHub Actions run ID')
    # The GitHub issue is the single persistent awaiting-review record.
    payload = {'run_id': run_id, 'sha256': metadata['sha256'], 'track_id': metadata['track_id'],
               'video_ids': metadata['video_ids'], 'footage_sources': metadata['footage_sources'],
               'caption': metadata['caption'], 'created_from': 'daily-review',
               'mail_message_id': mail_message_id or make_msgid(domain='carlecool.invalid'),
               'creative_profile': metadata.get('creative_profile'),
               'revision_number': metadata.get('creative_profile', {}).get('revision', 0)}
    name = 'carlecool-review'
    try:
        github_request('POST', 'labels', json_body={'name': name, 'color': '1f6feb',
                        'description': 'CarleCool Reel awaiting human approval'},
                       token=token, repo=repo, session=session)
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 422:
            raise
    body = (f"## CarleCool – Reel zum Freigeben\n\n"
            f"**Track:** {metadata['title']}\n\n"
            "**Privates Original:** Gmail-Anhang, nicht bei GitHub gespeichert.\n\n"
            f"**Caption:**\n\n{metadata['caption']}\n\n"
            f"**Creative Profile:** `{metadata.get('creative_profile', {}).get('preset', 'default')}` "
            f"· Tempo `{metadata.get('creative_profile', {}).get('pace', 'medium')}` "
            f"· Analog `{metadata.get('creative_profile', {}).get('analog', 65)}%`\n\n"
            "**Freigabe:** Schreibe als Repository-Eigentümer den exakten Kommentar `/approve` "
            "(alternativ `/publish`). Die Instagram-Veröffentlichung bleibt zusätzlich gesperrt, "
            "solange `PUBLISH_ENABLED` nicht bewusst aktiviert wurde. "
            "Das exakte Original wird aus Gmail Sent abgerufen und per SHA-256 geprüft. "
            "Eine Linköffnung allein veröffentlicht nichts.\n\n"
            "**Überarbeiten:** `/revise mehr natur, weniger skate` oder z.B. "
            "`/revise preset_rubin_lana`, `/revise more_mpc`, "
            "`/revise slower_cuts`, `/revise more_americana`. "
            "Der neue Entwurf erhält einen eigenen Prüfwert und eine neue Freigabe.\n\n"
            "**Verwerfen:** `/reject` kommentieren.\n\n"
            "**Achtung:** Die Originaldatei bleibt nur in deinem privaten Gmail-Postfach. "
            "Lösche die gesendete E-Mail erst nach Freigabe/Verwerfen.\n\n" + encode_issue_data(payload))
    return github_request('POST', 'issues', json_body={'title': f"🎬 Freigabe: {metadata['title']}",
                         'body': body, 'labels': [name]},
                          token=token, repo=repo, session=session)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metadata', default='output/reel_metadata.json')
    parser.add_argument('--dry-run-email', action='store_true', help='Send private test preview, no approval issue')
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text(encoding='utf-8'))
    original = Path(metadata['output'])
    run_id = int(os.environ['GITHUB_RUN_ID'])
    message_id = make_msgid(domain='carlecool.invalid')
    if args.dry_run_email:
        if not send_review_email('', metadata, original, message_id=message_id, run_id=run_id):
            raise RuntimeError('Gmail configuration is missing; no preview was sent')
        print('Private dry-run email sent; no approval issue, no Instagram call')
        return
    issue = create_review(metadata, run_id=run_id,
                          token=os.environ['GH_TOKEN'], repo=os.environ['GITHUB_REPOSITORY'],
                          mail_message_id=message_id)
    try:
        if not send_review_email(issue['html_url'], metadata, original,
                                 message_id=message_id, run_id=run_id):
            raise RuntimeError('Gmail configuration is missing; no preview was sent')
    except Exception:
        # Fail closed; don't leave an unservable approval issue if delivery fails.
        try:
            github_request('PATCH', f"issues/{issue['number']}",
                           json_body={'state': 'closed'}, token=os.environ['GH_TOKEN'],
                           repo=os.environ['GITHUB_REPOSITORY'])
        except Exception as cleanup_error:
            print('Warning: review issue cleanup failed:', type(cleanup_error).__name__)
        raise
    print('Private review email delivered; approval issue:', issue['html_url'])


if __name__ == '__main__':
    main()
