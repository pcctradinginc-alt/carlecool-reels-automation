"""Learning from the owner's publish / discard decisions (26 Nov): weak, gradual, no bans."""
from types import SimpleNamespace

from carlecool import decisions
from carlecool.review import encode_issue_data


def _issue(number, state, sources):
    payload = {"run_id": number, "sha256": "a" * 64, "video_ids": [s["id"] for s in sources],
               "footage_sources": sources, "reel_facts": {"style": "lana", "theme": "coast"}}
    return {"number": number, "state": state, "body": "x\n" + encode_issue_data(payload)}


def test_collect_published_discarded_and_ignores_undecided():
    issues = [_issue(1, "closed", [{"id": "a", "motif": "Sailboat", "used": True},
                                   {"id": "b", "motif": "dock", "used": False}]),
              _issue(2, "closed", [{"id": "c", "motif": "speedboat"}]),
              _issue(3, "open", [{"id": "d", "motif": "porch"}])]
    data = decisions.collect(issues, {1}, lambda n: ["❌ Reel verworfen, keine Veröffentlichung."] if n == 2 else [])
    assert [(d["issue"], d["decision"]) for d in data["decisions"]] == [(1, "published"), (2, "discarded")]
    assert data["decisions"][0]["video_ids"] == ["a"]           # unused clip b carries no signal
    assert data["decisions"][0]["motifs"] == ["sailboat"]


def test_adjustment_is_gradual_and_never_a_ban():
    data = {"decisions": [{"decision": "discarded", "video_ids": ["x"], "motifs": ["speedboat"]}] * 10
            + [{"decision": "published", "video_ids": ["y"], "motifs": ["sailboat"]}]}
    clips, motifs = decisions.scores(data)
    bad = decisions.adjustment(SimpleNamespace(id="x", query="Speedboat"), clips, motifs)
    one = decisions.adjustment(SimpleNamespace(id="z", query="speedboat"),
                               *decisions.scores({"decisions": data["decisions"][:1]}))
    good = decisions.adjustment(SimpleNamespace(id="y", query="sailboat"), clips, motifs)
    assert -0.56 <= bad < 0 and abs(one) <= 0.05 + 1e-9         # capped; one discard is a small nudge
    assert 0 < good <= decisions.BONUS_CAP
    assert decisions.adjustment(SimpleNamespace(id="n", query="porch"), clips, motifs) == 0.0
