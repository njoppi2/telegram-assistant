from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    GOOGLE_API_KEY: str = ""
    AUTH_PASSWORD: str = ""
    WEBHOOK_BASE_URL: str = ""
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
