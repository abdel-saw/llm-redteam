"""Capture des 3 captures d'ecran via Chrome headless.

Pre-requis :
- Le serveur uvicorn doit tourner sur http://127.0.0.1:8000.
- Chrome installe au chemin standard.

Sequence :
1. Cree une cible Groq.
2. Lance un scan court (3 categories x 2 attempts = ~25s).
3. Capture index, /scans/{id}/live (pendant l'execution), /history (apres).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
BASE_URL = "http://127.0.0.1:8000"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str:
    for path in CHROME_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RuntimeError("Chrome / Edge introuvable.")


def load_env_value(key: str) -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def shoot(browser: str, url: str, out_path: Path, *, width: int = 1440, height: int = 900):
    user_data = Path(os.environ["TEMP"]) / f"red-agent-s-shot-{os.getpid()}"
    args = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--user-data-dir={user_data}",
        f"--window-size={width},{height}",
        "--virtual-time-budget=4000",  # laisse le temps aux scripts SSE
        f"--screenshot={out_path}",
        url,
    ]
    print(f"  shooting {url} -> {out_path.name}")
    subprocess.run(args, check=False, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    print(f"Using browser: {browser}")

    api_key = load_env_value("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY missing in .env", file=sys.stderr)
        return 1

    # 1) Screenshot accueil (sans etat).
    shoot(browser, f"{BASE_URL}/", SCREENSHOT_DIR / "01_accueil.png", height=1100)

    # 2) Cree cible + lance scan.
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        r1 = client.post("/api/targets", json={
            "name": "Demo Groq Llama 3.1 8B",
            "target_type": "openai_compatible",
            "endpoint_url": "https://api.groq.com/openai/v1",
            "headers": {"Authorization": f"Bearer {api_key}"},
            "model_name": "llama-3.1-8b-instant",
        })
        if r1.status_code >= 300:
            print(f"ERROR creating target: {r1.text}", file=sys.stderr)
            return 2
        target_id = r1.json()["id"]
        print(f"  target id={target_id}")

        r2 = client.post("/api/scans", json={
            "target_id": target_id,
            "selected_categories": ["prompt_injection", "jailbreak", "system_prompt_leak"],
            "max_attempts_per_category": 2,
        })
        if r2.status_code >= 300:
            print(f"ERROR creating scan: {r2.text}", file=sys.stderr)
            return 3
        scan_id = r2.json()["id"]
        print(f"  scan id={scan_id}")

        # 3) Attendre ~12s pour avoir des attempts visibles (pas terminé).
        print("  waiting 14s for attempts to flow in…")
        time.sleep(14)

        shoot(browser, f"{BASE_URL}/scans/{scan_id}/live",
              SCREENSHOT_DIR / "02_scan_live.png", height=1400)

        # 4) Attendre la fin (jusqu'a ~60s max).
        print("  waiting for scan to complete…")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            r = client.get(f"/api/scans/{scan_id}")
            if r.json().get("status") in ("completed", "failed", "aborted"):
                break
            time.sleep(2)

    # 5) Screenshot historique (avec le scan termine).
    shoot(browser, f"{BASE_URL}/history",
          SCREENSHOT_DIR / "03_history.png", height=700)

    print(f"\nScreenshots saved to {SCREENSHOT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
