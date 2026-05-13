"""Filtre de logging qui masque les secrets dans tout LogRecord.

Installé sur le root logger au démarrage. Le filtre mute à la fois
`record.msg` (chaîne potentiellement contenant un secret via f-string)
et `record.args` (placeholders %s/%d résolus par le formatter).
"""

from __future__ import annotations

import logging

from .redaction import redact_text


class SecretRedactingFilter(logging.Filter):
    """Réécrit les LogRecord pour effacer toute clé API ou Bearer token.

    Stratégie : on formate le message via `record.getMessage()` (qui interpole
    `args` dans `msg`), on redacte la chaîne finale, puis on remplace `msg`
    et vide `args` pour que les handlers n'essaient pas de re-formater. Cela
    couvre les args imbriqués (typiquement SQLAlchemy qui logue des tuples
    de paramètres SQL contenant des `headers_json` en clair).
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - API logging
        try:
            formatted = record.getMessage()
        except Exception:  # noqa: BLE001 - logging ne doit jamais lever
            return True

        redacted = redact_text(formatted)
        if redacted != formatted:
            record.msg = redacted
            record.args = ()
        else:
            # Pas de secret : on ne touche pas au record (évite de payer un
            # str() sur tous les args pour rien).
            pass
        return True


def install_redacting_filter() -> SecretRedactingFilter:
    """Attache le filtre au root + à TOUS les loggers déjà créés + leurs handlers.

    Pourquoi itérer tous les loggers : certaines libs (SQLAlchemy avec
    `echo=True`, uvicorn) attachent leur propre StreamHandler à leur logger
    plutôt que de propager vers root. Sans couverture explicite, ces
    handlers ré-émettent le message brut (avec ses secrets) avant que le
    filtre root n'ait l'occasion de tourner.
    """
    flt = SecretRedactingFilter()
    _attach_to_logger(logging.getLogger(), flt)  # root
    for name in list(logging.Logger.manager.loggerDict.keys()):
        logger = logging.getLogger(name)
        if not isinstance(logger, logging.Logger):
            continue  # PlaceHolder entries dans la manager dict
        _attach_to_logger(logger, flt)
    return flt


def _attach_to_logger(logger: logging.Logger, flt: SecretRedactingFilter) -> None:
    if flt not in logger.filters:
        logger.addFilter(flt)
    for handler in logger.handlers:
        if flt not in handler.filters:
            handler.addFilter(flt)
