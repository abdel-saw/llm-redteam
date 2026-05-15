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
    # Default 0.0.0.0 so the demo target is reachable from outside the
    # container when run via Docker (compose maps 8765:8765). In pure
    # local dev, override via DEMO_TARGET_HOST=127.0.0.1 for a stricter
    # bind.
    host = os.environ.get("DEMO_TARGET_HOST", "0.0.0.0")  # noqa: S104
    uvicorn.run(
        "scripts.demo_target.app:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
