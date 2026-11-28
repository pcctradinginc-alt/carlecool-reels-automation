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
                    '-vf', 'scale=720:1280:force_original_aspect_ratio=decrease:flags=lanczos,'
                           'pad=720:1280:(ow-iw)/2:(oh-ih)/2',
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '23', '-maxrate', '3500k',
                    '-bufsize', '7000k', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart',
                    str(destination)], check=True, stdout=subprocess.DEVNULL)
    return destination if destination.stat().st_size <= MAX_ATTACHMENT_BYTES else None


def make_full_hd_copy(video: Path, destination: Path) -> Path | None:
    """1080×1920 copy that fits a Gmail attachment (bitrate from the length) — the same
    quality the Reels were published in before the cached master existed."""
    p = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(video)], capture_output=True, text=True)
    import re as _re
    m = _re.search(r'Duration: (\d+):(\d+):([\d.]+)', p.stderr)
    seconds = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 30.0
    kbps = max(1500, int(MAX_ATTACHMENT_BYTES * 8 / max(1.0, seconds) / 1000 * 0.9) - 192)
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(video),
                    '-c:v', 'libx264', '-preset', 'slow', '-b:v', f'{kbps}k', '-maxrate', f'{int(kbps * 1.15)}k',
                    '-bufsize', f'{kbps * 2}k', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
                    '-movflags', '+faststart', str(destination)], check=True, stdout=subprocess.DEVNULL)
    return destination if destination.stat().st_size <= MAX_ATTACHMENT_BYTES else None


def prepare_delivery(metadata: dict, run_id: int, metadata_path: Path | None = None) -> dict:
    """Upload the full-quality master privately when MASTER_S3_BUCKET is configured.

    Returns the (possibly updated) metadata. Without storage the legacy Gmail-attached
    original is used unchanged.
    """
    from . import masterstore
    if not masterstore.configured():
        return metadata
    location = masterstore.upload_master(Path(metadata['output']), run_id=run_id,
                                         sha256=metadata['sha256'])
    metadata = dict(metadata, master_storage=location)
    if metadata_path is not None:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Full-quality master stored privately:', location['bytes'], 'bytes')
    return metadata


def _safe_public_link(url: str, *, host: str) -> str:
    """Reject injection, redirect tricks, and non-HTTPS links in private email."""
    from urllib.parse import urlsplit
    if not url:
        return ""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != host or
            parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or len(url) > 1000):
        return ""
    return url


def _style_line(metadata: dict) -> str:
    """'Lana / Americana · cover: a rider … · Skater ✓ · Frau ✓' for the review mail."""
    style = metadata.get("style") or {}
    parts = [str(style.get("label") or "v4 default")]
    if style.get("basis"):
        parts.append(str(style["basis"]))
    signature = metadata.get("signature") or {}
    for role, name in (("skater", "Skater"), ("friends", "Freunde"), ("flag", "Flagge"), ("gear", "Analog-Gear"),
                       ("woman", "Frau"), ("car", "Porsche/Klassiker"), ("americana", "Americana"),
                       ("motif", "Cover-Motiv")):
        parts.append(f"{name} {'✓' if role in signature else '–'}")
    facts = metadata.get("reel_facts") or {}
    if facts.get("length_bucket"):
        parts.append(f"Länge {facts.get('length_s')}s ({facts['length_bucket']})")
    if metadata.get("performance_summary"):
        parts.append(str(metadata["performance_summary"]))
    return " · ".join(parts) + "  (ändern: /revise stil lana|rubin|night|auto)"


def footage_summary(metadata):
    from collections import Counter
    counts = Counter(x.get("provider", "unknown") for x in metadata.get("footage_sources", []))
    return ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nicht dokumentiert"


