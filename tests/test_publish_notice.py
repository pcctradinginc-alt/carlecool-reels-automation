from carlecool.publish_notice import describe
from carlecool.approve import validate_distribution_permissions
import pytest

def test_success_requires_durable_publication_record():
    title, body = describe({"published": [{"approval_issue": 1, "platform_status": {"tiktok": "published"}}]}, 1, "tiktok", {})
    assert "bestätigt" in title
    assert "Post-URL fehlt" in body

def test_pending_never_claims_success_or_retries():
    title, body = describe({"pending": {"issue_number": 1}}, 1, "tiktok", {"publish": "failure"})
    assert "ungeklärt" in title and "keine automatische" in body

def test_gmail_failure_is_reported_before_upload():
    title, body = describe({}, 1, "tiktok", {"restore": "failure"})
    assert title == "Nicht veröffentlicht" and "Gmail" in body

def test_ai_permission_gate_remains_explicit(monkeypatch):
    approval = {"footage_sources": [{"provider": "ai"}], "caption": "test"}
    monkeypatch.delenv("AI_VIDEO_PUBLISH_LICENSE_CONFIRMED", raising=False)
    with pytest.raises(RuntimeError, match="AI-video"):
        validate_distribution_permissions(approval)
    monkeypatch.setenv("AI_VIDEO_PUBLISH_LICENSE_CONFIRMED", "true")
    validate_distribution_permissions(approval)
