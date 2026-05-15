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
    guard_model: str = Field(default="openai/gpt-oss-safeguard-20b")
    guard_mode: Literal["policy", "taxonomy"] = Field(
        default="policy",
        description=(
            "Format du juge de sécurité. 'policy' = bring-your-own-policy "
            "(GPT-OSS-Safeguard) ; 'taxonomy' = MLCommons safe/unsafe (Llama Guard)."
        ),
    )

    # --- Persistance ---
    # Chemin absolu par défaut : cohérent avec le Dockerfile (qui crée
    # /app/data avec chown 1000 avant USER user) et avec docker-compose
    # (volume monté sur /app/data). Évite le grand classique
    # `unable to open database file` quand l'utilisateur non-root ne
    # peut pas écrire dans CWD. En dev local, override via `.env`.
    database_url: str = Field(default="sqlite:////app/data/red-agent-s.db")
    reports_dir: str = Field(
        default="/app/reports",
        description="Dossier d'écriture des rapports HTML générés (un sous-dossier par scan).",
    )

    # --- Environnement ---
    app_env: Literal["dev", "prod"] = Field(default="dev")
    app_version: str = Field(default="0.2.0")
    app_name: str = Field(default="Red-Agent-S")
    app_tagline: str = Field(
        default="Autonomous Red Teaming Agent for LLM Applications"
    )

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton paresseux — évite de re-parser `.env` à chaque import."""
    return Settings()


settings = get_settings()
