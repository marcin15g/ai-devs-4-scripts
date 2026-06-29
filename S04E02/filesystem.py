import os
#!/usr/bin/env python3
"""
Filesystem task - build Natan's trade notes structure.

Analysis from notes:
  - 8 cities with needs (from ogłoszenia.txt)
  - 8 people managing trade (from rozmowy.txt)
  - 13 goods for sale (from transakcje.txt)

Structure:
  /miasta/<city>  → JSON of city needs
  /osoby/<person> → name + markdown link to city
  /towary/<good>  → markdown link(s) to selling city/cities
"""

import json, ssl
from urllib.request import urlopen, Request

API_KEY = os.environ["AG3NTS_API_KEY"]
VERIFY = "https://hub.ag3nts.org/verify"
SSL_CTX = ssl._create_unverified_context()


def post(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = Request(VERIFY, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, context=SSL_CTX, timeout=30) as resp:
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


def fs(answer) -> dict:
    return post({"apikey": API_KEY, "task": "filesystem", "answer": answer})


# ─── DATA ────────────────────────────────────────────────────────────────────

# City needs (no Polish chars in keys/values, singular nominative)
cities = {
    "opalino":   {"chleb": 45, "woda": 120, "mlotek": 6},
    "domatowo":  {"makaron": 60, "woda": 150, "lopata": 8},
    "brudzewo":  {"ryz": 55, "woda": 140, "wiertarka": 5},
    "darzlubie": {"wolowina": 25, "woda": 130, "kilof": 7},
    "celbowo":   {"kurczak": 40, "woda": 125, "mlotek": 6},
    "mechowo":   {"ziemniak": 100, "kapusta": 70, "marchew": 65, "woda": 165, "lopata": 9},
    "puck":      {"chleb": 50, "ryz": 45, "woda": 175, "wiertarka": 7},
    "karlinkowo":{"makaron": 52, "wolowina": 22, "ziemniak": 95, "woda": 155, "kilof": 6},
}

# People managing trade (from rozmowy.txt)
# Format: filename -> (display_name, city_file)
people = {
    "natan_rams":    ("Natan Rams",    "domatowo"),
    "iga_kapecka":   ("Iga Kapecka",   "opalino"),
    "rafal_kisiel":  ("Rafal Kisiel",  "brudzewo"),   # Rafał Kisiel (ł→l)
    "marta_frantz":  ("Marta Frantz",  "darzlubie"),
    "oskar_radtke":  ("Oskar Radtke",  "celbowo"),
    "eliza_redmann": ("Eliza Redmann", "mechowo"),
    "damian_kroll":  ("Damian Kroll",  "puck"),
    "lena_konkel":   ("Lena Konkel",   "karlinkowo"),
}

# Goods for sale: item → [list of selling cities]
# Sources: transakcje.txt - left side is the seller
goods = {
    "chleb":     ["domatowo", "celbowo", "brudzewo"],
    "ryz":       ["darzlubie", "opalino", "karlinkowo"],
    "ziemniak":  ["domatowo", "darzlubie"],
    "maka":      ["brudzewo", "mechowo"],
    "kilof":     ["puck", "celbowo", "mechowo"],
    "lopata":    ["brudzewo", "puck"],
    "makaron":   ["opalino"],
    "wiertarka": ["domatowo", "karlinkowo"],
    "marchew":   ["puck"],
    "mlotek":    ["karlinkowo", "mechowo"],
    "wolowina":  ["opalino"],
    "kurczak":   ["darzlubie"],
    "kapusta":   ["celbowo"],
}


def build_batch():
    ops = []

    # 1. Reset
    ops.append({"action": "reset"})

    # 2. Create directories
    for d in ["/miasta", "/osoby", "/towary"]:
        ops.append({"action": "createDirectory", "path": d})

    # 3. City files (must exist before person/goods files link to them)
    for city, needs in cities.items():
        ops.append({
            "action": "createFile",
            "path": f"/miasta/{city}",
            "content": json.dumps(needs, ensure_ascii=True),
        })

    # 4. Person files
    for filename, (display_name, city) in people.items():
        content = f"{display_name}\n[{city.capitalize()}](/miasta/{city})"
        ops.append({
            "action": "createFile",
            "path": f"/osoby/{filename}",
            "content": content,
        })

    # 5. Goods files
    for good, sellers in goods.items():
        links = "\n".join(f"[{c.capitalize()}](/miasta/{c})" for c in sellers)
        ops.append({
            "action": "createFile",
            "path": f"/towary/{good}",
            "content": links,
        })

    return ops


def main():
    ops = build_batch()
    print(f"Total operations: {len(ops)}")
    for op in ops:
        print(f"  {op['action']:20s} {op.get('path', '')}")

    print("\nSending batch...")
    r = fs(ops)
    print(json.dumps(r, indent=2, ensure_ascii=False))

    # List the created structure
    print("\n--- Listing filesystem ---")
    for path in ["/", "/miasta", "/osoby", "/towary"]:
        r2 = fs({"action": "listFiles", "path": path})
        print(f"\n{path}:")
        print(json.dumps(r2, indent=2, ensure_ascii=False)[:500])

    # Call done
    print("\n--- Calling done ---")
    r3 = fs({"action": "done"})
    print(json.dumps(r3, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
