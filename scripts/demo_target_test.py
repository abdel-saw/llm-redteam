"""Demo end-to-end : POST /api/targets puis POST /test contre Groq.

Lit GROQ_API_KEY depuis .env (sans l'afficher). Affiche les reponses HTTP
en JSON formate, en redactant le header Authorization.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


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


def dump(label: str, resp: httpx.Response) -> None:
    print(f"\n=== {label} ===")
    print(f"HTTP {resp.status_code}")
    try:
        body = resp.json()
        # Redact any Authorization header echoed in target's headers field.
        if isinstance(body, dict) and "headers" in body and isinstance(body["headers"], dict):
            for k in list(body["headers"]):
                if k.lower() == "authorization":
                    body["headers"][k] = "Bearer " + redact(body["headers"][k].split()[-1])
        print(json.dumps(body, indent=2, ensure_ascii=False))
    except ValueError:
        print(resp.text[:500])


def main() -> int:
    api_key = load_env_value(ENV_PATH, "GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY introuvable dans .env", file=sys.stderr)
        return 1
    print(f"GROQ_API_KEY chargee: {redact(api_key)}")

    create_body = {
        "name": "Groq (llama-3.3-70b)",
        "target_type": "openai_compatible",
        "endpoint_url": "https://api.groq.com/openai/v1",
        "model_name": "llama-3.3-70b-versatile",
        "headers": {"Authorization": f"Bearer {api_key}"},
    }

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        r1 = client.post("/api/targets", json=create_body)
        dump("POST /api/targets", r1)
        if r1.status_code >= 300:
            return 2

        target_id = r1.json()["id"]
        r2 = client.post(f"/api/targets/{target_id}/test", json={})
        dump(f"POST /api/targets/{target_id}/test", r2)
        if r2.status_code >= 300:
            return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
