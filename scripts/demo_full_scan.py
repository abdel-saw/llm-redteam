"""Demo end-to-end : POST /targets -> /test -> /scans -> poll -> resultat final.

Lit GROQ_API_KEY dans .env. Imprime les requetes equivalentes en curl avant
chaque appel, puis la reponse. Ne logge jamais la cle.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
POLL_TIMEOUT_S = 240.0
POLL_INTERVAL_S = 3.0

SCAN_CATEGORIES = [
    "prompt_injection",
    "jailbreak",
    "system_prompt_leak",
    "sensitive_info_disclosure",
    "misinformation",
]
MAX_ATTEMPTS_PER_CATEGORY = 3


def load_env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return None


def redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:4] + "..." + value[-4:]


def _redact_body(body: dict) -> dict:
    out = dict(body)
    if isinstance(out.get("headers"), dict):
        hh = dict(out["headers"])
        for k, v in hh.items():
            if k.lower() == "authorization":
                tail = v.split()[-1] if v else ""
                hh[k] = "Bearer " + redact(tail)
        out["headers"] = hh
    return out


def print_step(title: str, method: str, path: str, body: dict | None = None) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(f"-> {method} {BASE_URL}{path}")
    if body is not None:
        safe = _redact_body(body)
        print("-- body --")
        print(json.dumps(safe, indent=2, ensure_ascii=False))


def print_resp(resp: httpx.Response, *, max_chars: int = 4000) -> None:
    print(f"<- HTTP {resp.status_code}")
    try:
        payload = resp.json()
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    except ValueError:
        text = resp.text
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [tronque, {len(text)} chars au total]"
    print(text)


def main() -> int:
    api_key = load_env_value(ENV_PATH, "GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY introuvable dans .env", file=sys.stderr)
        return 1
    print(f"GROQ_API_KEY chargee: {redact(api_key)}")

    create_target_body = {
        "name": "Groq Llama 3.1 8B (cible de demo)",
        "target_type": "openai_compatible",
        "endpoint_url": "https://api.groq.com/openai/v1",
        "headers": {"Authorization": f"Bearer {api_key}"},
        "model_name": "llama-3.1-8b-instant",
    }

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        # 1) Creer la cible
        print_step("STEP 1 — Creer la cible Groq", "POST", "/api/targets", create_target_body)
        r1 = client.post("/api/targets", json=create_target_body)
        print_resp(r1)
        if r1.status_code >= 300:
            return 2
        target_id = r1.json()["id"]

        # 2) Tester la connexion
        print_step(f"STEP 2 — Tester la connexion", "POST", f"/api/targets/{target_id}/test", {})
        r2 = client.post(f"/api/targets/{target_id}/test", json={})
        print_resp(r2)
        if r2.status_code >= 300 or not r2.json().get("ok"):
            print("\nERROR: test de connexion echoue, on n'enchaine pas sur le scan.")
            return 3

        # 3) Creer un scan multi-categories
        scan_body = {
            "target_id": target_id,
            "selected_categories": SCAN_CATEGORIES,
            "max_attempts_per_category": MAX_ATTEMPTS_PER_CATEGORY,
        }
        print_step("STEP 3 — Creer un scan", "POST", "/api/scans", scan_body)
        r3 = client.post("/api/scans", json=scan_body)
        print_resp(r3)
        if r3.status_code >= 300:
            return 4
        scan_id = r3.json()["id"]

        # 4) Poll jusqu'a completion
        print(f"\n{'=' * 70}\nSTEP 4 — Polling GET /api/scans/{scan_id} jusqu'a completion\n{'=' * 70}")
        deadline = time.monotonic() + POLL_TIMEOUT_S
        final = None
        while time.monotonic() < deadline:
            r4 = client.get(f"/api/scans/{scan_id}")
            data = r4.json()
            status = data.get("status")
            print(
                f"  t+{int(POLL_TIMEOUT_S - (deadline - time.monotonic())):>3}s "
                f"status={status} attempts={data.get('total_attempts')} "
                f"success={data.get('successful_attacks')}"
            )
            if status in ("completed", "failed", "aborted"):
                final = data
                break
            time.sleep(POLL_INTERVAL_S)

        if final is None:
            print("\nERROR: timeout, scan toujours en cours.")
            return 5

        # 5) Resume du scan + apercu des tentatives
        print(f"\n{'=' * 70}\nSTEP 5 — Resultat final du scan\n{'=' * 70}")
        print(f"status            = {final['status']}")
        print(f"total_attempts    = {final['total_attempts']}")
        print(f"successful_attacks= {final['successful_attacks']}")
        print(f"robustness_score  = {final.get('robustness_score')}")
        attempts = final.get("attempts", [])

        # Breakdown par categorie
        by_cat: dict[str, dict[str, int]] = {}
        for a in attempts:
            cat = a.get("category", "?")
            buckets = by_cat.setdefault(cat, {"success": 0, "failure": 0, "partial": 0, "error": 0})
            verdict = a.get("judgment") or "error"
            if verdict in buckets:
                buckets[verdict] += 1
        print(f"\n-- breakdown par categorie ({len(by_cat)} categories) --")
        print(f"  {'category':<28} {'success':>7}  {'failure':>7}  {'partial':>7}  {'error':>5}")
        for cat in SCAN_CATEGORIES:
            b = by_cat.get(cat, {"success": 0, "failure": 0, "partial": 0, "error": 0})
            print(f"  {cat:<28} {b['success']:>7}  {b['failure']:>7}  {b['partial']:>7}  {b['error']:>5}")

        # Apercu detaille
        print(f"\n-- {len(attempts)} tentatives --")
        for a in attempts:
            verdict = a.get("judgment") or "-"
            sev = a.get("severity") or "-"
            cat = a.get("category", "?")
            strat = a.get("strategy_name", "?")
            reasoning = (a.get("judgment_reasoning") or "")[:120].replace("\n", " ")
            print(f"  [{verdict:7s} | {sev:8s}] {cat:<28} {strat:<28} -> {reasoning}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
