# LLM-RT — Agent autonome de Red Teaming pour applications LLM

Projet de Fin d'Études (Master RSI, FST Settat) — plateforme web d'audit de
sécurité automatisé pour applications basées sur des modèles de langage. Le
MVP couvre cinq familles d'attaques alignées sur l'OWASP LLM Top 10 (2025) :
prompt injection, fuite de prompt système, divulgation d'informations
sensibles, jailbreak et désinformation.

## Caractéristiques (MVP)

- Configuration d'une cible LLM : texte brut, JSON custom, OpenAI-compatible.
- Lancement d'un scan automatisé avec orchestration d'attaques par stratégies.
- Visualisation en temps réel via SSE (Server-Sent Events).
- Génération d'un rapport HTML autonome téléchargeable.
- Fallback automatique Groq → OpenRouter en cas d'erreur du provider.

## Stack technique

| Couche | Technologie |
| --- | --- |
| Backend | Python 3.11+, FastAPI, sse-starlette |
| Persistance | SQLite + SQLAlchemy 2.x |
| Frontend | HTMX + Tailwind (CDN) + Jinja2 |
| LLM provider | Groq (par défaut) avec fallback OpenRouter |
| Modèles | `llama-3.3-70b-versatile` (attaquant + juge), `meta-llama/llama-guard-4-12b` (garde) |

## Prérequis

- Python **3.11** ou supérieur
- Une clé API Groq (gratuite) — <https://console.groq.com>
- Optionnel : une clé API OpenRouter pour le fallback

## Installation

```bash
git clone <repo>
cd llm-redteam

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Editer .env et renseigner GROQ_API_KEY (et OPENROUTER_API_KEY si dispo)
```

## Lancement

```bash
uvicorn backend.app.main:app --reload
```

Le service est ensuite disponible sur <http://127.0.0.1:8000>.

## Structure du projet

```
backend/
  app/
    main.py            # Entree FastAPI
    config.py          # pydantic-settings + .env
    database.py        # Engine SQLAlchemy + session
    models.py          # Modeles ORM
    schemas.py         # DTO Pydantic
    routes/            # Endpoints HTTP
    services/          # Logique metier (adapters, LLM, moteur, juge, rapport)
    strategies/        # Strategies d'attaque (OWASP LLM Top 10)
    templates/         # Templates Jinja2 (UI + rapport)
    static/            # Assets (CSS, images)
  tests/
rapport_latex/         # Rapport academique du PFE
```

## Patrons de conception

- **Strategy** : chaque famille d'attaque hérite de `AttackStrategy`.
- **Adapter** : chaque type de cible LLM hérite de `TargetAdapter`.
- **Producer / Consumer** : `asyncio.Queue` pour le streaming SSE.

## Statut

MVP en cours de développement (timeline : 2 semaines). Le fine-tuning des
modèles attaquant/juge est explicitement hors périmètre du MVP et listé
comme perspective d'évolution.
