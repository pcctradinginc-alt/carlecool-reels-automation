"""SoundCloud owner OAuth checks: mocked only, no account/data mutation."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

from carlecool import sc_owner


class FakeResponse:
    def __init__(self, data):
        self.data = data
    def raise_for_status(self):
        return None
    def json(self):
        return self.data


class Session:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(self.replies.pop(0))
    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse(self.replies.pop(0))


def test_pkce_and_state_validation():
    verifier, challenge = sc_owner.new_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected
    state = "safe-random"
    callback = "http://localhost:8765/callback"
    url = sc_owner.authorize_url("client", callback, challenge, state)
    qs = parse_qs(urlparse(url).query)
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["response_type"] == ["code"]
    assert qs["state"] == [state]
    assert sc_owner.validate_callback(callback + "?code=a1b2c3&state=safe-random",
                                       callback, state) == "a1b2c3"
    with pytest.raises(ValueError, match="state"):
        sc_owner.validate_callback(callback + "?code=x&state=attacker", callback, state)
    with pytest.raises(ValueError, match="redirect URI"):
        sc_owner.validate_callback("https://attacker.test/callback?code=ok&state="+state,
                                   callback, state)
    with pytest.raises(ValueError):
        sc_owner.validate_callback(callback + "?code=x&code=y&state="+state, callback, state)


def test_exchange_uses_documented_token_endpoint_and_verifier():
    session = Session([{"access_token": "access", "refresh_token": "refresh", "expires_in": 3599}])
    tokens = sc_owner.exchange_code("client", "secret", "http://localhost:8765/callback",
                                    "one-time-code", "long-verifier", session=session)
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://secure.soundcloud.com/oauth/token"
    assert kwargs["data"]["grant_type"] == "authorization_code"
    assert kwargs["data"]["code_verifier"] == "long-verifier"
    assert tokens["refresh_token"] == "refresh"


def test_refresh_token_single_use_rotation_and_encrypted_persistence(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    path = tmp_path / "data" / "encrypted.enc"
    state = {"access_token": "expired-access", "refresh_token": "old-refresh",
             "expires_at": 100}
    sc_owner.persist_encrypted_token_state(path, state, key)
    assert b"old-refresh" not in path.read_bytes()
    assert sc_owner.decrypt_tokens(path.read_bytes(), key) == state
    monkeypatch.setenv("SC_OWNER_FERNET_KEY", key)
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "cid")
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_SECRET", "csecret")
    session = Session([{"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}])
    assert sc_owner.owner_session(token_file=path, commit_rotation=False,
                                  session=session, now=100) == "new-access"
    method, url, kw = session.calls[0]
    assert kw["data"]["grant_type"] == "refresh_token"
    assert kw["data"]["refresh_token"] == "old-refresh"
    decoded = sc_owner.decrypt_tokens(path.read_bytes(), key)
    assert decoded["refresh_token"] == "new-refresh"
    assert b"new-refresh" not in path.read_bytes()
    assert sc_owner.owner_session(token_file=path, commit_rotation=False,
                                  session=Session([]), now=200) == "new-access"


def test_wrong_decryption_key_blocks():
    encrypted = sc_owner.encrypt_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 123},
                                        Fernet.generate_key().decode())
    with pytest.raises(RuntimeError, match="decrypt"):
        sc_owner.decrypt_tokens(encrypted, Fernet.generate_key().decode())


def test_artist_profile_ownership_checked_read_only():
    session = Session([{"urn": "soundcloud:users:456"}, {"id": 456}])
    result = sc_owner.read_owner_identity("mock-owner-token", "https://soundcloud.com/carlecool",
                                           session=session)
    assert result["id"] == "456"
    assert len(session.calls) == 2
    assert all(method == "GET" for method, _, _ in session.calls)
    assert all(kw["headers"]["Authorization"] == "OAuth mock-owner-token"
               for _, _, kw in session.calls)
    with pytest.raises(RuntimeError, match="not the CarleCool profile"):
        sc_owner.read_owner_identity("token", "https://soundcloud.com/carlecool",
                                     session=Session([{"id": 999}, {"id": 456}]))


def test_owner_download_metadata_probe_does_not_request_audio():
    session = Session([
        {"id": 100, "user": {"id": 456}, "downloadable": False, "download_url": None},
        {"id": 101, "user": {"id": 456}, "downloadable": True,
         "download_url": "https://api.soundcloud.com/tracks/101/download"},
    ])
    result = sc_owner.probe_owned_tracks("token", "456", ["100", "101"], session=session)
    assert result == {"checked": 2, "owned": 2, "downloadable": 1, "download_url_available": 1}
    assert all(kw["headers"]["Authorization"] == "OAuth token"
               for _, _, kw in session.calls)
    assert all(method == "GET" and "/tracks/soundcloud:tracks:" in url
               for method, url, _ in session.calls)
    assert not any(url.endswith("/download") for _, url, _ in session.calls)


def test_reject_other_artist_or_unsafe_track_id():
    with pytest.raises(RuntimeError, match="not owned"):
        sc_owner.probe_owned_tracks("t", "456", ["12"],
                                   session=Session([{"id": 12, "user": {"id": 789}}]))
    with pytest.raises(ValueError, match="Unsafe"):
        sc_owner.probe_owned_tracks("t", "456", ["../../secret"], session=Session([]))


def test_authorization_is_not_possible_without_encrypted_state(monkeypatch, tmp_path):
    monkeypatch.setenv("SC_OWNER_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", "cid")
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_SECRET", "secret")
    with pytest.raises(RuntimeError, match="not yet configured"):
        sc_owner.owner_session(token_file=tmp_path / "missing.enc", commit_rotation=False)
