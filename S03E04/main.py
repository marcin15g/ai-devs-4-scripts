import os
#!/usr/bin/env python3
"""S03E04 – negotiations: expose tool endpoints for the ag3nts agent."""

import csv, json, re, ssl, time
import certifi
from collections import defaultdict
from urllib.request import urlopen, Request
from flask import Flask, request, jsonify
from pyngrok import ngrok

# ── config ──────────────────────────────────────────────────────────────
API_KEY = os.environ["AG3NTS_API_KEY"]
VERIFY_URL = "https://hub.ag3nts.org/verify"
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# ── load data ───────────────────────────────────────────────────────────
cities = {}          # code -> name
city_codes = {}      # name_lower -> code
items = {}           # code -> name
item_names = {}      # name_lower -> code

with open(f"{DATA_DIR}/cities.csv") as f:
    for r in csv.DictReader(f):
        cities[r["code"]] = r["name"]
        city_codes[r["name"].lower()] = r["code"]

with open(f"{DATA_DIR}/items.csv") as f:
    for r in csv.DictReader(f):
        items[r["code"]] = r["name"]
        item_names[r["name"].lower()] = r["code"]

# item_code -> set of city_codes
item_to_cities = defaultdict(set)
# city_code -> set of item_codes
city_to_items = defaultdict(set)

with open(f"{DATA_DIR}/connections.csv") as f:
    for r in csv.DictReader(f):
        item_to_cities[r["itemCode"]].add(r["cityCode"])
        city_to_items[r["cityCode"]].add(r["itemCode"])

print(f"Loaded {len(cities)} cities, {len(items)} items, "
      f"{sum(len(v) for v in item_to_cities.values())} connections")

# ── helpers ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _filter_keywords(words: list[str]) -> list[str]:
    """Remove common Polish stop words and filler from query."""
    stop = {
        "potrzebuje", "potrzebuję", "szukam", "chce", "chcę", "kupić", "kupic",
        "znaleźć", "znalezc", "gdzie", "czy", "jest", "są", "sa", "jakiś",
        "jakis", "jakieś", "jakies", "proszę", "prosze", "o", "w", "z", "do",
        "na", "i", "lub", "albo", "oraz", "to", "ten", "ta", "te", "tego",
        "tej", "tych", "tym", "mi", "mnie", "nam", "nas", "się", "sie",
        "być", "byc", "może", "moze", "będzie", "bedzie", "długości",
        "dlugosci", "typu", "rodzaju", "jakości", "jakosci", "może", "moze",
        "metrów", "metrow", "sztuk", "sztuki", "kawałek", "kawalek",
    }
    return [w for w in words if w not in stop and len(w) > 1]


def _stem_match(keyword: str, text: str) -> bool:
    """Check if keyword (possibly inflected Polish) matches anything in text.
    Try full match first, then progressively shorter prefixes (min 3 chars)."""
    if keyword in text:
        return True
    # Try prefix matching for Polish declension (rezystora -> rezystor)
    min_len = max(3, len(keyword) - 3)
    for length in range(len(keyword) - 1, min_len - 1, -1):
        prefix = keyword[:length]
        if prefix in text:
            return True
    return False


def search_items(query: str) -> list[tuple[str, str, int]]:
    """Return list of (item_code, item_name, score) matching the query keywords.
    Score = number of keywords matched. Results sorted by score desc."""
    q = _normalize(query)
    keywords = _filter_keywords(q.split())
    if not keywords:
        keywords = q.split()

    results = []
    for name_lower, code in item_names.items():
        score = sum(1 for kw in keywords if _stem_match(kw, name_lower))
        if score > 0:
            results.append((code, items[code], score))

    # Sort by score descending
    results.sort(key=lambda x: -x[2])

    # Return only the best matches (highest score)
    if results:
        max_score = results[0][2]
        if max_score >= 2:
            results = [r for r in results if r[2] == max_score]

    return results


