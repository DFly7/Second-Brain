from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str = "dev-secret"
    litellm_model: str = "gemini/gemini-2.0-flash"
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "wiki"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    single_user_email: str = "user@example.com"
    single_user_password: str = "changeme"

    class Config:
        env_file = ".env"


settings = Settings()
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str = "dev-secret"
    gemini_api_key: str | None = None
    litellm_model: str = "gemini/gemini-2.0-flash"
    embedding_model: str = "gemini/text-embedding-004"
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "wiki"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    single_user_email: str = "user@example.com"
    single_user_password: str = "changeme"


settings = Settings()
