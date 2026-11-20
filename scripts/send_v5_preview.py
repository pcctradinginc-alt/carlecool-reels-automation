"""Send a private Creative v5 experiment without creating an approval issue.

This helper NEVER contacts Zernio, TikTok, Instagram or the GitHub write API.
It does not update the normal track rotation journal.
"""
from __future__ import annotations

from email.utils import make_msgid
import json
import os
from pathlib import Path

from carlecool.review import send_review_email


def main() -> None:
    if os.getenv("CARLECOOL_CREATIVE_V5") != "on":
        raise RuntimeError("This sender only accepts an explicit Creative v5 test")
    if os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("GITHUB_WORKFLOW") != (
        "CarleCool — Creative v5 FREE private preview"
    ):
        raise RuntimeError("Creative v5 mail must use the dedicated read-only workflow")
    metadata = json.loads(Path("output/reel_metadata.json").read_text(encoding="utf-8"))
    v5 = metadata.get("creative_v5") or {}
    signatures = v5.get("signatures") or {}
    if (v5.get("mode") != "manual_dry_run_only"
            or not all(x in signatures for x in ("woman", "skater"))):
        raise RuntimeError("Not a verified Creative v5 preview: no email sent")
    video = Path(metadata["output"])
    run_id = int(os.getenv("GITHUB_RUN_ID") or "0")
    if run_id <= 0:
        raise RuntimeError("Missing GitHub run identity")
    delivered = send_review_email("", metadata, video,
                                  message_id=make_msgid(domain="carlecool.invalid"),
                                  run_id=run_id)
    if not delivered:
        raise RuntimeError("Private Creative v5 email was not delivered")
    print("Creative v5 private preview delivered. No GitHub approval issue, "
          "no social publication, no posting status modified.")


if __name__ == "__main__":
    main()
