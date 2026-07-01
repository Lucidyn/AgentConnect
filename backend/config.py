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
    loop_max_iterations: int = 3

    # Performance / fast pipeline
    fast_mode: bool = False
    fast_skip_planner_llm: bool = False
    fast_skip_research: bool = True
    fast_skip_test_runner: bool = True
    assignment_context_max_chars: int = 2000

    llm_max_tokens_default: int = 1024
    llm_max_tokens_planner: int = 512
    llm_max_tokens_research: int = 400
    llm_max_tokens_coder: int = 800
    llm_max_tokens_reviewer: int = 300
    llm_temperature_default: float = 0.7
    llm_temperature_planner: float = 0.0
    llm_timeout_seconds: float = 120.0

    # API limits
    task_input_max_length: int = 8000
    api_max_list_limit: int = 100

    # Negotiation
    negotiation_max_rounds: int = 2

    # Phase 3 worker scaffold
    worker_mode: bool = False
    worker_stream_key: str = "ac:assignments"
    worker_result_stream_key: str = "ac:results"
    worker_poll_interval: float = 2.0


settings = Settings()
