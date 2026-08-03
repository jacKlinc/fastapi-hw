from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    postgres_user: str
    postgres_password: str
    postgres_port: int
    postgres_db: str
    postgres_host: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"

    redis_host: str = "localhost"
    redis_port: int = 6379
    # Toggled off to record the no_cache baseline, see scripts/benchmark/cache/
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    # Deliberately tight: a slow cache should be abandoned, not waited on
    cache_timeout_seconds: float = 0.25
    # Off while benchmarking, otherwise 5/minute stops the run dead
    rate_limit_enabled: bool = True


settings = Settings()
