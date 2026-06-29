import os
#!/usr/bin/env python3
"""Domatowo evacuation mission - find partisan in tallest blocks (B3)."""

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


def get_unit_id(obj) -> str:
    return obj.get("id") or obj.get("hash") or obj.get("object", "")


def get_unit_type(obj) -> str:
    return obj.get("typ") or obj.get("type", "")


def get_unit_pos(obj) -> str:
    return obj.get("position") or obj.get("pos", "")


def create_transporter(passengers: int) -> str:
    r = dm({"action": "create", "type": "transporter", "passengers": passengers})
    print(f"  CREATE transporter({passengers}) → {json.dumps(r)[:300]}")
    return r.get("object") or r.get("id") or r.get("hash", "")


def move_unit(obj_id: str, where: str) -> dict:
    r = dm({"action": "move", "object": obj_id, "where": where})
    print(f"  MOVE {obj_id[:8]}→{where}: {r.get('message','?')} (cost:{r.get('cost','?')})")
    return r


def dismount_unit(obj_id: str, passengers: int) -> dict:
    r = dm({"action": "dismount", "object": obj_id, "passengers": passengers})
    print(f"  DISMOUNT {obj_id[:8]} {passengers}p: {r.get('message','?')}")
    return r


def inspect_unit(obj_id: str) -> dict:
    r = dm({"action": "inspect", "object": obj_id})
    print(f"  INSPECT {obj_id[:8]}: {json.dumps(r)[:200]}")
    return r


def check_for_human() -> str | None:
    """Returns tile coordinate if human found in logs, else None."""
    global found_at
    if found_at:
        return found_at
    r = dm({"action": "getLogs"})
    logs = r.get("logs", [])
    if logs:
        last = logs[-1]
        print(f"    log[{len(logs)-1}]: {json.dumps(last)[:200]}")
        msg = json.dumps(last).lower()
        keywords = ["człowiek", "human", "person", "partyz", "znalezion", "cywil",
                    "ocalał", "ranny", "ocalal", "survivor", "wounded", "found"]
        if any(k in msg for k in keywords):
            pos = (last.get("position") or last.get("field") or
                   last.get("location") or last.get("coords") or last.get("tile"))
            print(f"  *** HUMAN FOUND! pos={pos}, log={json.dumps(last)[:300]} ***")
            found_at = pos
            return pos
    return None


def search_tile(scout_id: str, tile: str) -> bool:
    """Move scout to tile and inspect. Returns True if human found."""
    global found_at
    if found_at:
        return True
    move_unit(scout_id, tile)
    time.sleep(0.4)
    inspect_unit(scout_id)
    time.sleep(0.4)
    result = check_for_human()
    return result is not None


def ap_status():
    r = dm({"action": "expenses"})
    used = r.get("action_points_used", "?")
    left = r.get("action_points_left", "?")
    print(f"  AP: used={used}, left={left}")