def quality_summary(metadata):
    q = metadata.get("final_quality")
    if not q:
        return "Keine Endproduktprüfung dokumentiert"
    return ("Technik: " + ("bestanden" if not q["errors"] else "Fehler")
            + "; Szenenquellen: " + str(q["distinct_sources"]) + "/" + str(q["shots"])
            + "; Hinweise: " + (", ".join(q["warnings"]) or "keine"))


def review_plain_text(issue_url: str, metadata: dict, *, direct_links: dict | None = None) -> str:
    """Copy-friendly alternatives to HTML mail, never publish on link open."""
    title = str(metadata.get("song_label") or metadata.get("title", "Neuer Track"))
    profile = metadata.get("creative_profile") or {}
    duration = round(float(metadata.get("duration", 15) or 15))
    ai = any(x.get("provider") == "ai" for x in metadata.get("footage_sources", []))
    footage_label = footage_summary(metadata)
    if issue_url:
        actions = (
            f"DEIN FREIGABELINK:\n{issue_url}\n\n"
            "Nach dem Öffnen bei GitHub EXAKT EINEN Kommentar eingeben:\n"
            "  /publish instagram     - nur Instagram\n"
            "  /publish tiktok        - nur TikTok (API noch nicht aktiv)\n"
            "  /publish both          - TikTok und Instagram (API noch nicht aktiv)\n\n"
            "Ein Linkklick allein veröffentlicht nichts. TikTok bleibt gesperrt, bis die\n"
            "Zernio-Konten verbunden und die Publishing-Gates freigegeben sind.\n"
            "Mit /publish tiktok oder /publish both bestätigst du ausdrücklich,\n"
            "dass du das MP4 geprüft hast und es öffentlich auf TikTok erscheinen darf.\n"
        )
    else:
        actions = (
            "TESTVORSCHAU – keine Freigabe und keine Veröffentlichung.\n"
            "Bei der echten Freigabe stehen Instagram, TikTok und beide Plattformen zur Wahl.\n"
        )
    if issue_url and direct_links:
        actions = (
            "DEINE VIER SICHEREN FREIGABELINKS (48 Stunden gültig):\n"
            f"Nur TikTok: {direct_links['tiktok']}\n"
            f"Nur Instagram: {direct_links['instagram']}\n"
            f"TikTok & Instagram: {direct_links['both']}\n"
            f"Schlechter als das letzte Video – nicht veröffentlichen: {direct_links['discard']}\n\n"
            "Jeder Link öffnet eine Bestätigungsseite. Erst ein zweiter Klick "
            "mit ausdrücklicher Zustimmung löst die Entscheidung aus.\n"
            "\"Schlechter als das letzte Video\" verwirft den Entwurf und meldet dein Urteil "
            "ans System zurück (es lernt daraus); die E-Mail bleibt im Postfach.\n"
        )
    elif issue_url:
        actions += "  /reject                       - Schlechter als das letzte Video / nicht veröffentlichen\n"
    return (
        "CARLECOOL  /  CREATIVE REVIEW\n\n"
        f"{title}\n{duration} Sekunden · 9:16 Reel · MP4 im Anhang\n\n"
        "Ein neuer visueller Entwurf ist bereit. Bitte erst das Video ansehen, "
        "dann den nächsten Schritt auswählen.\n\n"
        + actions + "\n"
        f"FOOTAGE: {footage_label}\n"
        f"QUALITÄT: {quality_summary(metadata)}\n"
        f"STIL: {_style_line(metadata)}\n"
        f"LOOK: {profile.get('preset', 'Rubin / Analog / Americana / Skate')}\n"
        f"SCHNITT: {profile.get('pace', 'medium')}   "
        f"ANALOG: {profile.get('analog', 65)}%\n\n"
        "Das MP4 ist nur dieser privaten Mail beigefügt. "
        "Ein Link allein löst niemals eine Veröffentlichung aus.\n\n"
        + _trend_line(metadata) +
        f"Musik: {metadata.get('permalink', '')}\n"
        + (f"Spotify (für die Bio): {_spotify()}\n" if _spotify() else "") + "\n"
        f"Caption:\n{metadata.get('caption', '')}\n"
    )


