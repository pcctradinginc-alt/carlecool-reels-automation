import pytest
from carlecool.instagram import Instagram


class Response:
    def __init__(self, data):
        self.data = data
    def raise_for_status(self):
        pass
    def json(self):
        return self.data


class Session:
    def __init__(self, data):
        self.data = data
        self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return Response(self.data)


def test_unified_token_auto_selects_one_account_using_get_only():
    session = Session({"data": [{"id": "17841400000012345", "username": "carlecool"}]})
    client = Instagram("", "fake-token", session=session)
    assert client.verify_access() == {"id": "17841400000012345", "username": "carlecool"}
    assert client.user_id == "17841400000012345"
    assert len(session.calls) == 1
    method, url, params = session.calls[0]
    assert method == "GET" and url.endswith("/me/assigned_instagram_accounts")
    assert params["headers"]["Authorization"] == "Bearer fake-token"
    assert "fake-token" not in url


def test_multiple_accounts_fail_closed():
    session = Session({"data": [{"id": "123", "username": "a"}, {"id": "456", "username": "b"}]})
    with pytest.raises(RuntimeError, match="IG_USER_ID"):
        Instagram("", "token", session=session).verify_access()
    assert Instagram("456", "token", session=session).verify_access()["id"] == "456"
    with pytest.raises(RuntimeError, match="not assigned"):
        Instagram("999", "token", session=session).verify_access()


def test_empty_or_paginated_accounts_fail_closed():
    with pytest.raises(RuntimeError, match="Expected one"):
        Instagram("", "token", session=Session({"data": []})).verify_access()
    with pytest.raises(RuntimeError, match="paginated"):
        Instagram("", "token", session=Session({"data": [{"id": "123"}], "paging": {"next": "more"}})).verify_access()


def test_missing_or_invalid_credentials_rejected():
    with pytest.raises(ValueError, match="IG_ACCESS_TOKEN"):
        Instagram("", "")
    with pytest.raises(ValueError, match="numeric"):
        Instagram("invalid", "token")
