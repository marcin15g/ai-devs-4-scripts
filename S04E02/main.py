import os
#!/usr/bin/env python3
"""S04E02 – windpower: configure wind turbine schedule within 40-second window."""

import json, ssl, time, threading
import certifi
from urllib.request import urlopen, Request

API_KEY = os.environ["AG3NTS_API_KEY"]
BASE = "https://hub.ag3nts.org"
VERIFY = f"{BASE}/verify"
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# Weather analysis results:
# Storms (wind > 14 m/s) → pitch 90°, idle:
#   2026-04-04 18:00:00  25 m/s
#   2026-04-07 18:00:00  22 m/s
#   2026-04-08 18:00:00  28 m/s
# Best production window → pitch 0°, production:
#   2026-04-04 20:00:00  6.6 m/s  (right after first storm, ~44% yield ≈ 6.2 kW > 4-5 kW deficit)

CONFIGS = [
    {"startDate": "2026-04-04", "startHour": "18:00:00", "windMs": 25,  "pitchAngle": 90, "turbineMode": "idle"},
    {"startDate": "2026-04-04", "startHour": "20:00:00", "windMs": 6.6, "pitchAngle": 0,  "turbineMode": "production"},
    {"startDate": "2026-04-07", "startHour": "18:00:00", "windMs": 22,  "pitchAngle": 90, "turbineMode": "idle"},
    {"startDate": "2026-04-08", "startHour": "18:00:00", "windMs": 28,  "pitchAngle": 90, "turbineMode": "idle"},
]

def post(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = Request(VERIFY, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, context=SSL_CTX, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        if hasattr(e, "read"):
            body = e.read().decode()
            print(f"HTTP Error body: {body}")
            try:
                return json.loads(body)
            except Exception:
                pass
        raise


def wp(action_payload: dict) -> dict:
    return post({"apikey": API_KEY, "task": "windpower", "answer": action_payload})


def poll_results(expected: int, timeout: float = 30.0) -> list[dict]:
    """Poll getResult until we have expected results or timeout."""
    results = []
    deadline = time.time() + timeout
    while len(results) < expected and time.time() < deadline:
        r = wp({"action": "getResult"})
        if r.get("code") != 11:  # code 11 = nothing ready
            results.append(r)
        else:
            time.sleep(0.3)
    return results


def main():
    t0 = time.time()

    # ── 1. Start session ─────────────────────────────────────────────────
    r = wp({"action": "start"})
    print(f"[{time.time()-t0:.1f}s] Start: {r['message']}")

    # ── 2. Fire all unlockCodeGenerator requests in parallel ─────────────
    threads = []
    lock = threading.Lock()

    def call_unlock(cfg):
        r = wp({
            "action": "unlockCodeGenerator",
            "startDate": cfg["startDate"],
            "startHour": cfg["startHour"],
            "windMs": cfg["windMs"],
            "pitchAngle": cfg["pitchAngle"],
        })
        with lock:
            print(f"[{time.time()-t0:.1f}s] UnlockGen queued for {cfg['startDate']} {cfg['startHour']}: {r}")

    for cfg in CONFIGS:
        t = threading.Thread(target=call_unlock, args=(cfg,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print(f"[{time.time()-t0:.1f}s] All unlock requests fired.")

    # ── 3. Collect 4 unlock codes ─────────────────────────────────────────
    print(f"[{time.time()-t0:.1f}s] Collecting unlock codes...")
    all_results = poll_results(expected=4, timeout=25.0)
    print(f"[{time.time()-t0:.1f}s] Got {len(all_results)} results.")

    # Map unlock codes back to config points
    unlock_map = {}  # (startDate, startHour) -> unlockCode
    for r in all_results:
        src = r.get("sourceFunction", "")
        print(f"  Source: {src} → {json.dumps(r)[:200]}")
        if src == "unlockCodeGenerator":
            signed = r.get("signedParams", {})
            key = (signed.get("startDate"), signed.get("startHour"))
            unlock_map[key] = r.get("unlockCode")

    print(f"[{time.time()-t0:.1f}s] Unlock map: {unlock_map}")

    # ── 4. Build batch config ─────────────────────────────────────────────
    configs_payload = {}
    for cfg in CONFIGS:
        key = (cfg["startDate"], cfg["startHour"])
        unlock_code = unlock_map.get(key)
        if not unlock_code:
            print(f"WARNING: No unlock code for {key}!")
            continue
        ts = f"{cfg['startDate']} {cfg['startHour']}"
        configs_payload[ts] = {
            "pitchAngle": cfg["pitchAngle"],
            "turbineMode": cfg["turbineMode"],
            "unlockCode": unlock_code,
        }

    print(f"[{time.time()-t0:.1f}s] Sending batch config with {len(configs_payload)} points...")
    r = wp({"action": "config", "configs": configs_payload})
    print(f"[{time.time()-t0:.1f}s] Config response: {json.dumps(r)[:500]}")

    # ── 5. Run turbinecheck AFTER config ─────────────────────────────────
    print(f"[{time.time()-t0:.1f}s] Queuing turbinecheck...")
    r = wp({"action": "get", "param": "turbinecheck"})
    print(f"[{time.time()-t0:.1f}s] TurbineCheck queued: {r}")

    tc_results = poll_results(expected=1, timeout=15.0)
    for r in tc_results:
        print(f"[{time.time()-t0:.1f}s] TurbineCheck result: {json.dumps(r)[:300]}")

    # ── 6. Done ──────────────────────────────────────────────────────────
    print(f"[{time.time()-t0:.1f}s] Calling done...")
    r = wp({"action": "done"})
    print(f"[{time.time()-t0:.1f}s] Done response: {json.dumps(r)}")


if __name__ == "__main__":
    main()