def _trend_line(metadata: dict) -> str:
    """Trend scout in the review mail (owner, 28 Nov: shadow mode — suggestions only)."""
    facts = metadata.get("reel_facts") or {}
    mode = facts.get("trend_mode")
    if not mode or mode == "off":
        return ""
    idea = facts.get("trend_idea")
    applied = facts.get("trend_id")
    head = "TREND-SCOUT (nur Vorschlag)" if mode == "shadow" else "TREND"
    if applied:
        return f"{head}: angewendet – {applied} (Gruppe {facts.get('trend_bucket')})\n"
    if idea:
        return f"{head}: Idee – {idea} (Gruppe {facts.get('trend_bucket')}; nicht angewendet)\n"
    return f"{head}: kein passender Trend – das ist ein gültiges Ergebnis\n"


def _spotify() -> str:
    from .captions import links
    return str(links().get("spotify_artist") or "")


def review_html(issue_url: str, metadata: dict, *, direct_links: dict | None = None) -> str:
    """Responsive Gmail-safe, Apple-clean email; all text escaped, no tracking."""
    h = lambda v: html_escape(str(v), quote=True)
    trend_html = (f'<br><b>TREND</b> {h(_trend_line(metadata).strip())}' if _trend_line(metadata) else '')
    title = h(metadata.get("song_label") or metadata.get("title", "Neuer Track"))
    profile = metadata.get("creative_profile") or {}
    pace = {"slow": "Ruhig", "medium": "Musikalisch", "fast": "Dynamisch"}.get(
        profile.get("pace", "medium"), "Musikalisch")
    preset = str(profile.get("preset", "rubin_analog_lana_skate")).replace("_", " ").title()
    duration = h(round(float(metadata.get("duration", 15) or 15)))
    analog = h(profile.get("analog", 65))
    ai = any(x.get("provider") == "ai" for x in metadata.get("footage_sources", []))
    footage_label = footage_summary(metadata)
    source = _safe_public_link(str(metadata.get("permalink") or ""), host="soundcloud.com")
    song = (
        f'<a href="{h(source)}" style="color:#606d81;text-decoration:underline">Song auf SoundCloud</a>'
        if source else ""
    )
    url = _safe_public_link(issue_url, host="github.com")
    if issue_url and not url:
        raise ValueError("Review URL must be an exact HTTPS github.com link")
    if url:
        # With a configured Worker each card opens a safe confirmation page.
        # Otherwise preserve the owner-authenticated GitHub issue fallback.
        publication_options = (
            ("Nur TikTok", "tiktok", "/publish tiktok"),
            ("Nur Instagram", "instagram", "/publish instagram"),
            ("TikTok & Instagram", "both", "/publish both"),
            ("Schlechter als das letzte Video – nicht veröffentlichen", "discard", "/reject"),
        )
        choice_rows = ''.join(
            '<tr><td style="padding:7px 0">'
            f'<a href="{h(direct_links[choice] if direct_links else url)}" style="display:inline-block;background:#f6f3ef;'
            'border:1px solid #e4ded7;border-radius:9px;color:#202b36;'
            f'font-size:14px;font-weight:700;padding:12px 14px;text-decoration:none">{h(name)}</a>'
            f'<span style="padding-left:12px;font-size:12px;color:#5d6774">'
            f'{("Bestätigungsseite öffnen" if direct_links else "Kommentar: " + command)}</span>'
            '</td></tr>' for name, choice, command in publication_options
        )
        action_area = (
            f'<a href="{h(url)}" style="display:inline-block;background:#1f2937;'
            'color:#fff;font-size:15px;font-weight:700;padding:15px 24px;'
            'border-radius:10px;text-decoration:none">Freigabe auf GitHub öffnen</a>'
            '<p style="font-size:12px;color:#79818e;margin-top:13px">'
            'Öffnet ausschließlich die GitHub-Freigabe. Kein automatisches Posting.</p>'
            '<p style="font-size:12px;font-weight:700;color:#202b36;margin-top:24px">'
            'VERÖFFENTLICHUNG AUSWÄHLEN</p>'
            '<p style="font-size:12px;color:#657080;line-height:1.5">'
            + ('Gewünschte Plattform anklicken und auf der sicheren Seite ein zweites Mal bestätigen. '
               'Ein Linkklick allein löst nichts aus.</p>' if direct_links else
               'Gewünschte Plattform anklicken, auf GitHub den zugehörigen Kommentar '
               'eingeben und bestätigen. Nur der Kommentar ist die Freigabe.</p>') +
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
            + choice_rows + '</table>'
            '<p style="font-size:12px;color:#8a6860;line-height:1.5">'
            'TikTok ist bis zur Verbindung über Zernio und Aktivierung der Sperren blockiert. '
            'Bei „beide“ wird vorab geprüft; bis dahin erfolgt auch kein Instagram-Post. '
            'Der Kommentar für TikTok bestätigt die Prüfung des MP4 und deine ausdrückliche '
            'Einwilligung zur öffentlichen TikTok-Veröffentlichung.</p>'
            # owner, 26 Nov: the "Überarbeiten / Gefällt mir / Verwerfen" block is gone —
            # the platform choice above is the only decision in the mail
        )
    else:
        action_area = (
            '<p style="font-size:14px;color:#5c6775">'
            'Nur eine technische Testvorschau – kein Freigabelink und keine Veröffentlichung.</p>'
        )
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:24px 12px;background:#f4f2ee;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:#202b36">'
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%"'
        ' style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e9e5df;'
        'border-radius:16px"><tr><td style="padding:34px 34px 28px">'
        '<p style="margin:0 0 36px;font-size:11px;letter-spacing:3px;'
        'font-weight:800;color:#333c48">CARLECOOL<span style="color:#bb8e72"> / STUDIO</span></p>'
        '<p style="font-size:11px;letter-spacing:2px;color:#aa826c;'
        'font-weight:700;margin:0 0 12px">NEUER VIDEOENTWURF</p>'
        f'<h1 style="font-size:34px;letter-spacing:-1.3px;line-height:1.1;margin:0 0 18px">'
        f'{title}</h1>'
        '<p style="color:#616c79;font-size:15px;line-height:1.7;margin:0 0 20px">'
        f'Dein neuer {duration}-Sekunden-Film ist da. Ruhe, Analog-Texturen, '
        'California Nostalgia und ein bisschen Skate. Schau dir erst den '
        'MP4-Anhang an – anschließend entscheidest du über den nächsten Schnitt.</p>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' style="background:#f8f6f2;border:1px solid #efebe5;border-radius:10px">'
        '<tr><td style="padding:16px 18px;font-size:12px;color:#687281">'
        f'<b style="color:#202b36">REEL</b> &nbsp;{duration} s · 9:16 · MP4<br>'
        f'<b style="color:#202b36">STIL</b> &nbsp;{h(_style_line(metadata))}<br>'
        f'<b style="color:#202b36">LOOK</b> &nbsp;{h(preset)}<br>'
        f'<b style="color:#202b36">BILDER</b> &nbsp;{h(footage_label)}<br>'
        f'<b style="color:#202b36">SCHNITT</b> &nbsp;{h(pace)}'
        f' &nbsp;&nbsp;<b style="color:#202b36">ANALOG</b> &nbsp;{analog}%'
        f'<br><b>QUALITÄT</b> {h(quality_summary(metadata))}'
        f'{trend_html}'
        '</td></tr></table>'
        '<p style="font-size:13px;color:#79818e;margin:22px 0 20px">'
        '▶ Dein Video liegt als <b>CarleCool-Original.mp4</b> im Anhang.</p>'
        + action_area +
        f'<p style="margin:28px 0 0;font-size:12px;color:#87909a">{song}</p>'
        '<p style="border-top:1px solid #eeeae4;margin:26px 0 0;padding-top:20px;'
        'font-size:11px;line-height:1.6;color:#9499a2">'
        'Private Vorschau · Keine automatische Instagram-Veröffentlichung · '
        'Verlinkungen enthalten keine eingebetteten Trackingbilder.</p>'
        '</td></tr></table></body></html>'
    )


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
    if not metadata.get('master_storage') and original_path.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise RuntimeError('Gmail attachment is too large; cannot safely deliver original Reel')
    if hashlib.sha256(original_path.read_bytes()).hexdigest() != metadata.get('sha256'):
        raise RuntimeError('Original video differs from approved review metadata')
    if metadata.get('master_storage'):
        if (metadata['master_storage'] or {}).get('provider') == 'actions-cache':
            preview = make_full_hd_copy(original_path, original_path.with_name('email_copy.mp4'))
        else:
            preview = make_preview(original_path, original_path.with_name('email_preview.mp4'))
        if preview is None:
            raise RuntimeError('Email preview too large for Gmail')
        video_bytes, video_name = preview.read_bytes(), 'CarleCool-Preview.mp4'
        metadata = dict(metadata, preview_sha256=hashlib.sha256(video_bytes).hexdigest())
    else:
        video_bytes, video_name = original_path.read_bytes(), 'CarleCool-Original.mp4'
    if len(video_bytes) > MAX_ATTACHMENT_BYTES:
        raise RuntimeError('Gmail attachment is too large; cannot safely deliver original Reel')
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Message-ID'] = message_id
    msg['X-CarleCool-Run-ID'] = str(run_id)
    msg['X-CarleCool-SHA256'] = metadata['sha256']
    msg['Subject'] = f"CarleCool | Reel zur Freigabe: {metadata.get('song_label') or metadata['title']}"
    direct_links = {}
    if issue_url:
        from .approval_links import approval_links
        direct_links = approval_links(issue_url, metadata, run_id)
    msg.set_content(review_plain_text(issue_url, metadata, direct_links=direct_links))
    msg.add_alternative(review_html(issue_url, metadata, direct_links=direct_links), subtype="html")
    msg.add_attachment(video_bytes, maintype='video', subtype='mp4', filename=video_name)
    meta_bytes = json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode('utf-8')
    msg.add_attachment(meta_bytes, maintype='application', subtype='json', filename='reel_metadata.json')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=40) as smtp:
        smtp.login(sender, password)
        refused = smtp.send_message(msg)
        if refused:
            raise RuntimeError('SMTP refused review recipient')
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
               'master_storage': metadata.get('master_storage'),
               'song_label': metadata.get('song_label'),
               'cover_frame_ms': metadata.get('cover_frame_ms'),
               'reel_facts': metadata.get('reel_facts'),
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
            f"**Track:** {metadata.get('song_label') or metadata['title']}\n\n"
            "**Privates Original:** Gmail-Anhang, nicht bei GitHub gespeichert.\n\n"
            f"**Caption:**\n\n{metadata['caption']}\n\n"
            f"**Creative Profile:** `{metadata.get('creative_profile', {}).get('preset', 'default')}` "
            f"· Tempo `{metadata.get('creative_profile', {}).get('pace', 'medium')}` "
            f"· Analog `{metadata.get('creative_profile', {}).get('analog', 65)}%`\n\n"
            "**Plattform wählen (als Repository-Eigentümer kommentieren):**\\n"
            "- `/publish instagram` – nur Instagram\\n"
            "- `/publish tiktok` – nur TikTok (derzeit API-Sperre)\\n"
            "- `/publish both` – beide Plattformen (derzeit API-Sperre; kein teilweiser Upload)\\n\\n"
            "`/approve` und `/publish` sind alte Kurzformen nur für Instagram. "
            "Die Instagram-Veröffentlichung bleibt zusätzlich gesperrt, "
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
    return github_request('POST', 'issues', json_body={'title': f"🎬 Freigabe: {metadata.get('song_label') or metadata['title']}",
                         'body': body, 'labels': [name]},
                          token=token, repo=repo, session=session)


