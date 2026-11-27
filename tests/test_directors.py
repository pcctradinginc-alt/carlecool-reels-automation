"""Creative Directors (owner, 27 Nov): one file per director, swappable without code."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from carlecool import directors, hooktext, reach, signature, style, stylegate, themes

SNAPSHOT = json.loads(Path("tests/fixtures/directors-snapshot-27nov.json").read_text(encoding="utf-8"))
ROLES = ("skater", "woman", "friends", "friends2", "americana", "flag", "car", "gear")


def _effective(name, variant, use):
    directors.use(name if use else None)
    try:
        key = themes.key_for("lana", variant)
        prof = {k: 50 for k in style.STYLE_WEIGHTS["lana"]}
        return {
            "label": style.label({"style": "lana", "variant": variant}),
            "themes": themes.THEMES[key],
            "music": {t: themes.MUSIC[(key, t)] for t in themes.THEMES[key]},
            "wanted": list(stylegate.WANTED[directors.key("lana", variant)]),
            "look": style.look("lana", variant),
            "grade": style.grade_filters("lana", variant),
            "weights": style.blended_weights(prof, "lana", variant),
            "search": list(directors.get(key)["search"]),
            "roles": {r: list(signature.queries_for(r, "lana", variant)) for r in ROLES},
            "hook_lines": list(hooktext.LINES[key]),
            "fx": reach.FX[key],
            "references": directors.get(key)["references"],
            "pace": style.pace_for("medium", "lana"),
        }
    finally:
        directors.use(None)


def test_moving_lana_and_night_into_director_files_changed_nothing():
    for name, variant in (("lana", None), ("night", "night")):
        for use in (True, False):  # with the director in use, and via the legacy style/variant key
            got = json.loads(json.dumps(_effective(name, variant, use), sort_keys=True))
            assert got == SNAPSHOT[name], (name, use, [k for k in got if got[k] != SNAPSHOT[name][k]])


def test_rotation_and_choice_by_director_name(monkeypatch):
    assert style.rotate_style([], "x") in ("lana", "night")
    night = style.analyze(None, override="night")
    assert night["director"] == "night" and night["style"] == "lana" and night["variant"] == "night"
    monkeypatch.setenv("CARLECOOL_DIRECTORS", "night,unknown")
    assert directors.active() == ["night"]
    assert style.rotate_style([{"style": "lana"}] * 5, "x") == "night"


def test_a_new_director_is_just_a_new_file(tmp_path):
    for f in Path("directors").glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    doc = json.loads((tmp_path / "lana.json").read_text(encoding="utf-8"))
    doc.update(name="gilded", label="Gilded Rebels", order=3,
               themes={"yacht": dict(doc["themes"]["hamptons"], label="Yacht & Riviera",
                                     lines=["pov: the last summer on the yacht"])},
               look=dict(doc["look"], chroma_shift=3), fx=dict(doc["fx"], flashes=2))
    (tmp_path / "gilded.json").write_text(json.dumps(doc), encoding="utf-8")
    code = """
from carlecool import directors, style, themes, hooktext, reach
assert directors.active() == ['lana', 'night', 'gilded'], directors.active()
d = style.analyze(None, override='gilded')
assert d['director'] == 'gilded' and d['style'] == 'lana' and d['variant'] is None, d
directors.use('gilded')
assert themes.choose('lana', None, [], 'r') == 'yacht'
assert themes.lines('lana', None, 'yacht') == ('pov: the last summer on the yacht',)
assert style.look('lana')['chroma_shift'] == 3 and reach.FX['gilded']['flashes'] == 2
assert style.label(d) == 'Gilded Rebels'
print('ok')
"""
    env = dict(os.environ, CARLECOOL_DIRECTORS_DIR=str(tmp_path))
    env.pop("CARLECOOL_DIRECTORS", None)
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr
