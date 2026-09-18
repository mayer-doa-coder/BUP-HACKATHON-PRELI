"""Container health probe.

A separate script rather than an inline ``python -c`` in the Dockerfile, because the port has
to be read from the environment: Azure and most container platforms inject their own ``PORT``,
and a probe hard-coded to 8000 would report the service dead the moment the platform picks
anything else.

Exits 0 only when ``/health`` answers 200 with the canonical readiness body.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

TIMEOUT_SECONDS = 3.0


def main() -> int:
    port = os.environ.get("PORT", "8000")
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed localhost URL
            if response.status != 200:
                return 1
            body = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - any failure means "not healthy"
        return 1
    return 0 if body.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
