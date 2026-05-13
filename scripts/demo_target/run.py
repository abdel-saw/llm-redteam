"""Lance la cible de démo InternalLegalBot avec uvicorn.

Utilise la variable d'env DEMO_TARGET_PORT (default 8765). Les logs
sont en niveau INFO pour rester lisibles.
"""

from __future__ import annotations

import os
import sys

import uvicorn


def main() -> int:
    port = int(os.environ.get("DEMO_TARGET_PORT", "8765"))
    uvicorn.run(
        "scripts.demo_target.app:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        reload=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
