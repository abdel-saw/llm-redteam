# Journal de bord — LLM-RT

Décisions techniques notables et incidents au cours du développement du
PFE (Master RSI, FST Settat). Format : entrées datées en ordre
anti-chronologique.

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
