"""Create a GitHub approval issue and send a Gmail SMTP review email.

An email link NEVER performs a side effect. The repository owner must post the exact
/publish comment on the approval issue to trigger the separate publishing workflow.
"""
from __future__ import annotations

import argparse
from email.message import EmailMessage
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


def send_review_email(issue_url: str, metadata: dict, preview_path: Path | None = None) -> bool:
    sender = os.getenv('GMAIL_ADDRESS', '').strip()
    password = os.getenv('GMAIL_APP_PASSWORD', '').replace(' ', '')
    recipient = os.getenv('REVIEW_EMAIL', '').strip()
    if not all([sender, password, recipient]):
        print('Review email not sent: configure GMAIL_ADDRESS, GMAIL_APP_PASSWORD, REVIEW_EMAIL secrets.')
        return False
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Subject'] = f"CarleCool | Reel zur Freigabe: {metadata['title']}"
    msg.set_content(f"""CarleCool – Neuer Reel-Vorschlag

Song: {metadata['title']}
Dauer: {metadata.get('duration', '30')} Sekunden
SoundCloud: {metadata.get('permalink', '')}
Videostil: {', '.join(metadata.get('search_keywords', []))}

REEL ANSCHAUEN: Kleinere Videovorschau im Anhang, sofern enthalten.
Original herunterladen: {issue_url} (dort ist der Link zum GitHub-Actions-Artefakt)

VERÖFFENTLICHEN:
{issue_url}
GitHub öffnen, anmelden und im Kommentar exakt /publish eingeben.
Dieser bewusste zweite Schritt verhindert unbeabsichtigte Posts durch Mail-Linkscanner.

VERWERFEN: Auf derselben Seite /reject kommentieren.

Es wird exakt die geprüfte Original-MP4 aus dem GitHub-Artefakt veröffentlicht,
solange es verfügbar ist (standardmäßig 7 Tage). Eine bloße Linköffnung postet nichts.

Caption-Vorschlag:
{metadata.get('caption','')}
""")
    if preview_path and preview_path.is_file() and preview_path.stat().st_size <= 10_000_000:
        msg.add_attachment(preview_path.read_bytes(), maintype='video', subtype='mp4', filename='CarleCool-Vorschau.mp4')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=40) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    return True


def create_review(metadata: dict, *, run_id: int, token: str, repo: str, session=None) -> dict:
    if not metadata.get('sha256') or not metadata.get('track_id'):
        raise ValueError('Render metadata incomplete')
    if run_id <= 0:
        raise ValueError('Need a real GitHub Actions run ID')
    # The GitHub issue is the single persistent awaiting-review record.
    payload = {'run_id': run_id, 'sha256': metadata['sha256'], 'track_id': metadata['track_id'],
               'video_ids': metadata['video_ids'], 'footage_sources': metadata['footage_sources'],
               'caption': metadata['caption'], 'created_from': 'daily-review'}
    name = 'carlecool-review'
    try:
        github_request('POST', 'labels', json_body={'name': name, 'color': '1f6feb',
                        'description': 'CarleCool Reel awaiting human approval'},
                       token=token, repo=repo, session=session)
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 422:
            raise
    artifacts_url = f'https://github.com/{repo}/actions/runs/{run_id}'
    body = (f"## CarleCool – Reel zum Freigeben\n\n"
            f"**Track:** {metadata['title']}\n\n"
            f"**Vorschau/Original:** [Workflow-Artefakt öffnen]({artifacts_url})\n\n"
            f"**Caption:**\n\n{metadata['caption']}\n\n"
            "**Freigabe:** Schreibe als Repository-Eigentümer den exakten Kommentar `/publish`. "
            "Die Datei wird aus dem Artefakt dieses Workflow-Laufs geholt und per SHA-256 geprüft. "
            "Eine Linköffnung allein veröffentlicht nichts.\n\n"
            "**Verwerfen:** `/reject` kommentieren.\n\n"
            "**Achtung:** Das Artefakt läuft nach 7 Tagen ab. "
            "Nicht dieselbe Ausgabe blind erneut veröffentlichen.\n\n" + encode_issue_data(payload))
    return github_request('POST', 'issues', json_body={'title': f"🎬 Freigabe: {metadata['title']}",
                         'body': body, 'labels': [name]},
                          token=token, repo=repo, session=session)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metadata', default='output/reel_metadata.json')
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text(encoding='utf-8'))
    issue = create_review(metadata, run_id=int(os.environ['GITHUB_RUN_ID']),
                          token=os.environ['GH_TOKEN'], repo=os.environ['GITHUB_REPOSITORY'])
    print('Review issue created:', issue['html_url'])
    video = Path(metadata['output'])
    preview = None
    if video.is_file():
        try:
            preview = make_preview(video, Path('output/mail_preview.mp4'))
        except (subprocess.CalledProcessError, OSError) as e:
            print(f'Could not make optional small mail attachment: {e}')
    send_review_email(issue['html_url'], metadata, preview)


if __name__ == '__main__':
    main()
