from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    OPENAI_API_KEY: str
    WEBHOOK_BASE_URL: str = ""
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")


settings = Settings()
