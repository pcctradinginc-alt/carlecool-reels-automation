"""Guard against accidentally exposing music in public GitHub artifacts."""
from pathlib import Path


def test_media_workflows_do_not_upload_artifacts_or_depend_on_private_repo():
    daily = Path('.github/workflows/daily-reel.yml').read_text()
    approval = Path('.github/workflows/approve-reel.yml').read_text()
    connection = Path('.github/workflows/instagram-connection.yml').read_text()
    assert 'upload-artifact' not in daily
    assert 'gh run download' not in approval
    assert 'download-artifact' not in approval
    assert 'github.event.repository.private' not in daily + approval + connection
    assert 'python -m carlecool.review' in daily
    assert '--fetch' in approval and 'GMAIL_APP_PASSWORD' in approval


def test_owner_approval_is_mandatory_and_direct_publish_closed():
    workflow = Path('.github/workflows/approve-reel.yml').read_text()
    assert 'github.event.comment.user.login == github.repository_owner' in workflow
    assert "github.event.comment.body == '/publish'" in workflow
    assert 'PUBLISH_ENABLED' in workflow
    cli = Path('carlecool/main.py').read_text()
    assert 'Direct publication is disabled' in cli
