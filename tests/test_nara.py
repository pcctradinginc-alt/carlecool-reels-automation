"""National Archives Catalog source (owner, 27 Nov): rights filter, budget, API usage."""
from datetime import datetime, timezone

from carlecool import nara


def _hit(na, title, use="Unrestricted", access="Unrestricted", fname="film.mp4",
         url="https://catalog.archives.gov/OpaAPI/media/1/film.mp4"):
    return {"_id": str(na), "_source": {"record": {
        "naId": na, "title": title, "useRestriction": {"status": use}, "accessRestriction": {"status": access},
        "productionDates": [{"year": 1962}],
        "digitalObjects": [{"objectFilename": fname, "objectUrl": url, "objectType": "Video (MP4)"}]}}}


def test_only_unrestricted_mp4_with_safe_titles():
    payload = {"statusCode": 200, "body": {"hits": {"hits": [
        _hit(1, "Summer at the Beach, 1962"),
        _hit(2, "Regatta", use="Restricted - Possibly"),
        _hit(3, "Sailing", access="Restricted"),
        _hit(4, "President Kennedy at Hyannis Port"),         # no celebrity likeness
        _hit(5, "Navy Training Film"),                          # military
        _hit(6, "Boardwalk", fname="film.mp3", url="https://catalog.archives.gov/x/film.mp3"),
        _hit(7, "Warm summer evening at the pier"),              # "war" only as a whole word
        _hit(8, "Pier", url="https://evil.example.com/film.mp4"),
    ]}}}
    got = nara.parse_hits(payload)
    assert [g["naId"] for g in got] == ["1", "7"]
    assert got[0]["page"] == "https://catalog.archives.gov/id/1" and got[0]["year"] == 1962


def test_budget_keeps_every_day_of_the_month_covered():
    now = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)   # 4 days left incl. today
    assert nara.run_budget({}, now) == nara.RUN_CAP          # plenty left → per-run cap
    heavy = {"nara": {"events": [{"at": "2026-11-20T10:00:00+00:00", "run": "x", "requests": 9_000}]}}
    assert nara.run_budget(heavy, now) == 0                  # 90 % reserve line reached
    near = {"nara": {"events": [{"at": "2026-11-20T10:00:00+00:00", "run": "x", "requests": 8_900}]}}
    assert nara.run_budget(near, now) == 100 // (4 * nara.RUNS_PER_DAY)
    last_month = {"nara": {"events": [{"at": "2026-10-30T10:00:00+00:00", "run": "x", "requests": 9_999}]}}
    assert nara.run_budget(last_month, now) == nara.RUN_CAP  # a new month starts fresh


def test_record_keeps_coverr_and_counts_calls(tmp_path):
    from carlecool import providers
    path = tmp_path / "usage.json"
    providers.record(12, None, "r1", path=path)
    nara.record(5, "r1", path=path)
    data = providers.load(path)
    assert data["coverr"]["events"][0]["requests"] == 12 and nara.used_this_month(data) == 5
    providers.record(3, None, "r2", path=path)                # Coverr bookkeeping keeps the NARA part
    assert nara.used_this_month(providers.load(path)) == 5


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Session:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return _Resp(self.status, {"body": {"hits": {"hits": [_hit(9, "Sailing on the bay")]}}})


def test_searcher_uses_documented_parameters_and_respects_budget(monkeypatch):
    monkeypatch.setenv("NARA_API_KEY", "test-key")
    s = nara.Searcher(budget=2, session=_Session())
    assert s.search("sailing")[0]["id"] == "nara-9"
    url, params, headers = s.session.calls[0]
    assert url == nara.API and headers["x-api-key"] == "test-key"
    assert params["typeOfMaterials"] == "Moving Images" and params["availableOnline"] == "true"
    s.search("regatta")
    assert s.search("tennis") == [] and s.used == 2           # third call over budget: no request
    refused = nara.Searcher(budget=5, session=_Session(status=429))
    assert refused.search("x") == [] and refused.budget == 1   # stops after a refusal


def test_without_key_nothing_happens(monkeypatch, tmp_path):
    monkeypatch.delenv("NARA_API_KEY", raising=False)
    assert nara.fetch_nara("lana", set(), tmp_path) == ([], 0)


def test_archive_titles_with_snow_or_children_are_skipped():
    from carlecool import archives
    t = "Clark Family Home Movies Kids in Snow R.B.'s First Communion"
    assert archives._blocked(archives._clean(t), archives.PRELINGER_EXCLUDE)
    assert not archives._blocked(archives._clean("Summer at the beach, 1956"), archives.PRELINGER_EXCLUDE)