def _remember_sent_preview(metadata: dict, run_id: int, kind: str) -> None:
    """Persist only after successful private Gmail delivery, not on a failed render."""
    if os.getenv("GITHUB_ACTIONS") != "true":
        return
    from .history import record_preview_delivery
    changed = record_preview_delivery(
        metadata, run_id=run_id, kind=kind,
        token=os.getenv("GH_TOKEN", ""), repo=os.getenv("GITHUB_REPOSITORY", ""),
    )
    print("Preview rotation history:", "recorded" if changed else "already recorded")
    _remember_licences(metadata, run_id)


def _remember_licences(metadata: dict, run_id: int) -> None:
    """Licence proof per clip, kept for good in data/licence-log.json (also in the issue)."""
    if os.getenv("GITHUB_ACTIONS") != "true":
        return
    from .licences import record_licence_log
    try:
        changed = record_licence_log(metadata, run_id=run_id, token=os.getenv("GH_TOKEN", ""),
                                     repo=os.getenv("GITHUB_REPOSITORY", ""))
        print("Licence log:", "recorded" if changed else "already recorded")
    except Exception as exc:  # the mail is out; the issue still holds the same proof
        print("Warning: licence log not stored (proof remains in the approval issue):", type(exc).__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metadata', default='output/reel_metadata.json')
    parser.add_argument('--dry-run-email', action='store_true', help='Send private test preview, no approval issue')
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text(encoding='utf-8'))
    original = Path(metadata['output'])
    if os.getenv('CARLECOOL_OFFLINE_SMOKE') == '1' or metadata.get('resolution') != '1080x1920':
        raise RuntimeError('Offline or non-production render cannot be delivered')
    run_id = int(os.environ['GITHUB_RUN_ID'])
    metadata = prepare_delivery(metadata, run_id, Path(args.metadata))
    message_id = make_msgid(domain='carlecool.invalid')
    if args.dry_run_email:
        if not send_review_email('', metadata, original, message_id=message_id, run_id=run_id):
            raise RuntimeError('Gmail configuration is missing; no preview was sent')
        _remember_sent_preview(metadata, run_id, 'test')
        print('Private dry-run email sent; no approval issue, no Instagram call')
        return
    from . import production_journal as journal
    journal_date = os.getenv("CARLECOOL_PRODUCTION_DATE")
    if journal_date and journal.check(journal_date):
        print("Daily delivery already confirmed; no duplicate email")
        return
    issue = create_review(metadata, run_id=run_id,
                          token=os.environ['GH_TOKEN'], repo=os.environ['GITHUB_REPOSITORY'],
                          mail_message_id=message_id)
    if journal_date and not journal.begin(journal_date, run_id, message_id, metadata["sha256"]):
        return
    try:
        if not send_review_email(issue['html_url'], metadata, original,
                                 message_id=message_id, run_id=run_id):
            raise RuntimeError('Gmail configuration is missing; no preview was sent')
    except Exception:
        # Ambiguous SMTP result: keep the approval record for Sent reconciliation.
        if journal_date:
            raise
        # Fail closed; don't leave an unservable approval issue if delivery fails.
        try:
            github_request('PATCH', f"issues/{issue['number']}",
                           json_body={'state': 'closed'}, token=os.environ['GH_TOKEN'],
                           repo=os.environ['GITHUB_REPOSITORY'])
        except Exception as cleanup_error:
            print('Warning: review issue cleanup failed:', type(cleanup_error).__name__)
        raise
    if journal_date:
        journal.complete(journal_date, run_id)
    _remember_sent_preview(metadata, run_id, 'daily')
    print('Private review email delivered; approval issue:', issue['html_url'])


if __name__ == '__main__':
    main()
