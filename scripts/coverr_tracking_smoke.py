"""One-clip Coverr Demo API download+tracking integration probe.

No video output in GitHub artifacts, no external posting, no private media.
"""
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
import requests

from carlecool.video import (
    download_video, record_coverr_download, search_coverr,
)


def main():
    api_key = os.getenv("COVERR_API_KEY", "")
    if not api_key:
        raise RuntimeError("COVERR_API_KEY is not configured")
    with requests.Session() as session:
        choices = search_coverr(
            api_key, "cinematic", set(), session=session,
            wanted=1, keywords=["skateboarding"])
        if len(choices) != 1:
            raise RuntimeError("Coverr returned no accessible free stock clip")
        with TemporaryDirectory(prefix="carlecool-coverr-") as directory:
            file = download_video(choices[0].url, Path(directory) / "test.mp4",
                                  session=session)
            if file.stat().st_size < 1024:
                raise RuntimeError("Coverr video was too small")
            record_coverr_download(choices[0].id, api_key, session=session)
            print("PASS: Coverr video downloaded + stats tracking acknowledged. "
                  "Clip discarded, no email or Instagram post.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # HTTPError messages may contain signed video URLs with keys: never print.
        print(f"Coverr tracking smoke failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
