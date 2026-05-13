# Captures d'écran

Trois captures du frontend LLM-RT, générées par `scripts/take_screenshots.py`
via Chrome headless contre un scan réel sur Groq llama-3.1-8b-instant.

| Fichier | Page | Description |
| --- | --- | --- |
| `01_accueil.png` | `GET /` | Formulaire de configuration de cible + paramétrage du scan. L'étape 2 est verrouillée tant que la cible n'est pas créée et le consentement coché. |
| `02_scan_live.png` | `GET /scans/{id}/live` | Vue temps réel : progress bar, compteurs, breakdown par catégorie, feed des tentatives avec verdicts et severities. La capture a été prise après la complétion du scan (le 8B est rapide, ~12s) ; le même rendu s'applique en cours d'exécution avec moins de cartes visibles. |
| `03_history.png` | `GET /history` | Historique tabulaire des scans avec statut, score et lien de détail. |

## Reproduire les captures

```powershell
# 1. Lancer le serveur
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# 2. Dans un autre terminal
python scripts/take_screenshots.py
```

Le script lance un vrai scan (3 catégories × 2 tentatives) contre Groq —
il faut donc une `GROQ_API_KEY` valide dans `.env`.
