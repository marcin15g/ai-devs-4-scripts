import os
#!/usr/bin/env python3
"""
foodwarehouse task - create orders for 8 cities from food4cities.json.

Cities & needs (from food4cities.json):
  opalino:   {chleb:45, woda:120, mlotek:6}
  domatowo:  {makaron:60, woda:150, lopata:8}
  brudzewo:  {ryz:55, woda:140, wiertarka:5}
  darzlubie: {wolowina:25, woda:130, kilof:7}
  celbowo:   {kurczak:40, woda:125, mlotek:6}
  mechowo:   {ziemniaki:100, kapusta:70, marchew:65, woda:165, lopata:9}
  puck:      {chleb:50, ryz:45, woda:175, wiertarka:7}
  karlinkowo:{makaron:52, wolowina:22, ziemniaki:95, woda:155, kilof:6}

Destination IDs (from DB):
  opalino:   991828
  domatowo:  761834
  brudzewo:  234434
  darzlubie: 676323
  celbowo:   741906
  mechowo:   695992
  puck:      140606
  karlinkowo:707536

Creator: user_id=1, login="azurek", birthday="1983-09-23"
"""

import json, ssl, time
from urllib.request import urlopen, Request

API_KEY = os.environ["AG3NTS_API_KEY"]
VERIFY = "https://hub.ag3nts.org/verify"
SSL_CTX = ssl._create_unverified_context()


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


def fw(answer: dict) -> dict:
    return post({"apikey": API_KEY, "task": "foodwarehouse", "answer": answer})


# City data
CITIES = {
    "opalino":    {"dest": 991828,  "items": {"chleb": 45, "woda": 120, "mlotek": 6}},
    "domatowo":   {"dest": 761834,  "items": {"makaron": 60, "woda": 150, "lopata": 8}},
    "brudzewo":   {"dest": 234434,  "items": {"ryz": 55, "woda": 140, "wiertarka": 5}},
    "darzlubie":  {"dest": 676323,  "items": {"wolowina": 25, "woda": 130, "kilof": 7}},
    "celbowo":    {"dest": 741906,  "items": {"kurczak": 40, "woda": 125, "mlotek": 6}},
    "mechowo":    {"dest": 695992,  "items": {"ziemniaki": 100, "kapusta": 70, "marchew": 65, "woda": 165, "lopata": 9}},
    "puck":       {"dest": 140606,  "items": {"chleb": 50, "ryz": 45, "woda": 175, "wiertarka": 7}},
    "karlinkowo": {"dest": 707536,  "items": {"makaron": 52, "wolowina": 22, "ziemniaki": 95, "woda": 155, "kilof": 6}},
}

# Must be role=2 "Obsługa transportów" user
CREATOR_ID = 2
CREATOR_LOGIN = "tgajewski"
CREATOR_BIRTHDAY = "1991-04-06"


def generate_signature(destination: int) -> str:
    r = fw({
        "tool": "signatureGenerator",
        "action": "generate",
        "login": CREATOR_LOGIN,
        "birthday": CREATOR_BIRTHDAY,
        "destination": destination,
    })
    print(f"  SIG gen for dest {destination}: {json.dumps(r)[:200]}")
    sig = r.get("signature") or r.get("sign") or r.get("hash") or ""
    return sig


def create_order(city: str, dest: int, sig: str) -> str:
    r = fw({
        "tool": "orders",
        "action": "create",
        "title": f"Dostawa dla {city.capitalize()}",
        "creatorID": CREATOR_ID,
        "destination": dest,
        "signature": sig,
    })
    print(f"  CREATE order for {city}: {json.dumps(r)[:200]}")
    order_id = (r.get("order") or {}).get("id") or r.get("id") or r.get("order_id") or ""
    return order_id


def append_items(order_id: str, items: dict):
    r = fw({
        "tool": "orders",
        "action": "append",
        "id": order_id,
        "items": items,
    })
    print(f"  APPEND items to {order_id[:12]}: {json.dumps(r)[:200]}")
    return r


def main():
    print("=== FOODWAREHOUSE TASK ===\n")

    # Reset to clean state
    print("Resetting...")
    r = fw({"tool": "reset"})
    print(f"Reset: {r}\n")

    # Process each city
    order_ids = {}
    for city, data in CITIES.items():
        dest = data["dest"]
        items = data["items"]
        print(f"\n--- {city.upper()} (dest={dest}) ---")

        # 1. Generate signature
        sig = generate_signature(dest)
        if not sig:
            print(f"  ERROR: No signature for {city}!")
            continue

        # 2. Create order
        order_id = create_order(city, dest, sig)
        if not order_id:
            print(f"  ERROR: No order_id for {city}!")
            continue
        order_ids[city] = order_id

        # 3. Append items
        append_items(order_id, items)
        time.sleep(0.2)

    # Verify all orders
    print("\n--- Verifying orders ---")
    r = fw({"tool": "orders", "action": "get"})
    orders = r.get("orders", [])
    print(f"Total orders: {len(orders)}")
    for o in orders:
        item_summary = [(i['name'], i['items']) for i in o.get('items', [])]
        print(f"  [{o['id'][:12]}] dest={o['destination']} items={item_summary}")

    # Call done
    print("\n--- Calling DONE ---")
    r = fw({"tool": "done"})
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
