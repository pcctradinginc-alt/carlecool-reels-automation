"""All diagnostic output must be bounded and token-safe."""
from unittest.mock import Mock, patch
import requests

from carlecool import preflight

def test_preflight_masks_api_errors():
    r = requests.Response()
    r.status_code = 401
    r.url = "https://example.test/no-secrets"
    e = requests.HTTPError("Token dead: SECRET-LEAK-DO-NOT-PRINT", response=r)
    assert preflight._http_status(e) == "HTTP 401"

def test_no_missing_credentials_sent_to_provider(monkeypatch):
    for name in ("IG_ACCESS_TOKEN", "SOUNDCLOUD_CLIENT_ID", "SOUNDCLOUD_CLIENT_SECRET",
                 "COVERR_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "REVIEW_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    assert preflight.instagram().result == "BLOCKED"
    assert preflight.soundcloud().result == "BLOCKED"
    assert preflight.coverr().result == "BLOCKED"
    assert preflight.gmail().result == "BLOCKED"

def test_public_preflight_cannot_publish():
    import inspect
    src = inspect.getsource(preflight)
    assert "create_and_upload(" not in src
    assert "finish(" not in src
    assert "send_message(" not in src
    assert "upload-artifact" not in src
