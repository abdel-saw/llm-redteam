"""Exceptions du client LLM interne (cf. `llm_client.py`)."""


class LLMError(Exception):
    """Classe de base pour toutes les erreurs du client LLM."""


class LLMUnavailableError(LLMError):
    """Plus aucun provider n'a pu répondre à la requête."""


class LLMRateLimitError(LLMError):
    """Le provider a retourné HTTP 429."""


class LLMTimeoutError(LLMError):
    """Le provider n'a pas répondu dans les délais."""
