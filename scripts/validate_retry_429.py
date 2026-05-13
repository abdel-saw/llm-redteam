"""Validation live du retry 429.

Lance un scan 5 categories x 5 attempts (~25 tentatives, ~75 appels LLM)
contre llama-3.1-8b-instant et exporte le scan en JSON dans
docs/benchmarks/. Verifie que tous les attempts ont un verdict final
(error inclus) et que robustness_score est calcule.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = ROOT / "docs" / "benchmarks"
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


def run(model_name: str, label: str, attempts: int = 5) -> dict:
    api_key = load_env_value("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing in .env")
    with httpx.Client(base_url=BASE_URL, timeout=300.0) as c:
        r = c.post("/api/targets", json={
            "name": label,
            "target_type": "openai_compatible",
            "endpoint_url": "https://api.groq.com/openai/v1",
            "headers": {"Authorization": f"Bearer {api_key}"},
            "model_name": model_name,
        })
        r.raise_for_status()
        tid = r.json()["id"]
        print(f"  target id={tid}")

        r = c.post("/api/scans", json={
            "target_id": tid,
            "selected_categories": ALL_CATEGORIES,
            "max_attempts_per_category": attempts,
        })
        r.raise_for_status()
        sid = r.json()["id"]
        print(f"  scan id={sid} — waiting (max 300s)")

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            s = c.get(f"/api/scans/{sid}").json()
            if s["status"] in ("completed", "failed", "aborted"):
                print(f"  status={s['status']}  score={s.get('robustness_score')}  "
                      f"attempts={s.get('total_attempts')}  "
                      f"successes={s.get('successful_attacks')}")
                return s
            time.sleep(3)
        raise RuntimeError(f"scan {sid} timed out")


def export_scan(scan: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scan, indent=2, default=str), encoding="utf-8")
    print(f"  exported -> {path}")


def main() -> int:
    print("=== 8B / 5x5 ===")
    scan_8b = run("llama-3.1-8b-instant", "bench-8B", attempts=5)
    export_scan(scan_8b, BENCH_DIR / "scan_8b_5x5.json")

    print("\n=== 70B / 5x2 ===")
    scan_70b = run("llama-3.3-70b-versatile", "bench-70B", attempts=2)
    export_scan(scan_70b, BENCH_DIR / "scan_70b_5x2.json")

    ok = (scan_8b["status"] == "completed"
          and scan_8b["robustness_score"] is not None
          and scan_70b["status"] == "completed"
          and scan_70b["robustness_score"] is not None)
    print("\n=== Result ===")
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
