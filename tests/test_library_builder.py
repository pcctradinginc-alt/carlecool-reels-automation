"""Owner goal 28 Nov: the footage library is filled off-peak, least-covered theme first."""
from datetime import datetime, timezone

from carlecool import library_builder, themes


def test_target_alternates_directors_and_picks_the_least_covered_theme(monkeypatch):
    monkeypatch.delenv("CARLECOOL_DIRECTORS", raising=False)
    day = datetime(2026, 11, 28, 1, tzinfo=timezone.utc)
    night = datetime(2026, 11, 28, 23, tzinfo=timezone.utc)
    d1, _ = library_builder.pick_target({"clips": {}}, day)
    d2, _ = library_builder.pick_target({"clips": {}}, night)
    assert {d1, d2} == {"lana", "night"}
    full = {f"c{i}": {"director": d1, "theme": t} for i, t in enumerate(list(themes.THEMES[d1])[:-1])}
    _, theme = library_builder.pick_target({"clips": full}, day)
    assert theme == list(themes.THEMES[d1])[-1]


def test_build_without_keys_changes_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("COVERR_API_KEY", raising=False)
    monkeypatch.delenv("NARA_API_KEY", raising=False)
    monkeypatch.setenv("CARLECOOL_SEMANTIC", "off")
    monkeypatch.setenv("CARLECOOL_WIKIMEDIA", "off")   # no network in tests
    from carlecool import library
    monkeypatch.setattr(library, "PATH", tmp_path / "lib.json")
    report = library_builder.build(out_dir=tmp_path / "out")
    assert report["added"] == 0 and report["coverr_requests"] == 0


def test_wikimedia_theme_search_only_free_licences(monkeypatch):
    from carlecool import wikimedia

    class R:
        status_code = 200

        def json(self):
            def page(t, lic):
                return {"title": f"File:{t}.webm", "imageinfo": [{
                    "url": "https://upload.wikimedia.org/x.webm", "mime": "video/webm", "height": 1080, "width": 1920,
                    "size": 1000, "descriptionurl": "https://commons.wikimedia.org/wiki/File:x",
                    "extmetadata": {"LicenseShortName": {"value": lic}}}]}
            return {"query": {"pages": {"1": page("Skateboarding at night", "CC BY 4.0"),
                                        "2": page("Skate park", "CC BY-SA 4.0"),
                                        "3": page("Downhill skate", "Public domain"),
                                        "4": page("Kids skateboarding", "CC0")}}}

    class S:
        headers: dict = {}

        def get(self, *a, **k):
            return R()
    monkeypatch.setattr(wikimedia.time, "sleep", lambda s: None)
    got = wikimedia.search_files("skateboarding", session=S())
    assert sorted(i["license"] for i in got) == ["CC BY 4.0", "Public domain"]  # no SA, no children
