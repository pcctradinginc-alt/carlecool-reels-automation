"""One consistent public song name: "<artist> - <title>" (e.g. "carl e cool - nastro azzuro").

The artist spelling matches the streaming-service profile (Apple Music / Deezer:
"carl e cool"), so Instagram's audio label, captions and review mails all agree.
Override with the CARLECOOL_ARTIST_NAME repository variable if the name ever changes.
"""
from __future__ import annotations

import os
import re

DEFAULT_ARTIST = "carl e cool"
MAX_LABEL = 90  # Instagram audio names are short single-line labels


def artist_name() -> str:
    name = re.sub(r"\s+", " ", os.getenv("CARLECOOL_ARTIST_NAME", DEFAULT_ARTIST)).strip()
    return name or DEFAULT_ARTIST


def song_label(title: str) -> str:
    """'carl e cool - <title>' on one line, without control characters."""
    clean = re.sub(r"[\x00-\x1f\x7f]+", " ", str(title or ""))
    clean = re.sub(r"\s+", " ", clean).strip() or "untitled"
    label = f"{artist_name()} - {clean}"
    return label if len(label) <= MAX_LABEL else label[:MAX_LABEL - 1].rstrip() + "…"
