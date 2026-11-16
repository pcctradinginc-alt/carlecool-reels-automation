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


def publish(issue_number: int, run_id: int, directory: Path):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Publishing is only available through audited GitHub Actions')
    settings = Settings()
    settings.validate()
    if not settings.publish_enabled:
        raise RuntimeError('PUBLISH_ENABLED secret is not true; approval alone cannot post')
    if not settings.ig_access_token:
        raise RuntimeError('IG_ACCESS_TOKEN is missing')
    issue = github_request('GET', f'issues/{issue_number}')
    metadata = json.loads((directory / 'output/reel_metadata.json').read_text(encoding='utf-8'))
    video = directory / metadata['output']
    approval = verify_artifact(issue, metadata, video, run_id=run_id)
    if any(x.get('provider') == 'coverr' for x in approval['footage_sources']) and not settings.coverr_permission_confirmed:
        raise RuntimeError('Coverr free-tier attribution is not cleared for this publish method')
    state = load_state()
    if state.get('pending'):
        raise RuntimeError('Unresolved pending publication must be reconciled manually')
    if any(x.get('sha256') == approval['sha256'] or str(x.get('track_id')) == str(approval['track_id'])
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
    container_id = client.create_and_upload(video, approval['caption'])
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
    args = parser.parse_args()
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
    publish(args.issue, args.run, Path(args.directory))


if __name__ == '__main__':
    main()
