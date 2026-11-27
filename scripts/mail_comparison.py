"""Send the blind A/B comparison privately to the owner (no issue, no publication).

The A/B key is NOT in the mail; it stays in report.json until the owner has rated.
"""
from __future__ import annotations

from email.message import EmailMessage
import os
from pathlib import Path
import smtplib
import subprocess
import sys


def preview(src: Path, dest: Path) -> bytes:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", "scale=720:1280", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "24", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                    str(dest)], check=True)
    return dest.read_bytes()


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "compare")
    sender, password = os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    to = os.getenv("REVIEW_EMAIL") or sender
    msg = EmailMessage()
    msg["From"], msg["To"] = sender, to
    msg["Subject"] = "CarleCool | Blindvergleich A/B (alte vs. neue Pipeline)"
    msg.set_content("Zwei Fassungen desselben Songausschnitts mit demselben Material.\n"
                    "Welche wirkt filmischer und stimmiger – A oder B? Bitte kurz antworten (z. B. \"B, weil …\").\n"
                    "Welche Fassung alt oder neu ist, steht erst nach deiner Bewertung im Bericht.\n\n"
                    + (out / "report.md").read_text(encoding="utf-8").split("| critic score")[0].split("\n", 1)[0])
    for label in ("A", "B"):
        msg.add_attachment(preview(out / f"blind_{label}.mp4", out / f"mail_{label}.mp4"),
                           maintype="video", subtype="mp4", filename=f"CarleCool-{label}.mp4")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    print("Blind comparison mailed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
