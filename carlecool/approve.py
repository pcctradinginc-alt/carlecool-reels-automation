"""Human-approved publication of an *existing* hashed preview; no rerendering."""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path

from .config import Settings
from .instagram import Instagram
from .review import decode_issue_data, github_request
from .mailstore import fetch_reel_from_sent
from .state import load_state, save_state, commit_state


PUBLISH_CHOICES = {
    '/approve': 'instagram',       # legacy owner-only command
    '/publish': 'instagram',       # legacy owner-only command
    '/publish instagram': 'instagram',
    '/publish tiktok': 'tiktok',
    '/publish both': 'both',
}


def resolve_publish_target(command: str) -> str:
    """Only exact owner comments may select publication destinations."""
    try:
        return PUBLISH_CHOICES[command]
    except KeyError as exc:
        raise ValueError('Unknown or ambiguous publish command') from exc


def ensure_target_ready(target: str) -> None:
    """Fail before ANY upload if a requested platform is not configured.

    TikTok Content Posting API requires app approval, authorized user OAuth,
    creator-info-driven controls and an audit for public videos.
    The corresponding client is intentionally not yet implemented.
    """
    if target not in ('instagram', 'tiktok', 'both'):
        raise ValueError('Unknown publish destination')
    # Default to the old Instagram-only integration until the owner explicitly
    # connects two Zernio accounts and activates the new publisher.
    if os.getenv('ZERNIO_PUBLISH_ENABLED') == 'true':
        requested = ('instagram', 'tiktok') if target == 'both' else (target,)
        if not os.getenv('ZERNIO_API_KEY', '').strip():
            raise RuntimeError('ZERNIO_API_KEY missing; neither platform was posted')
        required = {'instagram': 'ZERNIO_INSTAGRAM_ACCOUNT_ID',
                    'tiktok': 'ZERNIO_TIKTOK_ACCOUNT_ID'}
        missing = [required[name] for name in requested if not os.getenv(required[name], '').strip()]
        if missing:
            raise RuntimeError('Missing connected Zernio accounts: ' + ', '.join(missing))
    elif target != 'instagram':
        raise RuntimeError(
            'Zernio is not connected and enabled. Neither TikTok nor Instagram '
            'has been posted. See docs/zernio-free-setup.md.'
        )


def verify_artifact(issue: dict, metadata: dict, video: Path, *, run_id: int) -> dict:
    if issue.get('state') != 'open':
        raise ValueError('Review issue is not open')
    if 'carlecool-review' not in [x.get('name') for x in issue.get('labels', [])]:
        raise ValueError('Issue is not labeled as a CarleCool review')
    approval = decode_issue_data(issue.get('body', ''))
    if approval['run_id'] != run_id:
        raise ValueError('Artifact workflow run ID does not match approval')
    hasher = hashlib.sha256()
    with video.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    digest = hasher.hexdigest()
    if digest != approval['sha256'] or digest != metadata['sha256']:
        raise ValueError('SHA-256 mismatch: original MP4 differs from approved file')
    if str(metadata.get('track_id')) != str(approval['track_id']):
        raise ValueError('Track identity changed')
    if metadata.get('video_ids') != approval['video_ids']:
        raise ValueError('Footage identity changed')
    if metadata.get('caption') != approval['caption']:
        raise ValueError('Caption changed after review')
    return approval


def validate_footage_rights(approval: dict) -> None:
    """Reject unknown sources and require free Coverr API credit in final caption.

    Licensed fallback stock is declared in assets/stock/manifest.json at render
    time; that declaration, and Coverr metadata, remain subject to human review.
    """
    sources = approval.get('footage_sources')
    if not isinstance(sources, list) or not sources:
        raise RuntimeError('Missing footage provenance; no publication')
    providers = {str(entry.get('provider', '')) for entry in sources
                 if isinstance(entry, dict)}
    if len(providers) == 0 or len(providers) > 3 or any(
            name not in ('coverr', 'owned', 'ai') for name in providers):
        raise RuntimeError('Unknown footage source; no publication')
    caption = str(approval.get('caption', ''))
    if 'coverr' in providers and ('Footage by Coverr' not in caption
                                 or 'https://coverr.co' not in caption):
        raise RuntimeError('Coverr free API credit missing from approved caption')


