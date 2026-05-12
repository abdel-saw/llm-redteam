from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration applicative chargée depuis l'environnement / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM providers ---
    groq_api_key: str = Field(default="", description="Clé API Groq.")
    openrouter_api_key: str = Field(default="", description="Clé API OpenRouter (fallback).")
    llm_provider: Literal["groq", "openrouter"] = Field(
        default="groq",
        description="Provider LLM actif au démarrage.",
    )

    # --- Modèles ---
    attacker_model: str = Field(default="llama-3.3-70b-versatile")
    judge_model: str = Field(default="llama-3.3-70b-versatile")
    guard_model: str = Field(default="meta-llama/llama-guard-4-12b")

    # --- Persistance ---
    database_url: str = Field(default="sqlite:///./redteam.db")

    # --- Environnement ---
    app_env: Literal["dev", "prod"] = Field(default="dev")

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton paresseux — évite de re-parser `.env` à chaque import."""
    return Settings()


settings = get_settings()
