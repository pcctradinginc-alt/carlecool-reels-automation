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
    from carlecool import library
    monkeypatch.setattr(library, "PATH", tmp_path / "lib.json")
    report = library_builder.build(out_dir=tmp_path / "out")
    assert report["added"] == 0 and report["coverr_requests"] == 0
