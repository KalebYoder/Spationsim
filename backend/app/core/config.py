from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_days: int = 7
    environment: str = "development"

    model_config = {"env_file": ".env"}


settings = Settings()
