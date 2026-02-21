from src.router.profiles import get_default_profile, load_profiles


def get_profile(user_id: str) -> dict:
    profiles = load_profiles()
    return profiles.get(str(user_id), get_default_profile())
