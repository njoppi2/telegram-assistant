from pathlib import Path

import yaml

PROFILES_DIR = Path(__file__).parent.parent.parent / "profiles"


def _normalize_profile(profile: dict) -> dict:
    normalized = dict(profile)
    capabilities = normalized.get("capabilities") or []
    normalized["capabilities"] = [str(cap).strip() for cap in capabilities if str(cap).strip()]
    return normalized


def load_profiles() -> dict:
    profiles: dict[str, dict] = {}
    for profile_path in PROFILES_DIR.glob("*.yaml"):
        with profile_path.open("r", encoding="utf-8") as f:
            profile = _normalize_profile(yaml.safe_load(f) or {})

        telegram_user_id = str(profile.get("telegram_user_id", "")).strip()
        if telegram_user_id:
            profiles[telegram_user_id] = profile

    return profiles