def publish_via_zernio(issue_number: int, approval: dict, metadata: dict,
                       video: Path, target: str, state: dict) -> None:
    """Publish with official partner after consent and an immutable Git reserve.

    Partial results and timeout are intentionally NOT retried automatically.
    The journal remains pending until manually reconciled to prevent duplicates.
    """
    from .zernio import Zernio, published_platforms
    if len(set(approval['video_ids'])) < 5:
        raise RuntimeError('Require 5 unique licensed clips for automatic posting')
    if state.get('pending'):
        raise RuntimeError('Unresolved publication; reconcile before sending another')
    if any(x.get('sha256') == approval['sha256'] for x in state.get('published', [])):
        raise RuntimeError('These exact approved video bytes were already published')
    client = Zernio(os.environ['ZERNIO_API_KEY'])
    ids = {'instagram': os.getenv('ZERNIO_INSTAGRAM_ACCOUNT_ID', ''),
           'tiktok': os.getenv('ZERNIO_TIKTOK_ACCOUNT_ID', '')}
    required = ('instagram', 'tiktok') if target == 'both' else (target,)
    client.verify_connections({name: ids[name] for name in required})
    if 'tiktok' in required:
        client.preflight_tiktok(ids['tiktok'])
    timestamp = datetime.now(timezone.utc).isoformat()
    state['pending'] = {
        'track_id': approval['track_id'],
        'sha256': approval['sha256'],
        'at': timestamp,
        'issue_number': issue_number,
        'target': target,
        'provider': 'zernio',
    }
    save_state(state)
    commit_state(f'journal: reserve approved zernio reel {issue_number} for {target}')
    # Any crash or 207 now leaves a pending record, stopping accidental retries.
    media_url = client.upload(video)
    response = client.publish(
        media_url=media_url, caption=approval['caption'], target=target,
        instagram_id=os.getenv('ZERNIO_INSTAGRAM_ACCOUNT_ID', ''),
        tiktok_id=os.getenv('ZERNIO_TIKTOK_ACCOUNT_ID', ''),
        ai_generated=any(item.get('provider') == 'ai' for item in approval['footage_sources']),
        sha256=approval['sha256'], issue_number=issue_number,
        audio_name=str(approval.get('song_label') or ''),
    )
    post = response.get('post') or {}
    state['pending']['provider_post_id'] = post.get('_id', '')
    per_platform = published_platforms(response, target)
    state['pending']['platform_status'] = {
        key: value.get('status', 'unknown') for key, value in per_platform.items()
    }
    save_state(state)
    commit_state(f'journal: record zernio result for issue {issue_number}')
    if any(item.get('status') != 'published' for item in per_platform.values()):
        raise RuntimeError('One or more platforms not confirmed published; '
                           'manual Zernio reconciliation needed before any retry')
    state['published'].append({
        'track_id': approval['track_id'], 'at': timestamp,
        'video_ids': approval['video_ids'], 'sha256': approval['sha256'],
        'approval_issue': issue_number, 'provider': 'zernio', 'target': target,
        'provider_post_id': post.get('_id', ''),
        'platform_status': state['pending']['platform_status'],
    })
    state['pending'] = None
    save_state(state)
    commit_state(f'journal: published zernio reel {issue_number} on {target}')
    github_request('POST', f'issues/{issue_number}/comments',
                   json_body={'body': f'✅ Veröffentlichung über Zernio bestätigt: {target}.'})
    github_request('PATCH', f'issues/{issue_number}', json_body={'state': 'closed'})


