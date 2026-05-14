---
title: Red-Agent-S
emoji: 🛡️
colorFrom: red
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Autonomous Red Teaming Agent for LLM Applications
---

# Red-Agent-S

*Autonomous Red Teaming Agent for LLM Applications*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![OWASP LLM Top 10](https://img.shields.io/badge/OWASP-LLM%20Top%2010%20aligned-c8102e.svg)](https://genai.owasp.org/llm-top-10/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#licence)
[![PFE](https://img.shields.io/badge/PFE-Master%20RSI%20%C2%B7%20FST%20Settat-0a1929.svg)](#auteur--cr%C3%A9dits)

Soumettez un endpoint LLM, et Red-Agent-S exécute une **campagne autonome
de Red Teaming** alignée sur l'OWASP LLM Top 10. Un modèle juge évalue
chaque tentative, et un **rapport HTML autonome** est généré
automatiquement à la fin du scan — partageable hors-ligne, prêt pour
audit ou pour intégration en CI.

---

## Captures

| | |
|---|---|
| ![Configuration de la cible](docs/screenshots/01_accueil.png) | ![Scan temps réel](docs/screenshots/02_scan_live.png) |
| *Configuration de la cible — 2 étapes verrouillées par consentement* | *Scan en direct — Server-Sent Events, breakdown par catégorie* |

![Rapport HTML — synthèse exécutive](docs/screenshots/04_rapport_overview.png)
*Rapport HTML standalone — synthèse exécutive, score de robustesse et heat map OWASP*

---

## Caractéristiques

- **3 types de cibles** : texte brut, JSON personnalisé (template + JSONPath), endpoint OpenAI-compatible.
- **5 catégories d'attaques** alignées OWASP LLM Top 10 — LLM01 (Prompt Injection), LLM02 (Sensitive Information Disclosure), LLM07 (System Prompt Leakage), LLM09 (Misinformation), et Jailbreak / Safety Bypass.
- **Juge à deux niveaux** : passe sémantique (LLM-as-judge, sortie JSON stricte) + classifieur de sécurité policy-based (`openai/gpt-oss-safeguard-20b`), avec fallback Llama Guard 3 sélectionnable.
- **Flux temps réel** via Server-Sent Events : progression, verdicts, severities, latence par tentative — UI HTMX réactive.
- **Rapport HTML standalone** : CSS + JS inlinés, aucune ressource réseau externe, ouvrable hors-ligne en double-clic. Score de robustesse, verdict global, heat map par catégorie, top-3 attaques sévères, mitigations.
- **Fallback automatique multi-provider** : Groq par défaut, OpenRouter en secours en cas d'indisponibilité.
- **Résilience HTTP 429** : retry unique avec respect du header `Retry-After` (capé à 10 s), puis fallback provider.
- **Redaction systématique des secrets** : `Authorization`, `Bearer …`, `gsk_*`, `sk-*`, `sk-or-*`, `sk-ant-*` — appliquée aux logs, à l'API et au rapport.
- **Cible de démo intégrée** (`InternalLegalBot`) : application LLM volontairement vulnérable pour démonstrations de bout en bout.

---

## Quick Start

### Option A — Docker (recommandé)

```bash
git clone https://github.com/abdel-saw/llm-redteam.git
cd llm-redteam
cp .env.example .env       # renseigner GROQ_API_KEY
docker compose up --build
```

Red-Agent-S est ensuite disponible sur <http://localhost:8000>.
La cible de démo `InternalLegalBot` répond sur <http://localhost:8765>.

### Option B — Python local

```bash
git clone https://github.com/abdel-saw/llm-redteam.git
cd llm-redteam

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env       # renseigner GROQ_API_KEY

uvicorn backend.app.main:app --reload
```

### Option C — Démo en ligne

Une instance publique tourne sur Hugging Face Space :
**`https://huggingface.co/spaces/abdel-saw/red-agent-s`** *(lien actif
une fois le déploiement terminé — cf. `HF_SPACE_DEPLOY.md`)*.

> Le free tier HF Space met le Space en pause après 48 h d'inactivité.
> Le premier visiteur après une pause peut attendre 30–60 s pour le
> cold-start. Pour une démo lors d'une soutenance : pinger le Space
> 1 h avant pour le réveiller.

---

## Architecture

```
┌────────────┐     SSE     ┌──────────────┐    HTTP    ┌────────────┐
│  Browser   │ ◀─────────  │ FastAPI      │ ─────────▶ │ LLM cible  │
│  (HTMX)    │             │ Attack Engine│            │ (json /    │
└────────────┘             └──────┬───────┘            │  openai /  │
                                  │                    │  text)     │
                                  ▼                    └────────────┘
              ┌─────────┬─────────┴─────────┬─────────┐
              ▼         ▼                   ▼         ▼
       ┌──────────┐ ┌─────────────────┐ ┌──────┐ ┌──────────┐
       │ Attacker │ │ Judge           │ │ SSE  │ │ Report   │
       │ (Groq)   │ │ • Semantic LLM  │ │ Bus  │ │ HTML     │
       │          │ │ • Safety Class. │ │      │ │ generator│
       └──────────┘ └─────────────────┘ └──────┘ └──────────┘
```

**Patrons de conception** :

- *Strategy* — chaque famille d'attaque hérite de `AttackStrategy`, le moteur les itère sans condition spéciale.
- *Adapter* — chaque type de cible (`text`, `json_custom`, `openai_compatible`) hérite de `TargetAdapter`.
- *Producer / Consumer* — `asyncio.Queue` par abonné SSE, avec buffer de replay pour les clients qui rouvrent l'onglet.
- *Abstract Factory* — `get_safety_classifier(settings, client)` choisit entre `GPTOSSSafeguardClassifier` (policy-based) et `LlamaGuardClassifier` (taxonomy MLCommons).

---

## Stack technique

| Couche | Technologie |
|---|---|
| Backend | Python 3.11+, FastAPI 0.115, sse-starlette 2.1, httpx 0.27 |
| Persistance | SQLite + SQLAlchemy 2.0 |
| Frontend | HTMX 2.0 + Tailwind (CDN) + Jinja2 |
| LLM providers | Groq (défaut), OpenRouter (fallback) |
| Modèles internes | `llama-3.3-70b-versatile` (attaquant + juge), `openai/gpt-oss-safeguard-20b` (safety classifier policy-based) |
| Tests | pytest 8.3, pytest-asyncio 0.24, respx 0.21 |
| Conteneurisation | Docker multi-stage, docker-compose, déploiement Hugging Face Space |

---

## Catégories d'attaque

| Code | Catégorie | Description courte |
|---|---|---|
| LLM01 | **Prompt Injection** | L'attaquant manipule le prompt utilisateur pour que ses instructions soient exécutées par le modèle au lieu de la tâche prévue. |
| LLM02 | **Sensitive Information Disclosure** | Le modèle émet des données sensibles (clés, PII, secrets internes, extraits de training data) en réponse à des requêtes ciblées. |
| LLM07 | **System Prompt Leakage** | Le modèle est amené à révéler son prompt système, ses règles cachées ou ses garde-fous internes. |
| LLM09 | **Misinformation** | Le modèle produit avec assurance des informations factuellement incorrectes (citations inventées, faits fabriqués). |
| —     | **Jailbreak / Safety Bypass** | L'alignement de sécurité est contourné pour produire du contenu que le modèle refuserait normalement. |

Chaque catégorie dispose d'une **stratégie hybride** : templates statiques (5–10 prompts curated, sans contenu réellement dangereux) puis génération adaptative par le LLM attaquant si `max_attempts_per_category` dépasse la taille du pool statique.

---

## Configuration

Variables d'environnement (cf. `.env.example`) :

| Variable | Défaut | Description |
|---|---|---|
| `GROQ_API_KEY` | *(vide)* | Clé API Groq, obligatoire pour le provider par défaut. |
| `OPENROUTER_API_KEY` | *(vide)* | Optionnel, utilisé en fallback si Groq échoue. |
| `LLM_PROVIDER` | `groq` | `groq` ou `openrouter` — provider primaire au démarrage. |
| `ATTACKER_MODEL` | `llama-3.3-70b-versatile` | Modèle qui génère les prompts d'attaque adaptatifs. |
| `JUDGE_MODEL` | `llama-3.3-70b-versatile` | Modèle qui rend le verdict sémantique (JSON strict). |
| `GUARD_MODEL` | `openai/gpt-oss-safeguard-20b` | Classifieur de sécurité (étage *guard*). |
| `GUARD_MODE` | `policy` | `policy` (GPT-OSS-Safeguard, bring-your-own-policy) ou `taxonomy` (Llama Guard, safe/unsafe Sx). |
| `DATABASE_URL` | `sqlite:///./redteam.db` | URL SQLAlchemy. |
| `REPORTS_DIR` | `./reports` | Dossier de sortie des rapports HTML. |
| `APP_ENV` | `dev` | `dev` ou `prod` — affecte le niveau de log et l'auto-reload. |

---

## Tests

```bash
pytest -v --cache-clear
```

| Suite | Tests | Couvre |
|---|---:|---|
| `test_adapters.py` | 12 | Adapters texte / json_custom / openai_compatible |
| `test_attack_engine.py` | 4 | Orchestration scan, calcul du score, gestion erreurs |
| `test_judge.py` | 7 | Pipeline juge sémantique + safety classifier (mocks) |
| `test_safety_classifier.py` | 10 | GPT-OSS-Safeguard + Llama Guard + factory |
| `test_prompt_injection_strategy.py` | 4 | Stratégie hybride statique → adaptative |
| `test_strategies.py` | 13 | Toutes les stratégies OWASP + safety des templates |
| `test_redaction.py` | 16 | Redaction headers + texte + filtre de logs |
| `test_llm_client.py` | 6 | Retry 429 + Retry-After + cap + fallback |
| `test_sse.py` | 7 | Bus d'événements + endpoint SSE + replay |
| `test_targets_api.py` | 2 | DELETE 204 strict (intégration ASGI) |
| `test_report.py` | 11 | Génération HTML autonome + redaction + idempotence + XSS |
| **Total** | **94** | |

Les tests d'intégration utilisent `httpx.ASGITransport` pour exercer la stack FastAPI/Starlette complète sans réseau. Les appels LLM sont mockés via `respx`.

---

## Limitations actuelles

- **MVP non destiné à un usage prod multi-tenant**. Single-user, pas d'authentification, pas de quotas par utilisateur.
- **Dépendance API externe** : Groq (et OpenRouter en fallback) — quotas et tarifs s'appliquent. Le free tier Groq plafonne à 6 000–12 000 tokens/min sur les modèles utilisés.
- **Verdicts du juge automatiques** : il s'agit d'estimations LLM, à vérifier humainement avant action sur un système en production. Faux positifs et négatifs possibles, surtout en catégorie *misinformation*.
- **Hardware-bound** : pas de fine-tuning local prévu dans le MVP — l'attaquant et le juge utilisent des modèles pré-entraînés via API distante.
- **Hugging Face Space free tier** : la base SQLite est éphémère (effacée au restart du Space). Acceptable pour démonstrations, pas pour des audits suivis.

---

## Roadmap

- Fine-tuning du modèle attaquant sur HarmBench / JailbreakBench.
- Fine-tuning du modèle juge pour réduire les faux positifs (notamment misinformation).
- Support des attaques **multi-tours** et **indirectes** (poisonée via RAG).
- **Comparaison historique** entre scans (régression de sécurité sur un même endpoint).
- **Mode CI/CD** : lancement en pipeline avec seuil de robustesse configurable, sortie JSON pour intégration GitOps.
- Plus d'adapters de cibles : Anthropic Messages API natif, Vertex AI, Bedrock.
- Stockage persistant côté Space (option payante HF).

---

## Disclaimer éthique

Red-Agent-S est un outil destiné à **l'évaluation autorisée de systèmes
que vous possédez ou avez l'autorisation explicite de tester**. L'usage
contre des systèmes tiers sans autorisation peut être illégal selon
votre juridiction (RGPD, fraude informatique, violation des conditions
d'utilisation).

Les templates d'attaque embarqués couvrent les catégories OWASP LLM
Top 10 et restent **scopés à du contenu *borderline-but-evaluative***.
Aucune instruction véritablement dangereuse (synthèse d'armes, CBRN,
exploitation d'enfants…) n'est émise par l'attaquant.

---

## Auteur / Crédits

Réalisé dans le cadre d'un **Projet de Fin d'Études** du Master
*Sciences et Techniques en Réseaux et Systèmes Informatiques* à la
**FST Settat — Université Hassan 1er** (Maroc), promotion 2025/2026.

- **Auteur** : Abdelhakim Sawadogo — [abdelsawadogo51@gmail.com](mailto:abdelsawadogo51@gmail.com)
- **Encadrant académique** : *(à compléter)*

Outils internes : le développement a été assisté par
[Claude Code](https://www.claude.com/product/claude-code) (Anthropic).

---

## Licence

[MIT](LICENSE) © 2026 Abdelhakim Sawadogo.

---

> *« Une attaque qu'on ne sait pas reproduire n'est pas un audit. »*