def cities_for_item(query: str) -> str:
    """Given a natural-language item query, return cities that sell matching items."""
    matches = search_items(query)
    if not matches:
        return json.dumps({"output": "Nie znaleziono przedmiotów pasujących do zapytania."})

    # Collect cities for all matching items
    city_set = set()
    matched_names = []
    for code, name, score in matches:
        for cc in item_to_cities.get(code, set()):
            city_set.add(cities[cc])
        matched_names.append(name)

    # Build response, keep under 500 bytes
    city_list = sorted(city_set)
    output = ", ".join(city_list)

    resp = {"output": output}
    encoded = json.dumps(resp, ensure_ascii=False).encode("utf-8")
    # Trim if too long
    while len(encoded) > 500 and city_list:
        city_list.pop()
        output = ", ".join(city_list)
        resp = {"output": output}
        encoded = json.dumps(resp, ensure_ascii=False).encode("utf-8")

    return json.dumps(resp, ensure_ascii=False)


def items_in_city(query: str) -> str:
    """Given a city name, return items available there."""
    q = _normalize(query)
    # Find city
    found_code = None
    for name_lower, code in city_codes.items():
        if q in name_lower or name_lower in q:
            found_code = code
            break
    if not found_code:
        return json.dumps({"output": "Nie znaleziono miasta."})

    item_list = sorted(items[ic] for ic in city_to_items.get(found_code, set()))
    output = ", ".join(item_list)
    resp = {"output": output}
    encoded = json.dumps(resp, ensure_ascii=False).encode("utf-8")
    if len(encoded) > 500:
        # Truncate
        while len(encoded) > 500 and item_list:
            item_list.pop()
            output = ", ".join(item_list)
            resp = {"output": output}
            encoded = json.dumps(resp, ensure_ascii=False).encode("utf-8")
    return json.dumps(resp, ensure_ascii=False)


# ── Flask app ───────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route("/search", methods=["POST"])
def handle_search():
    """Tool 1: search for items and return cities that sell them."""
    data = request.get_json(force=True)
    query = data.get("params", "")
    print(f"[search] query={query!r}")
    result = cities_for_item(query)
    print(f"[search] result={result!r}")
    return app.response_class(result, content_type="application/json")


@app.route("/city", methods=["POST"])
def handle_city():
    """Tool 2: list items available in a given city."""
    data = request.get_json(force=True)
    query = data.get("params", "")
    print(f"[city] query={query!r}")
    result = items_in_city(query)
    print(f"[city] result={result!r}")
    return app.response_class(result, content_type="application/json")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── helpers for verification ────────────────────────────────────────────

def _post(url, payload):
    data = json.dumps(payload).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, context=SSL_CTX) as resp:
            body = resp.read().decode()
    except Exception as e:
        if hasattr(e, "read"):
            body = e.read().decode()
        else:
            body = str(e)
    print(body)
    return body


def register_tools(base_url: str):
    payload = {
        "apikey": API_KEY,
        "task": "negotiations",
        "answer": {
            "tools": [
                {
                    "URL": f"{base_url}/search",
                    "description": (
                        "Szuka przedmiotów i zwraca miasta, które je sprzedają. "
                        "W params podaj słowa kluczowe przedmiotu, np. 'rezystor 10 ohm' "
                        "lub 'dioda LED czerwona'. Jedno zapytanie = jeden przedmiot."
                    ),
                },
            ]
        },
    }
    print("Registering tools...")
    return _post(VERIFY_URL, payload)


def check_result():
    payload = {
        "apikey": API_KEY,
        "task": "negotiations",
        "answer": {"action": "check"},
    }
    return _post(VERIFY_URL, payload)


# ── main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tunnel = ngrok.connect(3000)
    public_url = tunnel.public_url
    print(f"Public URL: {public_url}")

    # Register tools
    register_tools(public_url)

    print("Server running on port 3000. Press Ctrl+C to stop.")
    print("After ~60 seconds, run check or look at debug panel.")
    app.run(host="0.0.0.0", port=3000)
