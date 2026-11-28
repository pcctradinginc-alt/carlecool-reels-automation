"""Visual Coherence Engine (owner's plan, package C, 27 Nov).

"Eine Szene darf nicht allein deshalb verwendet werden, weil sie schön ist. Sie muss zum
Song, zum Filmkonzept, zur vorhergehenden und zur nachfolgenden Szene passen."

From the Shot DNA (shot_analysis.py) every pair of clips gets a transition score, with the
owner's starting weights (to be calibrated on real verdicts):

    emotional match 25 % · semantic link 20 % · colour continuity 15 % · motion continuity
    15 % · musical fit 10 % · light continuity 10 % · composition 5 %

Deliberate contrast stays allowed: a semantic link counts as strongly when two different
subjects share form / colour (a match cut) as when they are the same subject.

The whole order is optimised with a beam search over the free (unlocked) shots: bookends
(loop seam) and signature shots keep their places. Musical fit = calm clips on quiet
passages, moving clips on loud ones; composition = shot sizes vary (no five wide shots in
a row). Runs locally in milliseconds.
"""
from __future__ import annotations

import math

WEIGHTS = {"emotion": 0.25, "semantic": 0.20, "colour": 0.15, "motion": 0.15,
           "music": 0.10, "light": 0.10, "composition": 0.05}
BEAM = 12
SIZE_ORDER = {"wide": 0, "medium": 1, "close": 2, "detail": 3}


def _emb(dna):
    if not dna or not dna.get("embedding"):
        return None
    from .shot_analysis import decode_embedding
    v = decode_embedding(dna["embedding"])
    n = math.sqrt(float((v * v).sum())) or 1.0
    return v / n


def _closeness(a, b, scale) -> float:
    if a is None or b is None:
        return 0.5
    return max(0.0, 1.0 - abs(float(a) - float(b)) / scale)


VARIANTS = (None,                                            # the owner's starting weights
            {"music": 0.30, "emotion": 0.20, "semantic": 0.15},  # follows the music harder
            {"composition": 0.20, "colour": 0.20, "semantic": 0.10})  # shot-size rhythm + colour flow


def _weights(emphasis: dict | None) -> dict:
    w = dict(WEIGHTS, **(emphasis or {}))
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def _edge(dna: dict, side: str) -> dict:
    """Phase 3: the concrete last / first frame of the window, if the DNA has it."""
    e = (dna or {}).get(side) or {}
    return e if e.get("lab") else {}


def transition(a: dict | None, b: dict | None, ea=None, eb=None, weights: dict | None = None) -> dict:
    """Component scores (0..1) and the weighted total for cutting from clip a to clip b.
    Colour, light and the semantic link are judged on the real cut frames (end of a,
    start of b) when the Shot DNA carries them, else on the window averages."""
    if not a or not b:
        return {"total": 0.5}
    out_a, in_b = _edge(a, "edge_out"), _edge(b, "edge_in")
    if out_a and in_b:
        ea = _emb({"embedding": out_a.get("embedding")}) if out_a.get("embedding") else ea
        eb = _emb({"embedding": in_b.get("embedding")}) if in_b.get("embedding") else eb
        a = dict(a, lab=out_a["lab"], luma=out_a.get("luma", a.get("luma")))
        b = dict(b, lab=in_b["lab"], luma=in_b.get("luma", b.get("luma")))
    parts = {}
    # emotion: closeness to the owner's references + mood (brightness / warmth) of both
    parts["emotion"] = 0.5 * _closeness(a.get("ref_score"), b.get("ref_score"), 0.12) + \
        0.5 * _closeness(a.get("warmth"), b.get("warmth"), 25.0)
    if ea is not None and eb is not None:
        sim = float((ea * eb).sum())  # CLIP image-image cosine: ~0.5 unrelated … ~0.9 same subject
        # a shared look / form (match cut) already counts; contrast is carried by the other parts
        parts["semantic"] = min(1.0, max(0.0, (sim - 0.5) / 0.35))
    else:
        parts["semantic"] = 0.5
    la, lb = a.get("lab"), b.get("lab")
    if la and lb:
        dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))
        parts["colour"] = max(0.0, 1.0 - dist / 45.0)
    else:
        parts["colour"] = 0.5
    parts["motion"] = _closeness(a.get("motion"), b.get("motion"), 10.0)
    parts["light"] = 0.6 * _closeness(a.get("luma"), b.get("luma"), 0.35) + \
        0.4 * _closeness(a.get("contrast"), b.get("contrast"), 0.35)
    sa, sb = SIZE_ORDER.get(a.get("shot_size") or ""), SIZE_ORDER.get(b.get("shot_size") or "")
    parts["composition"] = 0.5 if sa is None or sb is None else (0.2 if sa == sb else 1.0)
    parts["music"] = 0.5  # set per slot in the sequence (energy vs motion)
    w = weights or WEIGHTS
    parts["total"] = sum(w[k] * parts[k] for k in w)
    return parts


