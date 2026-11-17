"""
Example: Claude API with Tool Use
Demonstrates calling Claude with a tool that makes an external HTTP request.
"""

import json
import os
import ssl
import certifi
import urllib.parse
import urllib.request
import anthropic

# Verify TLS against certifi's CA bundle (macOS Python may lack system certs)
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


# ── Tool implementation ────────────────────────────────────────────────────────

def get_location(name: str, surname: str) -> str:
    """Look up the location of a person by name and surname."""
    api_key = os.environ["AG3NTS_API_KEY"]
    url = "https://hub.ag3nts.org/api/location"
    payload = json.dumps({"apikey": api_key, "name": name, "surname": surname}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as response:
            return response.read().decode()
    except Exception as e:
        return json.dumps({"error": str(e)})
    

def get_accesslevel(name: str, surname: str, birthyear: str) -> str:
    """Look up the access level of a person by name and surname."""
    api_key = os.environ["AG3NTS_API_KEY"]
    url = "https://hub.ag3nts.org/api/accesslevel"
    payload = json.dumps({"apikey": api_key, "name": name, "surname": surname, "birthYear": birthyear}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as response:
            return response.read().decode()
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_powerplants() -> str:
    """Fetch power plant locations from the hub API."""
    api_key = os.environ["AG3NTS_API_KEY"]
    url = f"https://hub.ag3nts.org/data/{api_key}/findhim_locations.json"
    try:
        with urllib.request.urlopen(url, timeout=10, context=_SSL_CTX) as response:
            return response.read().decode()
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Tool definition (JSON schema for the API) ──────────────────────────────────

TOOLS = [
    {
        "name": "get_location",
        "description": "Look up the current location of a person by their first and last name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Person's first name",
                },
                "surname": {
                    "type": "string",
                    "description": "Person's last name",
                },
            },
            "required": ["name", "surname"],
        },
    },
    {
        "name": "get_accesslevel",
        "description": "Look up the the access level of a person by their first name, last name and year of their birth",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Person's first name",
                },
                "surname": {
                    "type": "string",
                    "description": "Person's last name",
                },
                "birthyear": {
                    "type": "string",
                    "description": "Person's year of birth",
                },
            },
            "required": ["name", "surname", "birthyear"],
        },
    },
    {
        "name": "get_powerplants",
        "description": "Retrieve power plant location data from the hub API.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ── Tool dispatcher ────────────────────────────────────────────────────────────

def execute_tool(name: str, tool_input: dict) -> str:
    if name == "get_location":
        return get_location(tool_input["name"], tool_input["surname"])
    if name == "get_accesslevel":
        return get_accesslevel(tool_input["name"], tool_input["surname"], tool_input["birthyear"])
    if name == "get_powerplants":
        return get_powerplants()
    return json.dumps({"error": f"Unknown tool: {name}"})


# ── Agentic loop ───────────────────────────────────────────────────────────────

def run(user_message: str) -> str:
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            # Extract final text response
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        if response.stop_reason == "tool_use":
            # Append assistant turn (includes tool_use blocks)
            messages.append({"role": "assistant", "content": response.content})

            # Execute each requested tool and collect results
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  → Calling tool '{block.name}' with {block.input}")
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason
        break

    return "(no response)"


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    question = """
For each suspicious person:
Retrieve their list of locations using get_location.
Compare the received coordinates with the power plant coordinates using get_powerplants.
If the location is very close to one of the power plants — you have a candidate.
For that person, retrieve the accessLevel using get_accesslevel.
Identify the power plant code (format: PWR0000PL) and prepare a report.

suspicious person list:
[
  {
    "name": "Cezary",
    "surname": "Żurek",
    "gender": "M",
    "born": 1987,
    "city": "Grudziądz",
    "tags": ["transport", "praca fizyczna"]
  },
  {
    "name": "Jacek",
    "surname": "Nowak",
    "gender": "M",
    "born": 1991,
    "city": "Grudziądz",
    "tags": ["transport", "praca z ludźmi"]
  },
  {
    "name": "Oskar",
    "surname": "Sieradzki",
    "gender": "M",
    "born": 1993,
    "city": "Grudziądz",
    "tags": ["transport", "praca fizyczna"]
  },
  {
    "name": "Wojciech",
    "surname": "Bielik",
    "gender": "M",
    "born": 1986,
    "city": "Grudziądz",
    "tags": ["transport", "praca z ludźmi"]
  },
  {
    "name": "Wacław",
    "surname": "Jasiński",
    "gender": "M",
    "born": 1986,
    "city": "Grudziądz",
    "tags": ["transport", "praca z ludźmi"]
  }
]

"""
    print(f"User: {question}\n")

    answer = run(question)
    print(f"\nClaude: {answer}")
