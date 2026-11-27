"""Phase 1 (27 Nov): one reproducible Creative Plan per Reel, on the #73 basis."""
import json
from types import SimpleNamespace

from carlecool import creative_director, directors


def _features():
    return SimpleNamespace(bpm=96.0, hook_at=6.1, structure_events=(3.0, 9.5), kicks=(0.5, 1.0, 1.5))


def _plan():
    directors.use("lana")
    try:
        return creative_director.build_plan(
            director="lana", style_decision={"style": "lana", "variant": None, "basis": "manual"},
            theme="hamptons", features=_features(), length=15.6, keywords=["land rover", "american flag", "lighthouse"],
            roles=["flag", "woman"], hook_line="pov: the last warm evening of the year", hook_strategy="push",
            pipeline="classic", music_fit=0.5, length_reason="manual")
    finally:
        directors.use(None)


def test_plan_has_every_field_and_reasons():
    p = _plan().as_dict()
    for key in ("director", "theme", "film_idea", "leitmotif", "emotion", "dominant_motifs", "palette", "light",
                "camera", "musical_arc", "search", "hook", "transitions", "effects", "exclusions", "pipeline"):
        assert p[key] not in (None, "", [], {}), key
    assert "#73" in p["film_idea"] and p["dominant_motifs"][0] == "beach house"
    assert p["musical_arc"]["hook_at"] == 6.1 and p["reasons"]["theme"].startswith("music fit")
    assert any("Schnee" in e for e in p["exclusions"])


def test_plan_is_reproducible_and_serialisable():
    a, b = _plan().as_dict(), _plan().as_dict()
    assert a == b and json.loads(json.dumps(a)) == a