def main():
    global found_at
    print("=== DOMATOWO MISSION ===\n")

    # Reset for fresh start
    r = dm({"action": "reset"})
    print(f"Reset: {r}\n")

    ap_status()

    # ─── T1: North group F1,G1,F2,G2 ───────────────────────────────────────
    print("\n--- T1: north block3 group ---")
    t1_id = create_transporter(2)
    print(f"  T1 id: {t1_id}")

    # Route: A6→D6→D5→D4→D3→D2→E2 = 8 steps
    move_unit(t1_id, "E2")
    time.sleep(0.4)
    dismount_unit(t1_id, 2)
    time.sleep(0.4)

    # Get scouts spawned near E2
    objs = get_objects()
    print(f"  Objects: {json.dumps(objs)[:600]}")
    scouts_all = [o for o in objs if get_unit_type(o) in ("scout", "zwiadowca")]
    print(f"  Scouts found: {len(scouts_all)}")
    for s in scouts_all:
        print(f"    {get_unit_id(s)[:8]} @ {get_unit_pos(s)}")

    north_scouts = scouts_all[:2]

    # Search north tiles
    north_tiles = ["F2", "G2", "G1", "F1"]
    if len(north_scouts) >= 2:
        # Scout 0: F2, G2
        for tile in ["F2", "G2"]:
            if search_tile(get_unit_id(north_scouts[0]), tile):
                break
        # Scout 1: G1, F1
        if not found_at:
            for tile in ["G1", "F1"]:
                if search_tile(get_unit_id(north_scouts[1]), tile):
                    break
    elif len(north_scouts) == 1:
        for tile in north_tiles:
            if search_tile(get_unit_id(north_scouts[0]), tile):
                break
    else:
        print("  WARNING: No scouts found for north group!")

    ap_status()

    # ─── T2: SW group A10,B10,C10,A11,B11,C11 ─────────────────────────────
    if not found_at:
        print("\n--- T2: SW block3 group ---")
        t2_id = create_transporter(2)
        print(f"  T2 id: {t2_id}")

        # Route: B6→C6→D6→D7→D8→D9→C9→B9 = 7 steps
        move_unit(t2_id, "B9")
        time.sleep(0.4)
        dismount_unit(t2_id, 2)
        time.sleep(0.4)

        objs = get_objects()
        scouts_now = [o for o in objs if get_unit_type(o) in ("scout", "zwiadowca")]
        sw_scouts = [s for s in scouts_now if s not in north_scouts]
        # Identify by new scouts (those not in previous list)
        north_ids = {get_unit_id(s) for s in north_scouts}
        sw_scouts = [s for s in scouts_now if get_unit_id(s) not in north_ids]
        print(f"  SW scouts: {[get_unit_id(s)[:8] for s in sw_scouts]} @ {[get_unit_pos(s) for s in sw_scouts]}")

        sw_tiles = ["B10", "A10", "A11", "B11", "C11", "C10"]
        if len(sw_scouts) >= 2:
            # Scout 0: B10, A10, A11
            for tile in ["B10", "A10", "A11"]:
                if search_tile(get_unit_id(sw_scouts[0]), tile):
                    break
            # Scout 1: B11, C11, C10
            if not found_at:
                for tile in ["B11", "C11", "C10"]:
                    if search_tile(get_unit_id(sw_scouts[1]), tile):
                        break
        elif len(sw_scouts) == 1:
            for tile in sw_tiles:
                if search_tile(get_unit_id(sw_scouts[0]), tile):
                    break
        else:
            print("  WARNING: No scouts for SW group!")

        ap_status()

    # ─── T3: SE group H10,I10,H11,I11 ─────────────────────────────────────
    if not found_at:
        print("\n--- T3: SE block3 group ---")
        t3_id = create_transporter(2)
        print(f"  T3 id: {t3_id}")

        # Route: C6→D6→D9→I9 = 1+3+5 = 9 steps
        move_unit(t3_id, "I9")
        time.sleep(0.4)
        dismount_unit(t3_id, 2)
        time.sleep(0.4)

        objs = get_objects()
        scouts_now = [o for o in objs if get_unit_type(o) in ("scout", "zwiadowca")]
        prev_ids = {get_unit_id(s) for s in scouts_all}
        if "sw_scouts" in dir():
            prev_ids |= {get_unit_id(s) for s in sw_scouts}  # type: ignore
        se_scouts = [s for s in scouts_now if get_unit_id(s) not in prev_ids]
        # Fallback: take last 2
        if not se_scouts:
            se_scouts = scouts_now[-2:]
        print(f"  SE scouts: {[get_unit_id(s)[:8] for s in se_scouts]} @ {[get_unit_pos(s) for s in se_scouts]}")

        se_tiles = ["I10", "H10", "H11", "I11"]
        if len(se_scouts) >= 2:
            for tile in ["I10", "I11"]:
                if search_tile(get_unit_id(se_scouts[0]), tile):
                    break
            if not found_at:
                for tile in ["H10", "H11"]:
                    if search_tile(get_unit_id(se_scouts[1]), tile):
                        break
        elif len(se_scouts) == 1:
            for tile in se_tiles:
                if search_tile(get_unit_id(se_scouts[0]), tile):
                    break
        else:
            print("  WARNING: No scouts for SE group!")

        ap_status()

    # ─── FINAL ─────────────────────────────────────────────────────────────
    print("\n--- FINAL LOGS ---")
    r = dm({"action": "getLogs"})
    print(json.dumps(r, indent=2, ensure_ascii=False)[:2000])

    print("\n--- EXPENSES ---")
    ap_status()

    if found_at:
        print(f"\n*** CALLING HELICOPTER to {found_at} ***")
        r = dm({"action": "callHelicopter", "destination": found_at})
        print(f"Helicopter: {json.dumps(r, ensure_ascii=False)}")
    else:
        print("\n!!! PARTISAN NOT FOUND IN BLOCK3 - need further investigation !!!")
        # Print all logs for analysis
        r = dm({"action": "getLogs"})
        print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
