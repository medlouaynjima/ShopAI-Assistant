"""
E-Commerce Support Agent - Configuration
"""
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database. Leave empty to use the existing SQLite database.
    database_url: str = ""
    redis_url: str = ""

    # LLM provider
    llm_provider: str = "groq"
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    temperature: float = 0.0
    llm_input_cost_per_1m_usd: float | None = None
    llm_output_cost_per_1m_usd: float | None = None

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8002
    admin_api_key: str = ""
    auth_secret_key: str = ""
    auth_session_hours: int = 12
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # Customer verification email (SMTP STARTTLS)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    smtp_use_tls: bool = True

    # Observability (optional)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL"),
    )
    langsmith_api_key: str = ""
    langsmith_project: str = "shopassist"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # Docker Compose also reads POSTGRES_PASSWORD / POSTGRES_PORT from this file.
    # They are infrastructure variables, not application settings.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
