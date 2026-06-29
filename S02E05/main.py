"""
S02E05 – Drone Bombing Agent
Analyzes a map of the Żarnowiec power plant area, locates the dam sector,
and sends drone instructions to bomb the dam (not the power plant) via /verify.
"""

import base64
import json
import os
import ssl
import time
import urllib.request

import anthropic

API_KEY = os.environ["AG3NTS_API_KEY"]

LLM_BASE_URL = (
    os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL", "").rstrip("/")
    or os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    or None
)
LLM_API_KEY = (
    os.environ.get("ANTHROPIC_FOUNDRY_API_KEY")
    or os.environ.get("ANTHROPIC_API_KEY")
    or None
)
LLM_MODEL = (
    os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
    or os.environ.get("DEFAULT_LLM_MODEL")
    or "claude-sonnet-4-5"
)

VERIFY_URL = "https://hub.ag3nts.org/verify"
MAP_URL = f"https://hub.ag3nts.org/data/{API_KEY}/drone.png"
POWER_PLANT_CODE = "PWR6132PL"

_SSL_CTX = ssl._create_unverified_context()


# ── HTTP helper with retry ───────────────────────────────────────────────────

def _post(url: str, payload: dict, retries: int = 3) -> str:
    data = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()
            except Exception:
                pass
            if e.code == 429 and attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"    [rate-limited, waiting {wait}s before retry {attempt+2}/{retries}]")
                time.sleep(wait)
                continue
            return body or json.dumps({"error": str(e)})
        except Exception as e:
            return json.dumps({"error": str(e)})
    return json.dumps({"error": "max retries exceeded"})


# ── Tools ────────────────────────────────────────────────────────────────────

def send_drone_instructions(instructions: list[str]) -> str:
    """Send drone instructions to the /verify endpoint."""
    payload = {
        "apikey": API_KEY,
        "task": "drone",
        "answer": {
            "instructions": instructions,
        },
    }
    print(f"  Sending instructions: {instructions}")
    return _post(VERIFY_URL, payload)


# ── Tool schemas ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "send_drone_instructions",
        "description": (
            "Send a sequence of drone instructions to the /verify endpoint. "
            "Returns the API response which may contain error messages or a flag {FLG:...}. "
            "If the API returns an error, read it carefully and adjust instructions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instructions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of drone instruction strings to execute in sequence",
                },
            },
            "required": ["instructions"],
        },
    },
]


# ── Tool dispatcher ──────────────────────────────────────────────────────────

def execute_tool(name: str, tool_input: dict) -> str:
    if name == "send_drone_instructions":
        return send_drone_instructions(tool_input["instructions"])
    return json.dumps({"error": f"Unknown tool: {name}"})


# ── Agentic loop ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""\
You are a drone operator programming an armed drone for a mission.

## Context
You must program the drone to bomb the DAM near the Żarnowiec power plant (NOT the power plant itself).
The goal is to release water from the dam to cool the reactor cores.

## Map Grid (4 columns × 3 rows, (1,1) = top-left)
The map you see is divided by red lines into a 4×3 grid:
- The POWER PLANT (industrial buildings, circular reactor) occupies the CENTER: sectors around (1,3), (2,2), (2,3), (3,2), (3,3)
- The DAM is at an EDGE sector where you see intensified green/blue WATER coloring
- Look carefully at the RIGHT side and corners for bright water areas — that's the dam

