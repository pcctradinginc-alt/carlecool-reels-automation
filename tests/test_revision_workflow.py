"""Owner-only revision workflow must never post to Instagram."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from carlecool import revise
from carlecool.creative import default_profile
from carlecool.review import encode_issue_data


def example_issue():
    payload = {
        "run_id": 111, "sha256": "a" * 64, "track_id": "123",
        "video_ids": ["a", "b", "c", "d", "e"],
        "caption": "original", "footage_sources": [],
        "creative_profile": default_profile(), "revision_number": 0,
    }
    return {"state": "open", "labels": [{"name": "carlecool-review"}],
            "body": encode_issue_data(payload)}


def test_owner_required_even_if_invoked_outside_workflow(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_ACTOR", "outsider")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "owner")
    with pytest.raises(RuntimeError, match="owner"):
        revise.revise(12, "/revise more_nature")


def test_revision_regenerates_same_track_and_creates_distinct_approval(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_ACTOR", "owner")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "owner")
    monkeypatch.setenv("GITHUB_RUN_ID", "222")
    monkeypatch.setenv("GH_TOKEN", "fake")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr(revise, "PROFILE_PATH", tmp_path / "data/creative-profile.json")
    calls = []
    issue = example_issue()
    def github(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json_body")))
        if method == "GET":
            return issue
        return {}
    def make_video(*args, **kwargs):
        assert kwargs["track_id"] == "123"
        assert kwargs["creative_profile"]["revision"] == 1
        folder = Path("output")
        folder.mkdir(exist_ok=True)
        (folder / "sample.mp4").write_bytes(b"private")
        (folder / "reel_metadata.json").write_text(json.dumps({
            "title": "test", "track_id": "123", "video_ids": ["f", "g", "h", "i", "j"],
            "caption": "new", "footage_sources": [], "output": "output/sample.mp4",
            "sha256": hashlib.sha256(b"private").hexdigest(),
            "creative_profile": kwargs["creative_profile"],
        }), encoding="utf-8")
    monkeypatch.setattr(revise, "github_request", github)
    monkeypatch.setattr(revise, "process", make_video)
    monkeypatch.setattr(revise, "create_review", lambda *a, **kw: {
        "html_url": "https://github.com/owner/repo/issues/15", "number": 15})
    monkeypatch.setattr(revise, "send_review_email", lambda *a, **kw: True)
    monkeypatch.setattr(revise.subprocess, "run", lambda *a, **kw: MagicMock(returncode=0))
    url = revise.revise(12, "/revise mehr natur, weniger skate")
    assert url.endswith("/issues/15")
    assert ("PATCH", "issues/12", {"labels": []}) in calls
    assert ("PATCH", "issues/12", {"state": "closed"}) in calls
    saved = json.loads((tmp_path / "data/creative-profile.json").read_text())
    assert saved["revision"] == 0
    assert saved["weights"]["nature"] > default_profile()["weights"]["nature"]


def test_revision_failure_restores_original_approval_label(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_ACTOR", "owner")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "owner")
    monkeypatch.setenv("GITHUB_RUN_ID", "222")
    monkeypatch.setenv("GH_TOKEN", "fake")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    calls = []
    def github(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json_body")))
        if method == "GET":
            return example_issue()
        return {}
    monkeypatch.setattr(revise, "github_request", github)
    monkeypatch.setattr(revise, "process", lambda **kw: (_ for _ in ()).throw(RuntimeError("render failed")))
    with pytest.raises(RuntimeError, match="render failed"):
        revise.revise(12, "/revise more_mpc")
    assert ("PATCH", "issues/12", {"labels": ["carlecool-review"]}) in calls
