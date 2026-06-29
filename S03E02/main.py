import os
#!/usr/bin/env python3
"""S03E02 – firmware: fix and run /opt/firmware/cooler/cooler.bin on a
restricted Linux VM accessed via the shell API, then submit the ECCS code."""

import json
import re
import ssl
import time
import urllib.request

API_KEY = os.environ["AG3NTS_API_KEY"]
SHELL_URL = "https://hub.ag3nts.org/api/shell"
VERIFY_URL = "https://hub.ag3nts.org/verify"
_ctx = ssl._create_unverified_context()


def _post(url: str, payload: dict) -> str:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, context=_ctx) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        # If temporarily banned, wait and retry
        try:
            err = json.loads(body)
            if err.get("ban") and err["ban"].get("ttl_seconds"):
                wait = err["ban"]["ttl_seconds"] + 2
                print(f"  [banned] waiting {wait}s...")
                time.sleep(wait)
                return _post(url, payload)
        except (json.JSONDecodeError, KeyError):
            pass
        return body


def shell(cmd: str) -> str:
    result = _post(SHELL_URL, {"apikey": API_KEY, "cmd": cmd})
    print(f"  $ {cmd}")
    print(f"    → {result[:300]}")
    return result


def verify(confirmation: str) -> str:
    return _post(
        VERIFY_URL,
        {
            "apikey": API_KEY,
            "task": "firmware",
            "answer": {"confirmation": confirmation},
        },
    )


def run():
    # Step 1: Find the password
    print("=== Finding password ===")
    txt_files = shell("find *.txt")
    pass_result = shell("cat /home/operator/notes/pass.txt")
    password = json.loads(pass_result)["data"].strip()
    print(f"  Password: {password}")

    # Step 2: Remove lock file if present
    print("\n=== Removing lock file ===")
    shell("rm /opt/firmware/cooler/cooler-is-blocked.lock")

    # Step 3: Fix settings.ini
    #   - Uncomment SAFETY_CHECK=pass  (line 2)
    #   - Disable test_mode            (line 6)
    #   - Enable cooling               (line 10)
    print("\n=== Fixing settings.ini ===")
    shell("editline /opt/firmware/cooler/settings.ini 2 SAFETY_CHECK=pass")
    shell("editline /opt/firmware/cooler/settings.ini 6 enabled=false")
    shell("editline /opt/firmware/cooler/settings.ini 10 enabled=true")

    # Verify the config
    cfg = shell("cat /opt/firmware/cooler/settings.ini")
    print(f"  Config: {json.loads(cfg)['data']}")

    # Step 4: Run the binary
    print("\n=== Running firmware ===")
    result = shell(f"/opt/firmware/cooler/cooler.bin {password}")
    data = json.loads(result).get("data", "")
    print(f"  Output: {data}")

    # Step 5: Extract ECCS code and submit
    match = re.search(r"ECCS-[a-f0-9]+", data)
    if match:
        eccs_code = match.group(0)
        print(f"\n=== Submitting: {eccs_code} ===")
        response = verify(eccs_code)
        print(f"  Result: {response}")
    else:
        print("ERROR: Could not find ECCS code in output!")


if __name__ == "__main__":
    run()
