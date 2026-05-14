"""Regenere les 6 screenshots apres le rebranding Red-Agent-S (v0.2.0).

Workflow :
1. Verifie les serveurs (Red-Agent-S + demo target).
2. Cree une cible json_custom pointant vers la cible demo.
3. Lance un petit scan court (3 cat x 2 attempts = 6).
4. Regenere le rapport pour scan #16 (si present) via POST /api/scans/16/report
   pour que le rapport historique porte le nouveau nom.
5. Captures :
   - 01_accueil.png      : page /
   - 02_scan_live.png    : page /scans/{new_id}/live (apres attente)
   - 03_history.png      : page /history
   - 04_rapport_overview.png : rapport scan #16 (sections repliees)
   - 05_rapport_categories_open.png : rapport scan #16, all details open
   - 06_rapport_all_attempts_open.png : rapport scan #16, all details open
     (cadre large)

Le script utilise Chrome headless. Pour ouvrir les <details>, on passe
par un fichier HTML temporaire dans lequel on injecte le script
"open everything" via une URL data: ou directement via le flag
--virtual-time-budget + un wrapper. Comme Chrome headless n'execute
pas de JS injecte par CLI sur une URL distante, on prefere :
  a) telecharger le rapport via HTTP,
  b) injecter le snippet d'ouverture dans le HTML,
  c) ouvrir le fichier local et capturer.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
TMP_DIR = Path(os.environ.get("TEMP", "/tmp")) / "red-agent-s-rescreens"
LLMRT_URL = "http://127.0.0.1:8000"
DEMO_TARGET_URL = "http://127.0.0.1:8765"

OPEN_ALL_SNIPPET = (
    "<script>"
    "document.addEventListener('DOMContentLoaded',function(){"
    "document.querySelectorAll('details').forEach(function(d){d.open=true;});"
    "});"
    "</script>"
)


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
    user_data = TMP_DIR / f"profile-{os.getpid()}-{out_path.stem}"
    args = [
        browser,
        "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--user-data-dir={user_data}",
        f"--window-size={w},{h}",
        "--virtual-time-budget=5000",
        f"--screenshot={out_path}",
        url,
    ]
    print(f"  shooting -> {out_path.name}")
    subprocess.run(args, check=False, timeout=60,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fetch_report_with_details_open(scan_id: int) -> Path:
    """Telecharge le rapport, injecte un snippet pour ouvrir tous les
    <details>, ecrit dans un fichier temporaire et retourne le path."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    r = httpx.get(f"{LLMRT_URL}/scans/{scan_id}/report", timeout=30.0)
    r.raise_for_status()
    html = r.text
    # Injecte juste avant </head>.
    html = re.sub(r"</head>", OPEN_ALL_SNIPPET + "</head>", html, count=1, flags=re.I)
    out = TMP_DIR / f"report_{scan_id}_open.html"
    out.write_text(html, encoding="utf-8")
    return out


def load_env_value(key: str) -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> int:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    print(f"Browser: {browser}")

    print("\n=== 1) Verify both servers ===")
    for url in (LLMRT_URL + "/", DEMO_TARGET_URL + "/healthz"):
        try:
            httpx.get(url, timeout=2.0).raise_for_status()
            print(f"  {url} OK")
        except httpx.HTTPError as exc:
            print(f"FAIL: {url} ({exc})", file=sys.stderr)
            return 1

    # Optional : re-launch a fresh short scan so the live page has fresh
    # data to show.
    print("\n=== 2) Launch short scan for /scans/{id}/live screenshot ===")
    target_id = None
    scan_id = None
    api_key = load_env_value("GROQ_API_KEY")
    if api_key:
        with httpx.Client(base_url=LLMRT_URL, timeout=180.0) as c:
            r = c.post("/api/targets", json={
                "name": "Rebranding screenshot target",
                "target_type": "json_custom",
                "endpoint_url": f"{DEMO_TARGET_URL}/chat",
                "request_template": '{"message": {{prompt}}}',
                "response_path": "$.reply",
            })
            r.raise_for_status()
            target_id = r.json()["id"]
            r = c.post("/api/scans", json={
                "target_id": target_id,
                "selected_categories": [
                    "prompt_injection", "jailbreak", "system_prompt_leak",
                ],
                "max_attempts_per_category": 2,
            })
            r.raise_for_status()
            scan_id = r.json()["id"]
            print(f"  scan id={scan_id}, waiting ~14s for some attempts to flow…")
            time.sleep(14)

    print("\n=== 3) Capture index ===")
    shoot(browser, f"{LLMRT_URL}/",
          SCREENSHOT_DIR / "01_accueil.png", w=1440, h=1100)

    print("\n=== 4) Capture live scan ===")
    if scan_id is not None:
        shoot(browser, f"{LLMRT_URL}/scans/{scan_id}/live",
              SCREENSHOT_DIR / "02_scan_live.png", w=1440, h=1400)
    else:
        print("  (no Groq key — skipping live capture)")

    # Wait for the new scan to complete to ensure history is populated.
    if scan_id is not None:
        print("\n=== 5) Wait for new scan to complete ===")
        with httpx.Client(base_url=LLMRT_URL, timeout=180.0) as c:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                s = c.get(f"/api/scans/{scan_id}").json()
                if s["status"] in ("completed", "failed", "aborted"):
                    print(f"  status={s['status']}  score={s.get('robustness_score')}")
                    break
                time.sleep(2)

    print("\n=== 6) Capture history ===")
    shoot(browser, f"{LLMRT_URL}/history",
          SCREENSHOT_DIR / "03_history.png", w=1440, h=900)

    print("\n=== 7) Pick a scan id for the report screenshots ===")
    report_scan_id = None
    with httpx.Client(base_url=LLMRT_URL, timeout=30.0) as c:
        scans = c.get("/api/scans?limit=100").json()
    # Prefer scan #16 if still around (matches the journaled demo); else
    # the most recent completed scan with attempts.
    by_id = {s["id"]: s for s in scans}
    if 16 in by_id and by_id[16]["total_attempts"] > 0:
        report_scan_id = 16
    else:
        completed = [s for s in scans if s["status"] == "completed" and s["total_attempts"] > 0]
        if completed:
            report_scan_id = max(s["id"] for s in completed)
    if report_scan_id is None:
        print("  no completed scan with attempts found — skipping report shots")
        return 0
    print(f"  using scan #{report_scan_id}")

    # Force regen so the report carries the new Red-Agent-S brand even if
    # it was generated under v0.1.0.
    print("\n=== 8) Regenerate report (rebranded) ===")
    with httpx.Client(base_url=LLMRT_URL, timeout=30.0) as c:
        c.post(f"/api/scans/{report_scan_id}/report").raise_for_status()

    print("\n=== 9) Capture report — overview (collapsed) ===")
    shoot(browser, f"{LLMRT_URL}/scans/{report_scan_id}/report",
          SCREENSHOT_DIR / "04_rapport_overview.png", w=1440, h=1500)

    print("\n=== 10) Capture report — categories (all details open) ===")
    local_open_html = fetch_report_with_details_open(report_scan_id)
    file_url = local_open_html.resolve().as_uri()
    shoot(browser, file_url,
          SCREENSHOT_DIR / "05_rapport_categories_open.png", w=1440, h=2400)

    print("\n=== 11) Capture report — all attempts list (open + filters) ===")
    shoot(browser, file_url,
          SCREENSHOT_DIR / "06_rapport_all_attempts_open.png", w=1600, h=2800)

    print("\n=== DONE ===")
    print(f"Screenshots in: {SCREENSHOT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
