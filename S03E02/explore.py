import os
#!/usr/bin/env python3
"""Quick helper to explore the VM interactively."""

import json
import ssl
import sys
import urllib.request

API_KEY = os.environ["AG3NTS_API_KEY"]
SHELL_URL = "https://hub.ag3nts.org/api/shell"
_ctx = ssl._create_unverified_context()


def shell(cmd: str) -> str:
    data = json.dumps({"apikey": API_KEY, "cmd": cmd}).encode()
    req = urllib.request.Request(
        SHELL_URL, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, context=_ctx) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode()}"


if __name__ == "__main__":
    cmd = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "help"
    print(shell(cmd))
