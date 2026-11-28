"""Hard resource budgets in one place (Phase 5, owner brief §15). Modules read their limits
from here; the workflow timeouts are chosen to fit them. No paid service is ever enabled."""
COVERR_PER_RUN = 35        # requests (Coverr allows ~50 / hour)
COVERR_PER_HOUR = 40       # documented ~50 / hour; 28 Nov: 429 already at ~26 + the run's own → plan conservatively
NARA_MONTHLY = 10_000      # National Archives API key limit
NARA_PER_RUN = 40
LIBRARY_FILES = 220        # Actions-cache footage library (~3 GB)
CLIP_FRAMES_PER_CLIP = 8   # OpenCLIP embeddings per clip window
DNA_SAMPLES = 24           # analysis frames per clip
RE_EDITS = 2               # critic-triggered re-edits per Reel
REEL_TIMEOUT_MIN = 90      # daily-reel job (incl. up to 60 min waiting for Coverr)
