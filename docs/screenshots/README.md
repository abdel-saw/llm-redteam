# Captures d'écran

Six captures du frontend Red-Agent-S, générées par
`scripts/regenerate_screenshots.py` via Chrome headless contre un scan
réel sur Groq llama-3.1-8b-instant et la cible démo `InternalLegalBot`.

| Fichier | Page | Description |
| --- | --- | --- |
| `01_accueil.png` | `GET /` | Formulaire de configuration de cible + paramétrage du scan. L'étape 2 est verrouillée tant que la cible n'est pas créée et le consentement coché. |
| `02_scan_live.png` | `GET /scans/{id}/live` | Vue temps réel : progress bar, compteurs, breakdown par catégorie, feed des tentatives avec verdicts et severities. |
| `03_history.png` | `GET /history` | Historique tabulaire des scans avec statut, score et lien de détail. |
| `04_rapport_overview.png` | `GET /scans/{id}/report` | En-tête + synthèse exécutive + heat map du rapport (sections repliées). |
| `05_rapport_categories_open.png` | (rapport, `<details>` ouverts) | Section *OWASP Category Breakdown* avec toutes les catégories dépliées : description, stats, top-3 attaques sévères, mitigations. |
| `06_rapport_all_attempts_open.png` | (rapport, `<details>` ouverts) | Section *All attempts* dépliée avec les filtres (category / verdict / severity / search) et la table complète. |

## Reproduire les captures

```powershell
# 1. Lancer Red-Agent-S
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# 2. Lancer la cible démo InternalLegalBot
python -m scripts.demo_target.run

# 3. Dans un troisième terminal
python scripts/regenerate_screenshots.py
```

Le script :
1. Lance un scan court (3 catégories × 2 attempts) pour `01–03`.
2. Régénère le rapport du scan le plus récent (ou #16 si présent) pour `04–06`.
3. Pour `05` et `06`, télécharge le HTML, injecte un snippet qui ouvre
   tous les `<details>`, écrit dans un fichier temporaire, et capture
   la version dépliée.

Nécessite une `GROQ_API_KEY` valide dans `.env`.
