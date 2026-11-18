"""Safe preflight before user-authorized public TikTok test. No upload or posting."""
from __future__ import annotations
import os
from carlecool.zernio import Zernio


def check() -> None:
    required = ["ZERNIO_API_KEY", "ZERNIO_TIKTOK_ACCOUNT_ID",
                "ZERNIO_INSTAGRAM_ACCOUNT_ID"]
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError("Missing GitHub Secrets: " + ", ".join(missing))
    client = Zernio(os.environ["ZERNIO_API_KEY"])
    accounts = {"instagram": os.environ["ZERNIO_INSTAGRAM_ACCOUNT_ID"].strip(),
                "tiktok": os.environ["ZERNIO_TIKTOK_ACCOUNT_ID"].strip()}
    client.verify_connections(accounts)
    print("PASS: Both linked Zernio accounts found.")
    client.preflight_tiktok(accounts["tiktok"])
    print("PASS: TikTok canPost, valid token and PUBLIC_TO_EVERYONE permission.")

    # No uploading, no API POST, and never disclose secret *values*.
    missing_gates = [name for name in
                     ("PUBLISH_ENABLED", "ZERNIO_PUBLISH_ENABLED",
                      "COVERR_PUBLISH_PERMISSION_CONFIRMED")
                     if os.getenv(name, "").lower().strip() != "true"]
    if missing_gates:
        print("NOT READY: Publishing gates remain disabled: " +
              ", ".join(missing_gates))
        print("SAFE: No upload or social post was attempted.")
    else:
        print("PASS: Publishing gates configured. Still no upload or post.")
    return


if __name__ == "__main__":
    check()
