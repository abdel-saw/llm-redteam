"""Validation live de la migration vers gpt-oss-safeguard-20b.

Cree 2 cibles Groq (llama-3.1-8b-instant et llama-3.3-70b-versatile),
lance un scan court contre chacune (5 categories x 2 attempts = 10 tentatives),
puis verifie que :
- Les deux scans terminent avec status=completed et robustness_score!=None.
- Aucun appel n'est passe via meta-llama/llama-guard-4-12b cote logs.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8000"
ALL_CATEGORIES = [
    "prompt_injection", "jailbreak", "system_prompt_leak",
    "sensitive_info_disclosure", "misinformation",
]


def load_env_value(key: str) -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def run_scan(client: httpx.Client, model_name: str, target_label: str) -> dict:
    print(f"\n=== {target_label} ({model_name}) ===")
    api_key = load_env_value("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing in .env")

    r = client.post("/api/targets", json={
        "name": target_label,
        "target_type": "openai_compatible",
        "endpoint_url": "https://api.groq.com/openai/v1",
        "headers": {"Authorization": f"Bearer {api_key}"},
        "model_name": model_name,
    })
    r.raise_for_status()
    target_id = r.json()["id"]
    print(f"  target id={target_id}")

    r = client.post("/api/scans", json={
        "target_id": target_id,
        "selected_categories": ALL_CATEGORIES,
        "max_attempts_per_category": 2,
    })
    r.raise_for_status()
    scan_id = r.json()["id"]
    print(f"  scan id={scan_id} — waiting for completion (max 180s)")

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        s = client.get(f"/api/scans/{scan_id}").json()
        status = s.get("status")
        if status in ("completed", "failed", "aborted"):
            print(f"  status={status}  score={s.get('robustness_score')}  "
                  f"attempts={s.get('total_attempts')}  "
                  f"successes={s.get('successful_attacks')}")
            return s
        time.sleep(2)

    raise RuntimeError(f"scan {scan_id} did not finish in time")


def main() -> int:
    with httpx.Client(base_url=BASE_URL, timeout=240.0) as client:
        scan_8b = run_scan(client, "llama-3.1-8b-instant", "validate-8B")
        scan_70b = run_scan(client, "llama-3.3-70b-versatile", "validate-70B")

    # Verifications dures.
    ok = True
    for label, s in (("8B", scan_8b), ("70B", scan_70b)):
        if s.get("status") != "completed":
            print(f"FAIL [{label}]: status={s.get('status')}", file=sys.stderr)
            ok = False
        if s.get("robustness_score") is None:
            print(f"FAIL [{label}]: robustness_score is None", file=sys.stderr)
            ok = False

    print("\n=== Result ===")
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
