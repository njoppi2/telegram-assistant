from src.router.profiles import load_profiles


def get_profile(user_id: str) -> dict | None:
    profiles = load_profiles()
    return profiles.get(str(user_id))