FUNCTIONS = ("hook", "establishing", "atmosphere", "development", "contrast", "accent", "climax",
             "resolution", "loop")


def slot_functions(energies: list[float], starts: list[float], accents: set[int] | None = None) -> list[str]:
    """Dramaturgic function per slot from the music: hook (first), loop (last), climax (the
    loudest), accent (cuts on a kick / the drop), atmosphere (the calmest), establishing
    (second shot), resolution (second to last), contrast (a calm shot right after a loud
    one), development otherwise."""
    n = len(energies)
    if n == 0:
        return []
    out = ["development"] * n
    order = sorted(range(n), key=lambda i: energies[i])
    if n > 2:
        out[order[0]] = "atmosphere"
        out[order[-1]] = "climax"
    for i in (accents or set()):
        if 0 < i < n - 1 and out[i] == "development":
            out[i] = "accent"
    for i in range(1, n - 1):
        if out[i] == "development" and energies[i] < energies[i - 1] - 0.25:
            out[i] = "contrast"
    if n > 3:
        out[1] = "establishing"
        out[-2] = "resolution"
    out[0], out[-1] = "hook", "loop"
    return out


# what a function wants from a clip (shot size, motion rank)
FUNCTION_WANTS = {"establishing": ({"wide"}, None), "accent": ({"close", "detail"}, None),
                  "climax": (None, 1.0), "atmosphere": (None, 0.0), "contrast": (None, 0.2),
                  "resolution": ({"wide", "medium"}, 0.3)}


def function_fit(function: str, dna: dict | None, motion_rank: float | None) -> float:
    sizes, motion = FUNCTION_WANTS.get(function, (None, None))
    if not dna:
        return 0.5
    score, parts = 0.0, 0
    if sizes is not None:
        parts += 1
        score += 1.0 if dna.get("shot_size") in sizes else 0.3
    if motion is not None and motion_rank is not None:
        parts += 1
        score += 1.0 - abs(motion - motion_rank)
    return score / parts if parts else 0.5


MATCH_CUT_BONUS = 0.08  # a strong visual link (form / colour / subject) on a musical accent


def _music_fit(dna, energy_rank: float, motion_ranks: dict[int, float], src: int) -> float:
    if not dna or src not in motion_ranks:
        return 0.5
    return 1.0 - abs(energy_rank - motion_ranks[src])


