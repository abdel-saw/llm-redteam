"""Modèles ORM SQLAlchemy.

Volontairement vide pour le moment — les tables seront ajoutées lors de la
phase d'implémentation des entités (Target, Scan, Attempt, …). Le module
existe néanmoins pour que `database.init_db()` puisse l'importer en toute
sécurité dès l'amorçage.
"""

from .database import Base  # noqa: F401  (réexport pour usage futur)
