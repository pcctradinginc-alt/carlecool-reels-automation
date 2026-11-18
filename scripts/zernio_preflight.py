"""Read-only health check for the two free Zernio social accounts."""
from __future__ import annotations
import os
from carlecool.zernio import Zernio


def main() -> None:
    key = os.getenv("ZERNIO_API_KEY", "")
    account_ids = {
        "instagram": os.getenv("ZERNIO_INSTAGRAM_ACCOUNT_ID", "").strip(),
        "tiktok": os.getenv("ZERNIO_TIKTOK_ACCOUNT_ID", "").strip(),
    }
    if not key or any(not value for value in account_ids.values()):
        raise RuntimeError("Set the ZERNIO_API_KEY and both ZERNIO_*_ACCOUNT_ID GitHub Secrets first")
    result = Zernio(key).verify_connections(account_ids)
    assert result == {"instagram": True, "tiktok": True}
    print("PASS: Both connected Zernio accounts verified; zero uploads, zero posts")


if __name__ == "__main__":
    main()
