from unittest.mock import Mock
import pytest
from carlecool import production_journal as journal
from carlecool import quality_gate as gate

def test_journal_reconciles_existing_message(monkeypatch):
    record = {"status": "SENDING", "run_id": 42}
    write = Mock()
    monkeypatch.setattr(journal, "read", lambda date: (record, "sha"))
    monkeypatch.setattr(journal, "sent_exists", lambda record: True)
    monkeypatch.setattr(journal, "write", write)
    assert journal.check("2026-11-26")
    assert record["status"] == "EMAIL_SENT"
    write.assert_called_once_with("2026-11-26", record, "sha")

def test_uncertain_delivery_never_blindly_retries(monkeypatch):
    monkeypatch.setattr(journal, "read", lambda date: ({"status": "SENDING"}, "sha"))
    monkeypatch.setattr(journal, "sent_exists", lambda record: False)
    write = Mock()
    monkeypatch.setattr(journal, "write", write)
    with pytest.raises(RuntimeError, match="uncertain"):
        journal.begin("2026-11-26", 42, "<test@invalid>", "digest")
    write.assert_not_called()

def test_quality_rejects_silent_master(monkeypatch):
    from carlecool import render
    monkeypatch.setattr(render, "probe_dimensions", lambda p: (1080,1920))
    monkeypatch.setattr(render, "probe_duration", lambda p: 18)
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: Mock(returncode=0, stderr="max_volume: -inf dB"))
    result = gate.inspect_reel("test.mp4", {"edit_plan": [{"source_index": 0}]}, 18)
    assert result["errors"]

def test_quality_flags_actual_repeated_sources(monkeypatch):
    from carlecool import render
    monkeypatch.setattr(render, "probe_dimensions", lambda p: (1080,1920))
    monkeypatch.setattr(render, "probe_duration", lambda p: 18)
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: Mock(returncode=0, stderr="max_volume: -1.5 dB"))
    result = gate.inspect_reel("test.mp4", {"edit_plan": [{"source_index": 0}]*4}, 18)
    assert not result["errors"]
    assert result["warnings"]


def test_low_resolution_only_allowed_in_explicit_offline_smoke(monkeypatch):
    from carlecool import render
    monkeypatch.setattr(render, "probe_dimensions", lambda p: (270,480))
    monkeypatch.setattr(render, "probe_duration", lambda p: 18)
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: Mock(returncode=0, stderr="max_volume: -1.5 dB"))
    monkeypatch.delenv("CARLECOOL_OFFLINE_SMOKE", raising=False)
    assert gate.inspect_reel("test.mp4", {}, 18)["errors"]
    monkeypatch.setenv("CARLECOOL_OFFLINE_SMOKE", "1")
    assert not gate.inspect_reel("test.mp4", {}, 18)["errors"]
