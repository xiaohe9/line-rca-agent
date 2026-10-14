"""Configuration. The only place in the codebase that reads the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LRC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = "dev"
    #: When true the API must run with no API key and no network.
    demo_mode: bool = True

    cors_origins: str = "http://localhost:5173"

    # --- LLM -----------------------------------------------------------------
    #: fake | deepseek | openai_compat | ollama
    llm_provider: str = "fake"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_timeout_seconds: float = 60.0
    # Deliberately unprefixed: it is a shared vendor credential, not an app knob.
    deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")

    # --- agent ---------------------------------------------------------------
    agent_max_steps: int = 12
    #: native | langgraph
    agent_orchestrator: str = "native"
    agent_confidence_threshold: float = 0.6

    # --- observability -------------------------------------------------------
    #: stdout | null | langfuse
    trace_sink: str = "stdout"

    # --- data ----------------------------------------------------------------
    database_url: str = ""
    mqtt_url: str = ""
    secom_path: str = "eval/datasets/secom"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
