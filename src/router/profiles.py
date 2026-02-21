from pathlib import Path

import yaml

PROFILES_DIR = Path(__file__).parent.parent.parent / "profiles"


def load_profiles() -> dict:
    profiles: dict[str, dict] = {}
    for profile_path in PROFILES_DIR.glob("*.yaml"):
        with profile_path.open("r", encoding="utf-8") as f:
            profile = yaml.safe_load(f) or {}

        telegram_user_id = str(profile.get("telegram_user_id", "")).strip()
        if telegram_user_id:
            profiles[telegram_user_id] = profile

    return profiles


def get_default_profile() -> dict:
    default_path = PROFILES_DIR / "default.yaml"
    with default_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
