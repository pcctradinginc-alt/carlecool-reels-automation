"""Reach effects (owner, 27 Nov: "Optimiere die Videos für mehr Reichweite, mach sie
interessanter, Effekte").

TikTok data of the first 12 Reels: ~220 views each (the platform's test pool), average
watch time ~2 s, completion 1-3 %. People leave in the first two seconds, so the picture
must move from the very first frame and never stand still. The effects stay in the
style's film language (no glitches, no shake, no modern transitions):

1. Opening push: shot 0 starts at full frame and pushes in with an ease-out (~1 s).
   Starting at scale 1.0 keeps the loop seam intact (last frame → first frame).
2. Camera drift: every interior shot slowly pushes in or pulls out (alternating), so
   static stock shots become a moving camera.
3. Film flash: the drop (hook) and the strongest beat cuts open with a short exposure
   flash that decays within ~0.2 s, like a film splice — always on the cut, on the beat.
The last shot stays untouched (it is the loop seam), and so do shots that dissolve in.
CARLECOOL_REACH_FX=off turns everything off.
"""
from __future__ import annotations

import os

FX: dict[str, dict] = {}  # per director, filled from directors/*.json below
# Creative Directors (27 Nov): every director brings its effect strengths ("fx").
from . import directors as _directors  # noqa: E402
for _n, _d in _directors.load_all().items():
    if _d.get("fx"):
        FX[_n] = dict(_d["fx"])
DEFAULT = {"push": 0.07, "drift": 0.04, "flash": 0.14, "flashes": 2}
PUSH_TAU = 0.45        # s: ease-out of the opening push (≈ 90 % reached after 1 s)
FLASH_TAU = 0.07       # s: flash decay (3-4 frames visible)
FLASH_RANK = 0.85      # relative beat energy for a peak flash
FLASH_GAP = 3.0        # s between two flashes
MIN_DRIFT_SHOT = 0.8   # s: shorter shots don't drift (would read as a jerk)
# Unified Creative Director bible (27 Nov): "keine unnötigen Effekte oder künstlichen Zooms",
# "unterschiedliche Hook-Strategien statt obligatorischer Bewegung". A slow zoom only gives
# life to footage that stands still; moving footage keeps its own camera.
STATIC_MOTION = 1.5    # look.motion_score (mean grey-level difference, 6 fps): below = static
HOOK_STRATEGIES = ("motion", "push")  # motion: the liveliest clip opens as it is; push: push-in on a still opener


def hook_strategy(run_key: str, strategies=None) -> str:
    """Opening strategy of this Reel (A/B, recorded in reel_facts.hook_strategy)."""
    import hashlib
    pool = tuple(strategies or HOOK_STRATEGIES)
    return pool[int.from_bytes(hashlib.sha256(f"{run_key}|hookstrategy".encode()).digest()[:2], "big") % len(pool)]


def is_static(motion: float | None) -> bool:
    return motion is not None and 0 <= float(motion) < STATIC_MOTION


def enabled() -> bool:
    return os.getenv("CARLECOOL_REACH_FX", "on").strip().lower() not in ("off", "false", "0", "no")


def plan(style: str | None, features, starts: list[float], durations: list[float],
         shot_look: list[dict], motion: list[float] | None = None, strategy: str = "push") -> list[dict]:
    """Per shot: {"zoom": None | ("push"|"in"|"out", amount), "flash": 0..1}.

    `motion`: motion score of each shot's source (None = unknown → no zoom on it)."""
    n = len(starts)
    out = [{"zoom": None, "flash": 0.0} for _ in range(n)]
    if n == 0 or not enabled():
        return out
    from .look import shot_energy
    fx = FX.get(_directors.current() or "") or FX.get(style or "", DEFAULT)
    if os.getenv("CARLECOOL_PIPELINE", "").strip().lower() == "classic":
        still = [True] * n  # #73 code: push on the opener, drift on every interior shot
    else:
        still = [is_static(motion[i]) if motion is not None and i < len(motion) else False for i in range(n)]
    if strategy == "push" and still[0]:
        out[0]["zoom"] = ("push", fx["push"])
    direction = "in"
    for i in range(1, n - 1):
        if still[i] and durations[i] >= MIN_DRIFT_SHOT and not shot_look[i].get("punch_in"):
            out[i]["zoom"] = (direction, fx["drift"])
            direction = "out" if direction == "in" else "in"
    energy = [shot_energy(features, s, d) for s, d in zip(starts, durations)]
    order = sorted(range(n), key=lambda k: (energy[k], k))
    rank = [0.0] * n
    for pos, k in enumerate(order):
        rank[k] = pos / max(1, n - 1)
    hook = float(getattr(features, "hook_at", 0.0) or 0.0)
    candidates = [i for i in range(1, n - 1) if not shot_look[i].get("dissolve_in")]
    # the drop first, then the loudest cuts
    candidates.sort(key=lambda i: (0 if hook > 0 and abs(starts[i] - hook) < 0.15 else 1, -rank[i], i))
    chosen: list[int] = []
    for i in candidates:
        is_hook = hook > 0 and abs(starts[i] - hook) < 0.15
        if not is_hook and rank[i] < FLASH_RANK:
            continue
        if all(abs(starts[i] - starts[j]) >= FLASH_GAP for j in chosen):
            chosen.append(i)
        if len(chosen) >= fx["flashes"]:
            break
    for i in chosen:
        out[i]["flash"] = fx["flash"]
    return out


def zoom_filters(zoom, duration: float, width: int, height: int, base: float = 1.0) -> list[str]:
    """Per-frame scale + centre crop; t is the shot's local time (input seeked to 0).
    `base` > 1 folds a punch-in into the same transform (one resampling)."""
    if not zoom:
        return []
    kind, amount = zoom
    d = max(0.1, float(duration))
    if kind == "hold":
        if base <= 1.0:
            return []
        return [f"scale={int(round(width * base / 2) * 2)}:{int(round(height * base / 2) * 2)}:flags=lanczos",
                f"crop={width}:{height}"]
    if kind == "push":
        z = f"({base:.4f}+{amount:.4f}*(1-exp(-t/{PUSH_TAU})))"
    elif kind == "in":
        z = f"({base:.4f}+{amount:.4f}*min(t/{d:.3f},1))"
    else:
        z = f"({base:.4f}+{amount:.4f}*max(1-t/{d:.3f},0))"
    return [f"scale=w='trunc({width}*{z}/2)*2':h='trunc({height}*{z}/2)*2':eval=frame:flags=bicubic",
            f"crop={width}:{height}"]


def flash_filter(amount: float) -> list[str]:
    if amount <= 0:
        return []
    return [f"eq=brightness='{amount:.3f}*exp(-t/{FLASH_TAU})':eval=frame"]
