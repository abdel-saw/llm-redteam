# Journal de bord — Red-Agent-S

Décisions techniques notables et incidents au cours du développement du
PFE (Ingénierie Informatique, FST Settat). Format : entrées datées en ordre
anti-chronologique.

---

## 2026-05-14 — Rebranding LLM-RT → Red-Agent-S (v0.2.0)

Le projet change de nom pour la soutenance et le packaging final :
**Red-Agent-S**, sous-titré *"Autonomous Red Teaming Agent for LLM
Applications"*. La référence S-class (manga / shōnen) reste implicite —
le sous-titre fait le travail d'explication pour un public extérieur.

Le rebranding cible précisément :

- Les éléments de marque visibles à l'utilisateur (header HTML, footer,
  titres de page, en-tête du rapport, badge de logo).
- Les métadonnées système (`settings.app_name`, `settings.app_tagline`,
  `FastAPI(title=..., description=..., version=...)`, frontmatter HF
  Space).
- Le journal et les benchmarks (références produit, pas les noms de
  branches/commits historiques).

Volontairement NON modifié :

- Le terme technique "LLM red teaming" reste partout — c'est une
  discipline, pas un nom de produit.
- Le nom de repo `llm-redteam` côté GitHub : changer de slug
  casserait les liens, le rapport LaTeX, les références dans les
  benchmarks. Le sous-domaine HF Space sera `red-agent-s` ; le repo
  GitHub reste tel quel pour conserver l'historique git.
- Les docstrings de fichiers internes qui parlent de "Red Teaming" sans
  référence directe au produit.

Bump version `0.1.0` → `0.2.0` dans `config.py` et exposée via le
endpoint `/healthz` ainsi que dans l'en-tête du rapport HTML.

---

## 2026-05-13 — Starlette strict sur HTTP 204 + retry 429 dans le client LLM

**Comportement Starlette strict sur `204 No Content`.** Le `DELETE
/api/targets/{id}` était écrit avec `status_code=204` mais sans
`response_class=Response` ; FastAPI tentait alors de sérialiser le
retour `None` en JSON `null`, ce que Starlette refuse à l'exécution
avec une `AssertionError("Status code 204 must not have a response
body")`. Le bug ne s'est pas vu en développement parce qu'il n'y avait
**aucun test d'intégration** sur cette route — un test unitaire qui
mock la couche route aurait laissé passer la divergence.

**Excellent exemple à mentionner dans le chapitre 4 (« leçons
apprises ») du rapport** : *les tests d'intégration HTTP attrapent des
classes entières de bugs que les tests unitaires ratent par
construction* — ici la spec HTTP (RFC 7231 §6.3.5) impose un body vide
sur 204, et seule la stack ASGI réelle (Starlette + httpx ASGITransport)
fait remonter la violation. Fix : `response_class=Response` + retour
explicite de `Response(status_code=204)` + ajout de
`backend/tests/test_targets_api.py`.

**Retry 429 dans `LLMClient`.** Sur les benchmarks précédents, ~3 %
des appels au safety classifier `gpt-oss-safeguard-20b` revenaient en
429 (rate limit Groq tier free). L'erreur était gracefully avalée par
le `Judge` (`flagged=False`) mais dégradait la qualité du scoring.
Ajout d'un retry léger : on parse `Retry-After`, on cap à 10 s, on
retry **une seule fois** sur le même provider, puis fallback comme
avant si toujours en échec. Log explicite du breakdown
`[provider=groq] 429 then 200 in 2543ms (retry delay 1000ms)` pour
l'audit. Refactor adjacent : extraction de `_call_with_retry()` autour
de `_call_provider()` qui reste atomique (un seul appel HTTP).

