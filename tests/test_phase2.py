"""Phase 2 (27 Nov): Shot DNA v2, DNA cache, era negatives, plan-led search, HDR handling."""
import subprocess
from pathlib import Path

from carlecool import creative_director, directors, shot_analysis, stylegate


def _clip(path, src):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_dna_v2_measures_camera_vs_subject_motion_and_edges(tmp_path):
    still = _clip(tmp_path / "s.mp4", "color=c=gray:s=180x320:r=24:d=6")
    pan = _clip(tmp_path / "p.mp4", "testsrc2=s=360x320:r=24:d=6,crop=180:320:'t*30':0")
    a, b = shot_analysis.analyze(still), shot_analysis.analyze(pan)
    assert a["version"] == shot_analysis.ANALYSIS_VERSION and a["hdr"] is False
    assert b["camera_motion"] > a["camera_motion"]
    assert {"lab", "luma"} <= set(b["edge_in"]) and {"lab", "luma"} <= set(b["edge_out"])
    assert 0 <= b["subject_x"] <= 1 and b["noise"] >= 0


def test_dna_cache_by_file_hash_and_version(tmp_path):
    clip = _clip(tmp_path / "c.mp4", "testsrc2=s=180x320:r=24:d=4")
    cache = tmp_path / "dna"
    first = shot_analysis.cached_analyze(clip, cache_dir=cache)
    files = list(cache.glob("*.json"))
    assert len(files) == 1 and f"_v{shot_analysis.ANALYSIS_VERSION}_" in files[0].name
    assert shot_analysis.cached_analyze(clip, cache_dir=cache) == first


def test_director_era_negatives_and_plan_led_search():
    assert any("smartphone" in u for u in directors.get("lana")["unwanted"])
    order = creative_director.search_order(["lighthouse", "sand dunes"],
                                           ["land rover", "american flag", "polo", "sand dunes", "tennis", "lighthouse"])
    assert order[:4] == ["land rover", "american flag", "lighthouse", "sand dunes"]
    assert stylegate.clip_verdicts([], "lana", None) == []


def test_hdr_to_sdr_chain_runs_for_pq_and_hlg(tmp_path):
    from carlecool.render import hdr_to_sdr
    for transfer in ("smpte2084", "arib-std-b67"):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=0.5", "-vf",
                        hdr_to_sdr(transfer), "-f", "null", "-"], check=True)
