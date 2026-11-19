import os
from dataclasses import dataclass


def flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    profile_url: str = os.getenv("SOUNDCLOUD_PROFILE_URL", "https://soundcloud.com/carlecool")
    reel_seconds: int = int(os.getenv("REEL_SECONDS", "15"))  # MAXIMUM; bar-aligned 8–15 s
    cooldown_days: int = int(os.getenv("POST_COOLDOWN_DAYS", "19"))
    coverr_key: str = os.getenv("COVERR_API_KEY", "")
    sc_client_id: str = os.getenv("SOUNDCLOUD_CLIENT_ID", "")
    sc_client_secret: str = os.getenv("SOUNDCLOUD_CLIENT_SECRET", "")
    ig_user_id: str = os.getenv("IG_USER_ID", "")
    ig_access_token: str = os.getenv("IG_ACCESS_TOKEN", "")
    graph_version: str = os.getenv("GRAPH_API_VERSION", "v27.0")
    publish_enabled: bool = flag("PUBLISH_ENABLED")
    coverr_permission_confirmed: bool = flag("COVERR_PUBLISH_PERMISSION_CONFIRMED")

    def validate(self) -> None:
        if self.reel_seconds < 8 or self.reel_seconds > 40:
            raise ValueError("REEL_SECONDS must be between 8 and 40")
        if self.cooldown_days < 0:
            raise ValueError("POST_COOLDOWN_DAYS must be >= 0")
        if not self.graph_version.startswith("v") or not self.graph_version[1:].replace(".", "").isdigit():
            raise ValueError("GRAPH_API_VERSION must look like v24.0")
