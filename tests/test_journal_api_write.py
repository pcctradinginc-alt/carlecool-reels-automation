"""Journal writes via the GitHub contents API survive unrelated commits (offline)."""
import base64
import json
from unittest.mock import MagicMock

import pytest
import requests

from carlecool import state as journal


class FakeGitHub:
    """Minimal contents API for data/state.json; `sha` changes on every write."""

    def __init__(self, text):
        self.text, self.version, self.puts = text, 1, []
        self.conflicts = 0

    def __call__(self, method, path, json_body=None):
        if method == "GET":
            return {"sha": f"v{self.version}", "content": base64.b64encode(self.text.encode()).decode()}
        assert method == "PUT" and path == "contents/data/state.json"
        if self.conflicts:
            self.conflicts -= 1
            resp = MagicMock(status_code=409)
            raise requests.HTTPError(response=resp)
        assert json_body["sha"] == f"v{self.version}" and json_body["branch"] == "main"
        self.text = base64.b64decode(json_body["content"]).decode()
        self.version += 1
        self.puts.append(json_body["message"])
        return {}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    text = json.dumps({"published": [], "pending": None}, indent=2) + "\n"
    (tmp_path / "data/state.json").write_text(text)
    monkeypatch.setattr(journal.time, "sleep", lambda s: None)
    return FakeGitHub(text)


def test_reserve_record_publish_sequence_writes_three_times(repo):
    state = journal.load_state()
    for step in ("reserve", "record", "published"):
        state["pending"] = None if step == "published" else {"step": step}
        journal.save_state(state)
        journal.commit_state(f"journal: {step}", request=repo)
    assert repo.puts == ["journal: reserve", "journal: record", "journal: published"]
    assert json.loads(repo.text)["pending"] is None


def test_unrelated_commits_do_not_matter_and_sha_race_is_retried(repo):
    state = journal.load_state()
    state["pending"] = {"step": "reserve"}
    journal.save_state(state)
    repo.conflicts = 1  # someone committed between our GET and PUT
    journal.commit_state("journal: reserve", request=repo)
    assert repo.puts == ["journal: reserve"]


def test_concurrent_change_to_the_journal_itself_is_never_overwritten(repo):
    state = journal.load_state()
    repo.text = json.dumps({"published": [{"manual": True}], "pending": None}, indent=2) + "\n"
    state["pending"] = {"step": "reserve"}
    journal.save_state(state)
    with pytest.raises(RuntimeError, match="changed on main"):
        journal.commit_state("journal: reserve", request=repo)
    assert repo.puts == []


def test_identical_content_is_a_no_op(repo):
    journal.load_state()
    journal.commit_state("journal: nothing", request=repo)
    assert repo.puts == []
