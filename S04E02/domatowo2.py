import os
#!/usr/bin/env python3
"""Domatowo - continuation: search SE block3 group (H10,I10,H11,I11)."""

import json, ssl, time
from urllib.request import urlopen, Request

API_KEY = os.environ["AG3NTS_API_KEY"]
VERIFY = "https://hub.ag3nts.org/verify"
SSL_CTX = ssl._create_unverified_context()
found_at = None


def post(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = Request(VERIFY, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, context=SSL_CTX, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        if hasattr(e, "read"):
            body = e.read().decode()
            print(f"HTTP Error: {body}")
            try:
                return json.loads(body)
            except Exception:
                pass
        raise


def dm(answer: dict) -> dict:
    return post({"apikey": API_KEY, "task": "domatowo", "answer": answer})


def get_objects():
    r = dm({"action": "getObjects"})
    return r.get("objects", [])


def move_unit(obj_id: str, where: str) -> dict:
    r = dm({"action": "move", "object": obj_id, "where": where})
    print(f"  MOVE {obj_id[:8]}→{where}: {r.get('message','?')} ap_left={r.get('action_points_left','?')}")
    return r


def dismount_unit(obj_id: str, passengers: int) -> dict:
    r = dm({"action": "dismount", "object": obj_id, "passengers": passengers})
    print(f"  DISMOUNT {obj_id[:8]} {passengers}p: {r.get('message','?')}")
    return r


def inspect_unit(obj_id: str) -> dict:
    r = dm({"action": "inspect", "object": obj_id})
    print(f"  INSPECT {obj_id[:8]}: ap_left={r.get('action_points_left','?')} entries={r.get('entries','?')}")
    return r


NEGATIVE_PATTERNS = [
    "pusto", "pusty", "pusta", "nikogo", "brak", "nie natrafiłem",
    "nie natrafiliśmy", "nie odnotowano", "opuszczone", "opuszczony",
    "nie ma", "nie było", "nikt", "nic", "brak obecności",
]

POSITIVE_PATTERNS = [
    "znalazłem go", "jest człowiek", "jest tu człowiek", "znaleziono człowieka",
    "to on", "ocalały", "ocalal", "jest ranny", "znaleziono rannego",
    "partyz", "cywil - jest", "jest żywy", "jest zywy", "żyje", "zyje",
    "udało się znaleźć", "potwierdzam obecność", "jest tu", "ukryty",
    "ranny i żywy", "żywy", "jest!", "znalazłem człowieka",
]


def is_human_found(msg: str) -> bool:
    msg_lower = msg.lower()
    # Check for explicit negative first
    for neg in NEGATIVE_PATTERNS:
        if neg in msg_lower:
            return False
    # Check for positive indicators
    for pos in POSITIVE_PATTERNS:
        if pos in msg_lower:
            return True
    # Fallback: "człowiek" without negation context
    if "człowiek" in msg_lower or "człowieka" in msg_lower:
        # Make sure not preceded by "nie" or similar
        idx = msg_lower.find("człowiek")
        context = msg_lower[max(0, idx-30):idx]
        if "nie " not in context and "brak" not in context and "nikogo" not in context:
            return True
    return False


def check_latest_log() -> tuple[bool, str]:
    """Returns (found, tile) from last log entry."""
    r = dm({"action": "getLogs"})
    logs = r.get("logs", [])
    if not logs:
        return False, ""
    last = logs[-1]
    msg = last.get("msg", "")
    tile = last.get("field", "")
    print(f"    LOG[{len(logs)-1}] @{tile}: {msg}")
    if is_human_found(msg):
        print(f"    *** HUMAN CONFIRMED at {tile}! ***")
        return True, tile
    return False, tile


def search_tile(scout_id: str, tile: str) -> bool:
    global found_at
    if found_at:
        return True
    move_unit(scout_id, tile)
    time.sleep(0.4)
    inspect_unit(scout_id)
    time.sleep(0.4)
    found, coord = check_latest_log()
    if found:
        found_at = coord or tile
    return found


def ap_status():
    r = dm({"action": "expenses"})
    print(f"  AP: used={r.get('action_points_used','?')} left={r.get('action_points_left','?')}")


def main():
    global found_at

    print("=== DOMATOWO MISSION - CONTINUATION (SE group) ===\n")
    ap_status()

    # Current state after previous run:
    # - T1 at E2, T2 at B9 (both with scouts dismounted)
    # - 4 scouts deployed (north + SW groups searched)
    # - AP used: 160, left: 140
    # Need T3 for SE group

    print("\n--- T3: SE block3 group (H10,I10,H11,I11) ---")
    r = dm({"action": "create", "type": "transporter", "passengers": 2})
    print(f"  CREATE T3: {json.dumps(r)[:300]}")
    t3_id = r.get("object") or r.get("id", "")
    crew = r.get("crew", [])
    print(f"  T3 id: {t3_id}")
    print(f"  Crew: {[c['id'][:8] for c in crew]}")
    time.sleep(0.4)

    # Route C6→D6→D9→I9 = 9 steps
    move_unit(t3_id, "I9")
    time.sleep(0.4)
    dismount_unit(t3_id, 2)
    time.sleep(0.4)

    objs = get_objects()
    print(f"  All objects: {json.dumps(objs)[:800]}")

    crew_ids = {c["id"] for c in crew}
    se_scouts = [o for o in objs if o.get("id") in crew_ids]

    if not se_scouts:
        # fallback: get scouts near I9
        se_scouts = [o for o in objs if o.get("typ") == "scout" and
                     o.get("id") not in {c["id"] for c in []}]
        # Just use all scouts from crew
        se_scouts = [{"id": c["id"], "typ": "scout"} for c in crew]

    print(f"  SE scouts: {[s['id'][:8] for s in se_scouts]}")

    # SE tiles: H10, I10, H11, I11
    if len(se_scouts) >= 2:
        s1 = se_scouts[0]["id"]
        s2 = se_scouts[1]["id"]
        for tile in ["I10", "I11"]:
            if search_tile(s1, tile):
                break
        if not found_at:
            for tile in ["H10", "H11"]:
                if search_tile(s2, tile):
                    break
    elif len(se_scouts) == 1:
        for tile in ["H10", "I10", "H11", "I11"]:
            if search_tile(se_scouts[0]["id"], tile):
                break
    else:
        print("  WARNING: No SE scouts!")

    ap_status()

    # Print all logs for analysis
    print("\n--- ALL LOGS ---")
    r = dm({"action": "getLogs"})
    for i, entry in enumerate(r.get("logs", [])):
        print(f"  [{i}] @{entry.get('field','?')}: {entry.get('msg','?')}")

    if found_at:
        print(f"\n*** CALLING HELICOPTER to {found_at} ***")
        r = dm({"action": "callHelicopter", "destination": found_at})
        print(f"Helicopter: {json.dumps(r, ensure_ascii=False)}")
    else:
        print("\n!!! PARTISAN NOT FOUND IN ANY BLOCK3 TILE !!!")
        print("Remaining AP, may need to search other tall buildings (church, school)")
        ap_status()


if __name__ == "__main__":
    main()
