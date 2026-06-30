from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    llm_provider: str = "openai"  # openai | openai_compatible | anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    redis_url: str = "redis://localhost:6379/0"
    use_redis: bool = True

    qdrant_path: str = "data/qdrant"
    use_qdrant: bool = True

    github_token: str = ""

    host: str = "0.0.0.0"
    port: int = 8000
    api_key: str = ""

    registry_db_path: str = "data/registry.db"
    tasks_db_path: str = "data/tasks.db"

    enabled_agents: str = ""
    enabled_tools: str = ""
    plugins_manifest: str = "plugins/manifest.yaml"

    max_concurrent_tasks: int = 3

    message_reliability: bool = True
    message_max_retries: int = 3
    message_retry_interval: int = 30
    message_retry_grace: int = 60
    clear_failed_outbox: bool = False
    assignment_max_retries: int = 1


settings = Settings()
