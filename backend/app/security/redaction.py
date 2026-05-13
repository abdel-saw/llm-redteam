"""Utilitaires de redaction de secrets (en-têtes HTTP et texte libre).

Utilisé à deux endroits :
- Sérialisation API : `Target.headers_preview` masque les valeurs d'auth
  avant d'être envoyées via TargetRead.
- Logs : `SecretRedactingFilter` (cf. `log_filter.py`) applique
  `redact_text()` à chaque LogRecord pour empêcher les clés de fuir
  dans la sortie de uvicorn / SQLAlchemy / httpx.

Si tu ajoutes un nouveau header sensible ou un nouveau format de clé
(Anthropic, Azure, Vertex...), c'est ici qu'il faut le déclarer.
"""

from __future__ import annotations

import re

REDACTED_PLACEHOLDER = "***REDACTED***"

# Noms comparés en case-insensitive. Toute valeur portée par un de ces
# en-têtes sera intégralement masquée à la sérialisation.
SENSITIVE_HEADER_NAMES: set[str] = {
    "authorization",
    "x-api-key",
    "api-key",
    "openai-api-key",
    "x-auth-token",
    "cookie",
    "x-goog-api-key",
    "x-anthropic-api-key",
    "proxy-authorization",
}

# Motifs reconnus dans du texte libre (logs, error messages, réponses
# de cible…). Chaque entrée est `(regex compilée, remplacement)`.
SECRET_KEY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)bearer\s+[\w\-\.]+"), f"Bearer {REDACTED_PLACEHOLDER}"),
    (re.compile(r"(?i)\bsk-[A-Za-z0-9]{20,}"), REDACTED_PLACEHOLDER),
    (re.compile(r"(?i)\bgsk_[A-Za-z0-9]{20,}"), REDACTED_PLACEHOLDER),
    (re.compile(r"(?i)\bsk-or-[A-Za-z0-9\-]{20,}"), REDACTED_PLACEHOLDER),  # OpenRouter
    (re.compile(r"(?i)\bsk-ant-[A-Za-z0-9\-_]{20,}"), REDACTED_PLACEHOLDER),  # Anthropic
]


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Copie le dict en masquant les valeurs des en-têtes sensibles.

    La comparaison des noms d'en-têtes est case-insensitive (RFC 7230),
    mais la casse d'origine est conservée dans le dict retourné.
    """
    sensitive = {name.lower() for name in SENSITIVE_HEADER_NAMES}
    out: dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() in sensitive:
            out[name] = REDACTED_PLACEHOLDER
        else:
            out[name] = value
    return out


def redact_text(text: str) -> str:
    """Applique tous les motifs de clé connus à `text`.

    Idempotent : une chaîne déjà redactée n'est plus modifiée.
    """
    if not text:
        return text
    out = text
    for pattern, replacement in SECRET_KEY_PATTERNS:
        out = pattern.sub(replacement, out)
    return out
