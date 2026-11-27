"""Phase 5 (27 Nov): checkpoint fix, comparable observations, factor report, calibration."""
from carlecool import calibration, decisions, performance


def _post(at, cps):
    return {"at": at, "facts": {}, "checkpoints": cps}


def test_checkpoints_get_their_real_age_and_wrong_labels_are_fixed():
    m = {"tiktok": {"views": 100.0}}
    data = {"posts": {
        "a": _post("2026-11-23T19:44:00+00:00", {"d1": {"fetched": "2026-11-25T23:24:00+00:00", "platforms": m}}),
        "b": _post("2026-11-20T15:37:00+00:00", {"d2": {"fetched": "2026-11-24T01:57:00+00:00", "platforms": m}}),
        "c": _post("2026-11-24T19:01:00+00:00", {"d1": {"fetched": "2026-11-25T23:24:00+00:00", "age_hours": 28.4,
                                                       "platforms": m}})}}
    log = performance.normalize_checkpoints(data)
    posts = data["posts"]
    assert "d2" in posts["a"]["checkpoints"] and posts["a"]["checkpoints"]["d2"]["relabelled_from"] == "d1"
    assert posts["b"]["checkpoints"]["d2"]["valid"] is False          # 82 h is not a 2-day value
    assert posts["c"]["checkpoints"]["d1"]["valid"] is True
    assert len(log) == 2 and data["migrations"]


def test_factor_report_is_report_only():
    rows = [{"relative": 1.0 + i / 10, "facts": {"pipeline": "classic" if i % 2 else "cinematic"}} for i in range(6)]
    model = performance._model_for(rows)
    assert model["report"]["pipeline"]["classic"]["n"] == 3 and model["report"]["pipeline"]["classic"]["enough"] is False


def test_revision_requests_are_a_signal_and_calibration_waits_for_enough_verdicts():
    from carlecool.review import encode_issue_data
    body = encode_issue_data({"run_id": 1, "sha256": "ab" * 32,
                              "reel_facts": {"style": "lana", "pipeline": "classic", "critic": {"score": 0.7}},
                              "footage_sources": [{"id": "x", "motif": "m", "used": True}]})
    got = decisions.collect([{"number": 5, "state": "open", "body": body}], set(),
                            lambda n: ["/revise mehr Meer"])
    d = got["decisions"][0]
    assert d["decision"] == "revision" and d["pipeline"] == "classic" and d["critic"] == 0.7
    clips, _ = decisions.scores(got)
    assert clips.get("x", 0) == 0  # a revision request does not move the ranking
    few = calibration.calibrate({"decisions": [{"issue": 1, "decision": "published", "critic": 0.9}]},
                                {"verdicts": [{"issue": 2}]})
    assert few["status"] == "insufficient"
    many = {"decisions": [{"issue": i, "decision": "published", "critic": 0.85} for i in range(12)]
                         + [{"issue": 100 + i, "decision": "discarded", "critic": 0.55} for i in range(10)]}
    cal = calibration.calibrate(many, {"verdicts": []})
    assert cal["status"] == "calibrated" and cal["retry_below"] == 0.7
    flat = {"decisions": [{"issue": i, "decision": "published", "critic": 0.6} for i in range(12)]
                         + [{"issue": 100 + i, "decision": "discarded", "critic": 0.8} for i in range(10)]}
    assert calibration.calibrate(flat, {"verdicts": []})["status"] == "not predictive"
