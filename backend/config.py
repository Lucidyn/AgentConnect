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
    api_key_salt: str = "agent-connect"
    multi_tenant: bool = True

    registry_db_path: str = "data/registry.db"
    tasks_db_path: str = "data/tasks.db"
    database_url: str = ""
    database_pool_size: int = 10
    api_replica_id: str = ""

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
    assignment_context_max_chars: int = 4000

    arxiv_timeout_seconds: float = 6.0
    queue_avg_task_seconds: int = 90

    llm_max_tokens_default: int = 2048
    llm_max_tokens_planner: int = 512
    llm_max_tokens_research: int = 1200
    llm_max_tokens_writer: int = 2000
    llm_max_tokens_analyst: int = 1200
    llm_max_tokens_coder: int = 800
    llm_max_tokens_reviewer: int = 300
    llm_temperature_default: float = 0.7
    llm_temperature_planner: float = 0.0
    llm_timeout_seconds: float = 120.0
    llm_streaming: bool = True
    llm_cost_input_per_1k: float = 0.00015
    llm_cost_output_per_1k: float = 0.0006
    saved_templates_dir: str = "data/saved_templates"

    # HTTP tool plugin (MCP-style fetch)
    http_tool_base_url: str = ""

    # TestRunner sandbox
    test_runner_pytest: bool = True
    test_runner_timeout: int = 30
    test_runner_sandbox: str = "subprocess"  # subprocess | docker | off
    test_runner_docker_image: str = "python:3.11-slim"

    # Surpass: model routing, budget, replan, marketplace
    llm_cheap_model: str = ""
    llm_premium_model: str = ""
    llm_research_model: str = ""
    llm_coder_model: str = ""
    tenant_budget_enabled: bool = False
    default_tenant_budget_usd: float = 0.0
    dynamic_replan_enabled: bool = True
    template_marketplace_dir: str = "data/marketplace"

    # OpenTelemetry (optional)
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "agent-connect"
    task_input_max_length: int = 8000
    api_max_list_limit: int = 100

    # Project workspace (local directory for coding / pytest)
    workspace_enabled: bool = True
    workspace_allowed_roots: str = ""  # comma-separated; empty = repo root + cwd
    workspace_create_if_missing: bool = True
    workspace_write_enabled: bool = True
    workspace_max_read_bytes: int = 200_000
    workspace_max_files_in_tree: int = 80
    workspace_max_tree_depth: int = 4
    workspace_max_snippet_files: int = 8

    # Negotiation
    negotiation_max_rounds: int = 2

    # Phase 3 distributed workers
    distributed_workers: bool = False
    worker_mode: bool = False
    worker_agent_name: str = ""
    worker_agents: str = ""
    worker_stream_key: str = "ac:assignments"
    worker_result_stream_key: str = "ac:results"
    worker_consumer_group: str = "ac-workers"
    worker_consumer_name: str = ""
    worker_poll_interval: float = 2.0

    # Production hardening
    production_mode: bool = False
    cors_origins: str = ""
    rate_limit_per_minute: int = 120


settings = Settings()
