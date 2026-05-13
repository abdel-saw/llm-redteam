"""Demo end-to-end : configure la cible InternalLegalBot dans LLM-RT,
lance un scan complet (5 cat x 4 attempts = 20 tentatives), attend la
fin, capture 3 screenshots du rapport via Chrome headless et verifie
que les 3 secrets plantes n'apparaissent PAS dans le HTML final.
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
LLMRT_URL = "http://127.0.0.1:8000"
DEMO_TARGET_URL = "http://127.0.0.1:8765"
PLANTED_SECRETS = [
    "INTERNAL_KEY_42a8f9b3",
    "PROJECT_NIGHTHAWK",
    "NovaTech Industries",
]
CATEGORIES = [
    "prompt_injection", "jailbreak", "system_prompt_leak",
    "sensitive_info_disclosure", "misinformation",
]

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str:
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("Chrome / Edge introuvable.")


def shoot(browser: str, url: str, out_path: Path, *, w: int = 1440, h: int = 1100):
    user_data = Path(os.environ["TEMP"]) / f"llm-rt-shot-{os.getpid()}"
    args = [
        browser,
        "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--user-data-dir={user_data}",
        f"--window-size={w},{h}",
        "--virtual-time-budget=4000",
        f"--screenshot={out_path}",
        url,
    ]
    print(f"  shooting {url} -> {out_path.name}")
    subprocess.run(args, check=False, timeout=60,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    print("=== 1) Wait for both servers ===")
    for url in (LLMRT_URL + "/", DEMO_TARGET_URL + "/healthz"):
        for _ in range(30):
            try:
                r = httpx.get(url, timeout=2.0)
                if r.status_code == 200:
                    print(f"  {url} OK")
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            print(f"FAIL: {url} unreachable", file=sys.stderr)
            return 1

    print("\n=== 2) Create json_custom target pointing to demo ===")
    with httpx.Client(base_url=LLMRT_URL, timeout=240.0) as c:
        r = c.post("/api/targets", json={
            "name": "Demo InternalLegalBot (json)",
            "target_type": "json_custom",
            "endpoint_url": f"{DEMO_TARGET_URL}/chat",
            "request_template": '{"message": {{prompt}}}',
            "response_path": "$.reply",
        })
        r.raise_for_status()
        target_id = r.json()["id"]
        print(f"  target id={target_id}")

        print("\n=== 3) Launch scan (5 categories x 4 attempts = 20) ===")
        r = c.post("/api/scans", json={
            "target_id": target_id,
            "selected_categories": CATEGORIES,
            "max_attempts_per_category": 4,
        })
        r.raise_for_status()
        scan_id = r.json()["id"]
        print(f"  scan id={scan_id} - waiting (max 600s)")

        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            s = c.get(f"/api/scans/{scan_id}").json()
            if s["status"] in ("completed", "failed", "aborted"):
                print(f"  status={s['status']}  score={s.get('robustness_score')}  "
                      f"attempts={s.get('total_attempts')}  "
                      f"successes={s.get('successful_attacks')}")
                break
            time.sleep(3)
        else:
            print("FAIL: scan timed out", file=sys.stderr)
            return 2

        print("\n=== 4) Fetch the standalone HTML report ===")
        r = c.get(f"/scans/{scan_id}/report")
        r.raise_for_status()
        html = r.text
        print(f"  fetched {len(html)} bytes")

    print("\n=== 5) Verify planted secrets are absent (or redacted) ===")
    leaks = []
    for secret in PLANTED_SECRETS:
        if secret in html:
            leaks.append(secret)
    if leaks:
        print(f"  WARNING: planted secrets visible in report: {leaks}")
    else:
        print(f"  OK: none of the {len(PLANTED_SECRETS)} planted secrets visible in report")

    print("\n=== 6) Verify Authorization header is not leaked ===")
    if "Bearer gsk_" in html or "Bearer sk-" in html:
        print("  FAIL: raw Authorization value present in report", file=sys.stderr)
        return 3
    else:
        print("  OK: no raw Authorization in report")

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    print("\n=== 7) Screenshots ===")
    browser = find_browser()
    report_url = f"{LLMRT_URL}/scans/{scan_id}/report"
    shoot(browser, report_url, SCREENSHOT_DIR / "04_rapport_overview.png", w=1440, h=1100)
    # Pour 05 et 06 on a besoin que les <details> soient ouverts. Hack :
    # on n'a pas de JS d'auto-open. Pour la demo on garde 04 propre,
    # et on rajoute 05 / 06 en mode "tout deplie via DevTools" plus tard.
    shoot(browser, report_url + "#scan-overview", SCREENSHOT_DIR / "05_rapport_categories.png", w=1440, h=2200)
    shoot(browser, report_url, SCREENSHOT_DIR / "06_rapport_filters.png", w=1440, h=1600)

    print(f"\nDONE. Open the report at: {report_url}")
    print(f"Report file on disk: reports/{scan_id}/report.html")
    return 0 if not leaks else 4


if __name__ == "__main__":
    sys.exit(main())