def sequence(shots, energies: list[float], dna: list[dict | None], source_durations: list[float],
             locked: set[int], beam: int = BEAM, emphasis: dict | None = None,
             accents: set[int] | None = None, functions: list[str] | None = None):
    """Re-pair sources and free slots so the whole Reel flows; returns (shots, mean score)."""
    from .cinematic import Shot
    n = len(shots)
    free = [i for i in range(n) if i not in locked]
    if len(free) < 2 or not any(dna):
        return list(shots), None
    embs = {k: _emb(d) for k, d in enumerate(dna)}
    known = [k for k, d in enumerate(dna) if d and d.get("motion") is not None]
    order = sorted(known, key=lambda k: dna[k]["motion"])
    motion_ranks = {k: pos / max(1, len(order) - 1) for pos, k in enumerate(order)}
    e_order = sorted(range(n), key=lambda i: (energies[i], i))
    e_rank = {i: pos / max(1, n - 1) for pos, i in enumerate(e_order)}
    cache: dict[tuple[int, int], float] = {}
    weights = _weights(emphasis)

    def pair(x: int, y: int) -> float:
        if x == y:
            return -1.0  # the same clip twice in a row
        if (x, y) not in cache:
            cache[(x, y)] = transition(dna[x], dna[y], embs.get(x), embs.get(y), weights)["total"]
        return cache[(x, y)]

    pool = [shots[i].source_index for i in free]
    # beam over slots in time order; state = (score, assignment dict, remaining pool)
    states = [(0.0, {}, tuple(pool))]
    for i in range(n):
        new_states = []
        for score, assign, remaining in states:
            prev = assign.get(i - 1, shots[i - 1].source_index) if i > 0 else None
            if i in locked:
                src = shots[i].source_index
                s = score + (pair(prev, src) if prev is not None else 0.0)
                new_states.append((s, assign, remaining))
                continue
            tried = set()
            for k, src in enumerate(remaining):
                if src in tried:
                    continue
                tried.add(src)
                s = score + weights["music"] * _music_fit(dna[src], e_rank[i], motion_ranks, src)
                if functions:
                    s += 0.1 * function_fit(functions[i], dna[src], motion_ranks.get(src))
                if prev is not None:
                    link = pair(prev, src)
                    s += link
                    if accents and i in accents and prev != src and link > 0.7:
                        s += MATCH_CUT_BONUS  # match cut: strong visual link exactly on the beat accent
                nxt = i + 1
                if nxt < n and nxt in locked:
                    s += pair(src, shots[nxt].source_index)
                new_states.append((s, {**assign, i: src}, remaining[:k] + remaining[k + 1:]))
        new_states.sort(key=lambda st: -st[0])
        states = new_states[:beam]
    best_score, assign, _ = states[0]
    out = list(shots)
    used: dict[int, float] = {}
    for i in range(n):
        src = assign.get(i, out[i].source_index)
        length = out[i].duration
        if i in assign:
            room = max(0.0, source_durations[src] - length)
            offset = used.get(src, 0.0)
            offset = offset if offset <= room else 0.0
            out[i] = Shot(src, round(offset, 3), length)
        used[src] = out[i].source_offset + max(0.5, length)
    return out, round(best_score / max(1, n - 1), 4)


def reel_coherence(shots, dna: list[dict | None]) -> float | None:
    """Mean transition score of the final order (for the critic and for learning)."""
    if len(shots) < 2 or not any(dna):
        return None
    embs = {k: _emb(d) for k, d in enumerate(dna)}
    vals = [transition(dna[a.source_index], dna[b.source_index], embs.get(a.source_index),
                       embs.get(b.source_index))["total"] for a, b in zip(shots, shots[1:])
            if a.source_index != b.source_index]
    return round(sum(vals) / len(vals), 4) if vals else None


OUTLIER_GAP = 0.10  # mean transition this far below the median → the clip does not belong


def outliers(dna: list[dict | None], protected: set[int], keep_min: int) -> set[int]:
    """Owner, 28 Nov: "Die Bilder passen nur teilweise zusammen". Clips whose mean
    transition to all other clips is clearly below the median do not belong to this film
    and are left out — never protected ones (signature shots), never below keep_min clips."""
    idx = [i for i, d in enumerate(dna) if d]
    if len(idx) <= keep_min:
        return set()
    embs = {i: _emb(dna[i]) for i in idx}
    mean = {}
    for i in idx:
        vals = [transition(dna[i], dna[j], embs.get(i), embs.get(j))["total"] for j in idx if j != i]
        mean[i] = sum(vals) / len(vals) if vals else 0.5
    import statistics
    med = statistics.median(mean.values())
    out = set()
    for i in sorted(idx, key=lambda k: mean[k]):
        if len(dna) - len(out) <= keep_min:
            break
        if i not in protected and mean[i] < med - OUTLIER_GAP:
            out.add(i)
    return out
