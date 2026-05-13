"""Orchestrateur de démo : lance la cible InternalLegalBot, attend
qu'elle réponde, puis affiche les URLs / valeurs pour configurer
LLM-RT côté UI.

Reste en avant-plan jusqu'à Ctrl+C. Le serveur LLM-RT principal doit
être lancé séparément (cf. README).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import httpx

PORT = int(os.environ.get("DEMO_TARGET_PORT", "8765"))
HEALTH_URL = f"http://127.0.0.1:{PORT}/healthz"


def wait_healthy(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(HEALTH_URL, timeout=2.0)
            if r.status_code == 200 and r.json().get("ok"):
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


BANNER = """
================================================================
  InternalLegalBot — demo target is RUNNING on http://127.0.0.1:{port}

  Health check:  {health}

  Configure LLM-RT (http://127.0.0.1:8000) with EITHER:

  [Option A: json_custom]
    name              : Demo InternalLegalBot (json)
    target_type       : json_custom
    endpoint_url      : http://localhost:{port}/chat
    request_template  : {{"message": {{{{prompt}}}}}}
    response_path     : $.reply

  [Option B: openai_compatible]
    name              : Demo InternalLegalBot (openai)
    target_type       : openai_compatible
    endpoint_url      : http://localhost:{port}/v1
    model_name        : llama-3.1-8b-instant

  Press Ctrl+C to stop the demo target.
================================================================
"""


def main() -> int:
    cmd = [sys.executable, "-m", "scripts.demo_target.run"]
    print(f"Starting demo target on port {PORT}...")
    proc = subprocess.Popen(cmd)
    try:
        if not wait_healthy():
            print("ERROR: demo target failed to become healthy", file=sys.stderr)
            proc.terminate()
            return 1
        print(BANNER.format(port=PORT, health=HEALTH_URL))
        proc.wait()
    except KeyboardInterrupt:
        print("\nStopping demo target...")
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