## CRITICAL: Identifying the Dam
- The dam has INTENSIFIED water color (bright green/blue/cyan) — it will stand out from normal terrain
- The dam is NOT in the center (that's the power plant)
- Look at EDGE sectors: (1,1), (4,1), (1,2), (4,2), (1,3), (4,3) for water features
- The right side of the map (column 4) has green vegetation and water — the dam is likely there

## Drone API Commands
**REQUIRED before flyToLocation:** destination object, landing sector, altitude

- `hardReset` - ALWAYS start with this to clear any previous state
- `setDestinationObject({POWER_PLANT_CODE})` - Set destination (required)
- `set(x,y)` - Landing sector coordinates — THIS determines where the bomb actually drops
- `set(Xm)` - Altitude (1m-100m, required)
- `set(engineON)` / `set(engineOFF)` - Engine control
- `set(0%)` to `set(100%)` - Power level
- `set(destroy)` / `set(video)` / `set(image)` / `set(return)` - Mission objective
- `flyToLocation` - Execute the mission (put this LAST)
- `getConfig` - Check current configuration
- `selfCheck`, `calibrateCompass`, `calibrateGPS` - Diagnostics

## Strategy
1. Analyze the map image. Find the sector with intensified water color (the dam). It's on the EDGE of the map, not in the center.
2. Start with `hardReset` to ensure clean state.
3. Send a COMPLETE instruction sequence in ONE call:
   hardReset, setDestinationObject({POWER_PLANT_CODE}), set(x,y), set(Xm), set(engineON), set(100%), set(destroy), flyToLocation
4. If the API returns error code -880 ("pretending to destroy power plants"), that means your coordinates HIT THE POWER PLANT. Try a DIFFERENT sector — move to an edge sector with water.
5. If you get error -892 about owner, try setOwner with a Polish name.
6. If you get any other error, read it and adapt.
7. When {{FLG:...}} appears, the mission is complete.

## IMPORTANT
- Error -880 means your set(x,y) coordinates point at the power plant, NOT the dam. Try different edge sectors.
- ALWAYS include hardReset at the start of every attempt to clear previous state.
- The bomb drops at the set(x,y) sector, regardless of setDestinationObject.
"""


def run() -> str:
    client_kwargs = {}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    if LLM_API_KEY:
        client_kwargs["api_key"] = LLM_API_KEY
    client = anthropic.Anthropic(**client_kwargs)

    # Load the map image and encode as base64 (URL sources not supported by all providers)
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drone.png")
    if os.path.exists(local_path):
        print(f"Loading map from local file {local_path} ...")
        with open(local_path, "rb") as f:
            image_bytes = f.read()
    else:
        print(f"Downloading map from {MAP_URL} (this may take a while) ...")
        req = urllib.request.Request(MAP_URL)
        with urllib.request.urlopen(req, timeout=120, context=_SSL_CTX) as resp:
            image_bytes = resp.read()
        # Cache locally for next run
        with open(local_path, "wb") as f:
            f.write(image_bytes)
    image_b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    media_type = "image/png"
    print(f"  Map loaded: {len(image_bytes)} bytes")

    # Initial message includes the map image for analysis
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Here is the map of the power plant area (4 columns × 3 rows grid, (1,1) = top-left). "
                        "The power plant is in the CENTER sectors. The DAM has intensified water color (bright green/blue) "
                        "and is at an EDGE sector. Look carefully for the bright water area — that's where you need to drop the bomb. "
                        "Start with hardReset, then send a complete instruction set targeting the dam sector."
                    ),
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64,
                    },
                },
            ],
        }
    ]

    max_iterations = 20
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"Iteration {iteration}/{max_iterations}")
        print(f"{'='*60}")

        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        for block in response.content:
            if block.type == "text":
                print(f"\nAgent: {block.text}")

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    return block.text
            return "(no text response)"

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"\n  → {block.name}({json.dumps(block.input, ensure_ascii=False)})")
                    result = execute_tool(block.name, dict(block.input))
                    print(f"  ← {result[:1000]}{'...' if len(result) > 1000 else ''}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                    if "FLG:" in result:
                        print(f"\n{'='*60}")
                        print(f"FLAG FOUND: {result}")
                        print(f"{'='*60}")
                        return result

            messages.append({"role": "user", "content": tool_results})
            continue

        print(f"Unexpected stop_reason: {response.stop_reason}")
        break

    return "(max iterations reached)"


if __name__ == "__main__":
    result = run()
    print(f"\nFinal result: {result}")
