"""Exceptions du client LLM interne (cf. `llm_client.py`)."""


class LLMError(Exception):
    """Classe de base pour toutes les erreurs du client LLM."""


class LLMUnavailableError(LLMError):
    """Plus aucun provider n'a pu répondre à la requête."""


class LLMRateLimitError(LLMError):
    """Le provider a retourné HTTP 429.

    Porte la valeur du header `Retry-After` si présente (en secondes), pour
    que l'orchestrateur puisse temporiser intelligemment avant un retry.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMTimeoutError(LLMError):
    """Le provider n'a pas répondu dans les délais."""
