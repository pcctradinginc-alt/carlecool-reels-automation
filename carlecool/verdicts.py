"""Owner verdicts from the review mail (27 Nov: "Button: Schlechter als das letzte Video …
diese Info direkt an das Repo zurückgeben, anstelle von: nicht veröffentlichen und löschen").

The mail's former "discard" button now reads "Schlechter als das letzte Video – nicht
veröffentlichen". It still uses the existing signed link and worker (choice "discard" →
`/reject`), so nothing about the approval security changes. The reject workflow closes
the issue as before AND records the comparative verdict here:

    data/owner-verdicts.json: {"verdicts": [{"issue": 82, "verdict": "worse_than_previous",
                                             "previous": 73, "at": "…"}]}

"previous" = the newest earlier review issue. These verdicts calibrate the critic and the
pipeline comparison (docs/validation.md); decisions.py still counts the Reel as discarded.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

PATH = Path("data/owner-verdicts.json")
VERDICTS = ("worse_than_previous",)


def load(path: Path = PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"verdicts": []}
    except (OSError, ValueError):
        return {"verdicts": []}


def add(data: dict, issue: int, verdict: str, previous: int | None) -> dict:
    if verdict not in VERDICTS:
        raise ValueError("unknown verdict")
    items = [v for v in data.get("verdicts") or [] if v.get("issue") != issue]
    items.append({"issue": int(issue), "verdict": verdict, "previous": previous,
                  "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return {"version": 1, "verdicts": sorted(items, key=lambda v: v["issue"])}


def previous_issue(issue: int, request=None) -> int | None:
    """Newest review issue created before this one."""
    if request is None:
        from .review import github_request as request
    items = request("GET", "issues?labels=carlecool-review&state=all&per_page=50&sort=created&direction=desc") or []
    earlier = [int(i["number"]) for i in items if "pull_request" not in i and int(i["number"]) < int(issue)]
    return max(earlier) if earlier else None


def main(argv: list[str]) -> int:
    """`python -m carlecool.verdicts worse <issue>` (approve-reel workflow, reject job)."""
    if len(argv) != 3 or argv[1] != "worse" or not argv[2].isdigit():
        print("usage: python -m carlecool.verdicts worse <issue>")
        return 2
    issue = int(argv[2])
    from .performance import commit_json
    from .review import github_request
    import base64
    try:
        item = github_request("GET", f"contents/{PATH.as_posix()}?ref=main")
        data = json.loads(base64.b64decode(item["content"]).decode("utf-8"))
    except Exception:
        data = load()
    data = add(data, issue, "worse_than_previous", previous_issue(issue))
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    if os.getenv("GITHUB_ACTIONS") == "true":
        commit_json(PATH, f"verdicts: #{issue} worse than the previous Reel [skip ci]")
    print(f"Verdict recorded: #{issue} worse than #{data['verdicts'][-1]['previous']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