**Validation live** : scan 25 tentatives sur llama-3.1-8b-instant
(~75 appels LLM) → 2 « Rate limit hit on groq » loggés, 1 sauvé par
retry (1 s d'attente puis 200), 1 cap à 8 s puis fallback openrouter
(402 car clé invalide → flagged=False). Aucun attempt en erreur
finale, `robustness_score=64.0` calculé sans NULL.

Les JSON bruts des 2 derniers scans validés sont exportés dans
[`docs/benchmarks/`](./benchmarks/) avec un README résumant les
conditions de test et un comparatif 8B vs 70B par catégorie.

---

## 2026-05-13 — Migration du juge de sécurité

`meta-llama/llama-guard-4-12b` a été **déprécié par Groq le 10/02/2026**.
Symptôme observé sur le scan #2 : `robustness_score=None` car tous les
appels Llama Guard renvoyaient `400 Bad Request`, et le `Judge` avalait
silencieusement l'exception via le warning « guard pass failed ».

**Bascule vers `openai/gpt-oss-safeguard-20b`**, le remplaçant officiel.
Particularité : ce modèle est *policy-based* (bring-your-own-policy) au
lieu de *taxonomy-based* MLCommons. On lui fournit une policy
descriptive en langage naturel (sections Instructions / Definitions /
Criteria / Output) et il raisonne dessus ; la sortie est un JSON
`{flagged, category, rationale}`.

**Refactor découplé** plutôt que swap direct :

- Nouvelle abstraction `SafetyClassifier` (ABC) avec dataclass unifiée
  `SafetyClassification(flagged, categories, raw_output, confidence)`.
- Deux implémentations : `GPTOSSSafeguardClassifier` (défaut) et
  `LlamaGuardClassifier` (fallback MLCommons safe/unsafe Sx, garde
  `llama-guard-3-8b` accessible).
- Factory `get_safety_classifier(settings, llm_client)` qui choisit
  selon `guard_mode` (`policy` | `taxonomy`) avec override automatique
  si `guard_model` contient `"llama-guard"`.
- Policies par catégorie d'attaque dans `services/safety_policies.py`
  (anglais, 4 sections, alignées sur OWASP LLM Top 10).

**Conséquence pour le `Judge`** : la règle de combinaison s'est
simplifiée. Avant, on devait filtrer le flag Llama Guard sur un set
`GUARD_RELEVANT_CATEGORIES` (Jailbreak, SensitiveInfo, Misinformation)
parce que la taxonomie MLCommons n'était pas alignée par construction
sur la catégorie d'attaque. Avec une policy policy-based dédiée à la
catégorie, `flagged=True` est cohérent par construction → la règle
devient simplement « flagged + verdict != success → partial ».

**Piège rencontré** : `max_tokens=256` (valeur héritée de Llama Guard)
provoque un `400 json_validate_failed` côté Groq. `GPT-OSS-Safeguard`
émet une longue chain-of-thought dans le champ `reasoning` du message
*avant* de produire le JSON final dans `content` — il faut au moins
1024 tokens pour laisser la génération aboutir.

**Confirmation de la pertinence de l'architecture découplée prévue dès
la conception** : le `Judge` à deux étages (sécurité + sémantique) avec
le sémantique en JSON strict était déjà en place ; il a suffi
d'extraire l'étage sécurité derrière une interface pour absorber un
changement majeur de format sans toucher au reste du pipeline.

**Validation live** : 2 scans complets sur Groq (5 catégories × 2
attempts = 10 tentatives chacun), un sur `llama-3.1-8b-instant` et un
sur `llama-3.3-70b-versatile`. Les deux ont terminé avec
`status=completed` et un `robustness_score` non-nul. Sur 20 appels
classifier, 17 réussites + 3 échecs (rate limit 429, gérés
gracieusement → `flagged=False` par défaut). Aucun appel vers le
modèle déprécié dans les logs serveur.

**Tests** : 75 tests verts, 0 warning (10 nouveaux dans
`test_safety_classifier.py` couvrant les deux implémentations + la
factory ; `test_judge.py` refactoré avec injection de classifier,
7 tests au lieu de 6).

---
