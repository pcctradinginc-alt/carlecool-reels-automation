from pathlib import Path

import pytest

from carlecool import zernio


def test_full_quality_master_over_16mb_is_allowed(tmp_path: Path):
    video = tmp_path / "master.mp4"
    with video.open("wb") as f:
        f.truncate(30_000_000)
    assert zernio.check_upload_file(video) == 30_000_000


def test_missing_or_oversized_file_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        zernio.check_upload_file(tmp_path / "missing.mp4")
    video = tmp_path / "huge.mp4"
    with video.open("wb") as f:
        f.truncate(zernio.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ValueError):
        zernio.check_upload_file(video)


def test_size_checked_before_journal_reservation():
    source = Path("carlecool/approve.py").read_text(encoding="utf-8")
    body = source[source.index("def publish_via_zernio"):]
    assert body.index("check_upload_file(video)") < body.index("state['pending'] = {")
