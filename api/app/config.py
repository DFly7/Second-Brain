from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    dev_auth_bypass: bool = False
    authentik_issuer: str = ""
    authentik_jwks_uri: str = ""
    authentik_client_id: str = ""
    authentik_token_url: str = ""
    authentik_redirect_uri: str = ""
    litellm_model: str = "gemini/gemini-2.0-flash"
    gemini_api_key: str | None = None
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "wiki"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    vector_search_enabled: bool = True
    # Conversion backend: "datalab" (managed API) or "local" (self-hosted marker container)
    marker_backend: str = "datalab"
    datalab_api_key: str = ""
    datalab_mode: str = "accurate"
    # Local marker settings — only used when MARKER_BACKEND=local
    marker_url: str = "http://marker:8001"
    marker_llm_service: str = "marker.services.gemini.GoogleGeminiService"
    marker_llm_model: str = ""
    marker_llm_api_key: str = ""
    openai_api_key: str = ""
    browser_agent_url: str = "http://browser-agent:8001"
    novnc_url: str = "/vnc/vnc.html"
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
