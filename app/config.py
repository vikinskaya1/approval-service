import os


class Settings:
    """Application settings, sourced from environment variables.

    Nothing secret lives here by default. DATABASE_URL may contain
    credentials in real deployments, but it is never logged or
    exposed in API responses.
    """

    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite:///./approval_service.db"
    )
    app_env: str = os.getenv("APP_ENV", "local")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
