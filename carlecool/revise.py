"""Owner-only review revisions; new video -> new Gmail -> new approval Issue.

Old approved bytes are never modified. No Instagram API calls are made here.
Whitelisted style feedback is stored for future proposals after successful email.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from email.utils import make_msgid

from .creative import (
    PROFILE_PATH, apply_commands, interpret_revision, load_profile,
    validate_profile,
)
from .main import process
from .review import (
    create_review, decode_issue_data, github_request, prepare_delivery, send_review_email,
)


def require_owner():
    # Workflow enforces the same condition at dispatch, but verify independently.
    if (not os.getenv("GITHUB_ACTIONS") == "true"
            or os.getenv("GITHUB_ACTOR") != os.getenv("GITHUB_REPOSITORY_OWNER")
            or not os.getenv("GITHUB_REPOSITORY_OWNER")):
        raise RuntimeError("Only the repository owner can request a Reel revision")


def revise(issue_number: int, command: str) -> str:
    require_owner()
    if not 0 < issue_number < 1_000_000_000:
        raise ValueError("Invalid review issue number")
    instructions = interpret_revision(command)
    issue = github_request("GET", f"issues/{issue_number}")
    if issue.get("state") != "open":
        raise ValueError("Review issue is already closed")
    labels = [item.get("name") for item in issue.get("labels", [])]
    if "carlecool-review" not in labels:
        raise ValueError("This is not a current CarleCool review issue")
    old = decode_issue_data(issue.get("body", ""))
    revision = int(old.get("revision_number", 0)) + 1
    if revision > 5:
        raise ValueError("Maximum five revisions per original proposal; use /reject")
    old_profile = old.get("creative_profile") or load_profile()
    profile = apply_commands(old_profile, instructions)
    profile["revision"] = revision
    profile = validate_profile(profile)
    # Temporarily remove approval label to invalidate /approve while rendering.
    inactive_labels = [label for label in labels if label != "carlecool-review"]
    github_request("PATCH", f"issues/{issue_number}",
                   json_body={"labels": inactive_labels})
    new_issue = None
    delivered = False
    try:
        # Reuse the identical track, but pick new clips and render with revised intent.
        process(publish=False, track_id=str(old["track_id"]), creative_profile=profile)
        metadata = json.loads(Path("output/reel_metadata.json").read_text(encoding="utf-8"))
        metadata = prepare_delivery(metadata, int(os.environ["GITHUB_RUN_ID"]),
                                    Path("output/reel_metadata.json"))
        message_id = make_msgid(domain="carlecool.invalid")
        new_issue = create_review(
            metadata, run_id=int(os.environ["GITHUB_RUN_ID"]),
            token=os.environ["GH_TOKEN"], repo=os.environ["GITHUB_REPOSITORY"],
            mail_message_id=message_id,
        )
        if not send_review_email(
            new_issue["html_url"], metadata, Path(metadata["output"]),
            message_id=message_id, run_id=int(os.environ["GITHUB_RUN_ID"]),
        ):
            raise RuntimeError("Revised Gmail preview could not be delivered")
        delivered = True
        github_request("PATCH", f"issues/{issue_number}",
                       json_body={"state": "closed"})
        github_request("POST", f"issues/{issue_number}/comments", json_body={
            "body": "🎬 Überarbeitung erstellt: " + new_issue["html_url"]
                    + "\nDie alte Freigabe wurde deaktiviert."
        })
    except Exception:
        if new_issue and not delivered:
            try:
                github_request("PATCH", f"issues/{new_issue['number']}",
                               json_body={"state": "closed"})
            except Exception:
                pass
        if not delivered:
            # Reopen the original approval for another attempt only if no new
            # Gmail original has been sent to the owner.
            try:
                github_request("PATCH", f"issues/{issue_number}",
                               json_body={"labels": labels})
            except Exception:
                pass
        raise

    # Revisions help avoid reused footage but do not count as a new daily song.
    try:
        from .history import record_preview_delivery
        record_preview_delivery(
            metadata, run_id=int(os.environ["GITHUB_RUN_ID"]), kind="revision",
            token=os.environ["GH_TOKEN"], repo=os.environ["GITHUB_REPOSITORY"],
        )
    except Exception as exc:
        # The private original was already sent and the new approval is valid.
        # Do not re-email or reactivate the old issue after a history failure.
        print("Warning: revised preview sent, but history was not stored:",
              type(exc).__name__)

    # "Feedback memory": learn explicit, interpreted choices for next Reels.
    # The profile file contains only public style weights, never secrets/media.
    profile["revision"] = 0
    # A style choice (/revise stil rubin) is remembered for THIS SONG (data/song-styles.json);
    # other songs keep following cover and music.
    from .creative import STYLE_COMMANDS
    from . import songstyle
    chosen = [STYLE_COMMANDS[c] for c in instructions if c in STYLE_COMMANDS]
    if chosen:
        songstyle.remember(str(old["track_id"]), chosen[-1])
        print(f"Style for this song remembered: {chosen[-1]}")
    profile["style"] = "auto"
    # Explicit owner revision after successful delivery is the only signal.
    from .quality_learning import PATH as LEARN_PATH, load as load_learning, observe
    updated_learning = observe(load_learning(), instructions)
    LEARN_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARN_PATH.write_text(json.dumps(updated_learning, indent=2) + "\n", encoding="utf-8")
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    try:
        subprocess.run(["git", "config", "user.name", "CarleCool Creative Bot"], check=True)
        subprocess.run(["git", "config", "user.email",
                        "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        to_add = [str(PROFILE_PATH), str(LEARN_PATH)]
        if songstyle.PATH.is_file():
            to_add.append(str(songstyle.PATH))
        subprocess.run(["git", "add", *to_add], check=True)
        changes = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if changes.returncode:
            subprocess.run(["git", "commit", "-m",
                            "creative: remember owner feedback for future Reels"], check=True)
            # Other commits (preview history) may have landed meanwhile.
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
            subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)
    except subprocess.SubprocessError:
        print("Warning: New review email succeeded, but style memory was not persisted")
    print("New reviewed revision email sent; approval:", new_issue["html_url"])
    return new_issue["html_url"]


def main():
    issue = int(os.environ["REVIEW_ISSUE"])
    instruction = os.environ.get("REVISE_COMMAND", "")
    revise(issue, instruction)


if __name__ == "__main__":
    main()