def publish(issue_number: int, run_id: int, directory: Path, *, target: str = 'instagram'):
    ensure_target_ready(target)
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Publishing is only available through audited GitHub Actions')
    settings = Settings()
    settings.validate()
    if not settings.publish_enabled:
        raise RuntimeError('PUBLISH_ENABLED secret is not true; approval alone cannot post')
    if os.getenv('ZERNIO_PUBLISH_ENABLED') != 'true' and not settings.ig_access_token:
        raise RuntimeError('IG_ACCESS_TOKEN is missing')
    issue = github_request('GET', f'issues/{issue_number}')
    metadata = json.loads((directory / 'output/reel_metadata.json').read_text(encoding='utf-8'))
    video = directory / metadata['output']
    approval = verify_artifact(issue, metadata, video, run_id=run_id)
    validate_footage_rights(approval)
    if any(x.get('provider') == 'coverr' for x in approval['footage_sources']) and not settings.coverr_permission_confirmed:
        raise RuntimeError('Coverr free-tier attribution is not cleared for this publish method')
    # AI video still requires explicit license review and cannot be silently
    # published even if the existing Instagram gate is enabled.
    if (any(x.get('provider') == 'ai' for x in approval['footage_sources'])
            and os.getenv('AI_VIDEO_PUBLISH_LICENSE_CONFIRMED') != 'true'):
        raise RuntimeError('AI-video distribution rights have not been confirmed')
    state = load_state()
    if os.getenv('ZERNIO_PUBLISH_ENABLED') == 'true':
        publish_via_zernio(issue_number, approval, metadata, video, target, state)
        return
    if state.get('pending'):
        raise RuntimeError('Unresolved pending publication must be reconciled manually')
    if any(x.get('sha256') == approval['sha256']
           for x in state.get('published', [])):
        raise RuntimeError('Track or reel was already published; no duplicate post')
    if len(set(approval['video_ids'])) < 5:
        raise RuntimeError('Require 5 unique licensed clips for automatic posting')
    # Verify assigned Instagram asset before recording a pending publication.
    client = Instagram(settings.ig_user_id, settings.ig_access_token, settings.graph_version)
    client.verify_access()
    timestamp = datetime.now(timezone.utc).isoformat()
    state['pending'] = {'track_id': approval['track_id'], 'at': timestamp,
                        'sha256': approval['sha256'], 'issue_number': issue_number}
    save_state(state)
    commit_state(f'journal: reserve human approved reel {issue_number}')
    container_id = client.create_and_upload(video, approval['caption'],
                                            audio_name=str(approval.get('song_label') or ''))
    state['pending']['container_id'] = container_id
    save_state(state)
    commit_state(f'journal: created container for review {issue_number}')
    media_id = client.finish(container_id)
    state['published'].append({'track_id': approval['track_id'], 'at': timestamp,
                               'video_ids': approval['video_ids'], 'sha256': approval['sha256'],
                               'instagram_media_id': media_id, 'instagram_container_id': container_id,
                               'approval_issue': issue_number})
    state['pending'] = None
    save_state(state)
    commit_state(f'journal: posted approved reel {issue_number} / {media_id}')
    github_request('POST', f'issues/{issue_number}/comments',
                   json_body={'body': f'✅ Instagram Reel veröffentlicht, Media-ID `{media_id}`.'})
    github_request('PATCH', f'issues/{issue_number}', json_body={'state': 'closed'})
    print('Published approved Reel:', media_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--issue', type=int, required=True)
    parser.add_argument('--run', type=int)
    parser.add_argument('--directory', default='approval_artifact')
    parser.add_argument('--inspect', action='store_true', help='Print immutable source run id')
    parser.add_argument('--fetch', action='store_true', help='Retrieve exact approved Gmail original')
    parser.add_argument('--command', default='/approve', help='Exact GitHub issue comment')
    parser.add_argument('--preflight', action='store_true', help='Verify selected target before any uploads')
    args = parser.parse_args()
    target = resolve_publish_target(args.command)
    if args.preflight:
        ensure_target_ready(target)
        print('Allowed publication destination:', target)
        return
    if args.inspect:
        issue = github_request('GET', f'issues/{args.issue}')
        if issue.get('state') != 'open' or 'carlecool-review' not in [x.get('name') for x in issue.get('labels', [])]:
            raise ValueError('No active, labeled review issue')
        data = decode_issue_data(issue.get('body', ''))
        print(data['run_id'])
        return
    if args.fetch:
        issue = github_request('GET', f'issues/{args.issue}')
        if issue.get('state') != 'open' or 'carlecool-review' not in [x.get('name') for x in issue.get('labels', [])]:
            raise ValueError('No active, labeled CarleCool approval issue')
        approval = decode_issue_data(issue.get('body', ''))
        if args.run != approval['run_id']:
            raise ValueError('Approved run ID differs from Gmail retrieval request')
        fetch_reel_from_sent(approval, Path(args.directory))
        print('Exact approved Gmail Reel restored locally; SHA-256 verified')
        return
    if not args.run:
        parser.error('--run is required unless --inspect')
    publish(args.issue, args.run, Path(args.directory), target=target)


if __name__ == '__main__':
    main()
