"""Package B (27 Nov): Shot DNA, best window, footage library."""
import subprocess
from pathlib import Path

from carlecool import library, shot_analysis
from carlecool.video import Video


def _clip(path, src="testsrc2=s=180x320:r=24:d=12"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_best_window_avoids_dark_part_and_cuts(tmp_path):
    # 6 s black, then 10 s of a lit, moving test picture
    black = _clip(tmp_path / "b.mp4", "color=c=black:s=180x320:r=24:d=6")
    lit = _clip(tmp_path / "l.mp4", "testsrc2=s=180x320:r=24:d=10")
    both = tmp_path / "both.mp4"
    (tmp_path / "list.txt").write_text(f"file '{black.name}'\nfile '{lit.name}'\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp_path / "list.txt"),
                    "-c", "copy", str(both)], check=True)
    dna = shot_analysis.analyze(both)
    assert dna["duration"] > 15 and dna["best_start"] >= 5.0 and dna["best_length"] == shot_analysis.WINDOW
    assert 0 <= dna["luma"] <= 1 and dna["lab"] and dna["sharpness"] > 0
    cut = shot_analysis.cut_to_window(both, dna, tmp_path / "w.mp4")
    assert cut.name == "w.mp4" and abs(shot_analysis._probe(cut)[0] - shot_analysis.WINDOW) < 0.2


def test_library_add_reuse_skip_and_prune(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "CACHE", tmp_path / "cache")
    clip = _clip(tmp_path / "c.mp4")
    dna = shot_analysis.analyze(clip)
    data = {"version": 1, "clips": {}}
    v = Video("abc123", "coverr", title="Woman with a turntable", query="turntable",
              page_url="https://coverr.co/videos/x", licence="Coverr License", width=1080, height=1920)
    assert library.add(data, v, clip, dict(dna, quality=0.9), director="lana", theme="studio", run_id="1")
    assert library.file_for("abc123").is_file()
    e = data["clips"]["abc123"]
    assert e["director"] == "lana" and e["licence"] == "Coverr License" and "url" not in e
    got = library.candidates(data, director="lana", theme="studio", exclude=set(), limit=3)
    assert [x.id for x in got] == ["abc123"] and got[0].path.endswith("abc123.mp4") and got[0].vertical
    assert library.candidates(data, director="night", theme=None, exclude=set(), limit=3) == []
    assert library.candidates(data, director="lana", theme=None, exclude={"abc123"}, limit=3) == []
    blocked = Video("6kxRdq6Z1t", "coverr", title="x")  # owner blocklist
    library.add(data, blocked, clip, dict(dna, quality=0.9), director="lana", theme="studio", run_id="1")
    assert [x.id for x in library.candidates(data, director="lana", theme=None, exclude=set(), limit=5)] == ["abc123"]
    assert not library.add(data, Video("low", "coverr"), clip, dict(dna, quality=0.1), director="lana",
                           theme=None, run_id="1")
    monkeypatch.setattr(library, "MAX_FILES", 1)
    assert library.prune(data) == 1
    merged = library.merge({"clips": {"old": {"director": "night", "runs": ["0"]}}}, data)
    assert set(merged["clips"]) >= {"old", "abc123"}
