-- A single reviewed issue may be confirmed or discarded only once.
-- Atomic INSERT OR IGNORE prevents links for competing targets being used.
CREATE TABLE IF NOT EXISTS used_approvals (
  issue INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  action TEXT NOT NULL CHECK(action IN ('instagram','tiktok','both','discard')),
  created_at INTEGER NOT NULL
);
