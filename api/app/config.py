from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str = "dev-secret"
    litellm_model: str = "gemini/gemini-2.0-flash"
    gemini_api_key: str | None = None
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "wiki"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    single_user_email: str = "user@example.com"
    single_user_password: str = "changeme"
    # Hybrid search: call embedding API for the query vector. Set false to use FTS only.
    vector_search_enabled: bool = True
    marker_url: str = "http://marker:8001"
    marker_use_llm: bool = False
    marker_llm_service: str = "marker.services.gemini.GoogleGeminiService"
    marker_llm_model: str = ""
    marker_llm_api_key: str = ""
    vision_model: str = ""  # empty = vision disabled
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
