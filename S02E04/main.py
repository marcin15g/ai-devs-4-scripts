"""
S02E04 – Mailbox Agent
Searches an operator's mailbox via the zmail API to find:
  1. date       – planned attack date (YYYY-MM-DD)
  2. password   – employee system password
  3. confirmation_code – security ticket code (SEC- + 32 chars)
Then submits the answer to the hub /verify endpoint.
"""

import json
import os
import ssl
import time
import urllib.request

import anthropic

API_KEY = os.environ["AG3NTS_API_KEY"]

# LiteLLM / Foundry proxy configuration (set via env vars)
LLM_BASE_URL = os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL", "").rstrip("/") or None
LLM_API_KEY = os.environ.get("ANTHROPIC_FOUNDRY_API_KEY") or None
LLM_MODEL = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-5")
ZMAIL_URL = "https://hub.ag3nts.org/api/zmail"
VERIFY_URL = "https://hub.ag3nts.org/verify"

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
            if e.code == 429 and attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"    [rate-limited, waiting {wait}s before retry {attempt+2}/{retries}]")
                time.sleep(wait)
                continue
            return json.dumps({"error": str(e)})
        except Exception as e:
            return json.dumps({"error": str(e)})
    return json.dumps({"error": "max retries exceeded"})


# ── Generic zmail caller – the agent decides action & params ─────────────────

def zmail_call(action: str, **kwargs) -> str:
    """Call the zmail API with any action and parameters."""
    payload = {"apikey": API_KEY, "action": action}
    payload.update(kwargs)
    return _post(ZMAIL_URL, payload)


def verify_answer(password: str, date: str, confirmation_code: str) -> str:
    """Submit the three found values to the hub for verification."""
    return _post(VERIFY_URL, {
        "apikey": API_KEY,
        "task": "mailbox",
        "answer": {
            "password": password,
            "date": date,
            "confirmation_code": confirmation_code,
        },
    })


# ── Tool schemas ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "zmail_call",
        "description": (
            "Call the zmail API with any action and parameters. "
            "First use action='help' to discover all available actions and their exact parameter names. "
            "Common actions: help, getInbox, search (with 'query' param), and an action to read "
            "full message content by ID (discover the exact name via help). "
            "Search supports Gmail-like operators: from:, to:, subject:, OR, AND."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "The API action name (e.g. help, getInbox, search, ...)"},
                "query": {"type": "string", "description": "Search query for the search action"},
                "page": {"type": "integer", "description": "Page number for pagination"},
                "perPage": {"type": "integer", "description": "Results per page"},
                "id": {"type": "string", "description": "Message ID (for reading a specific message)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "verify_answer",
        "description": (
            "Submit the three extracted values to the hub for verification. "
            "Returns a flag {FLG:...} if all values are correct, or feedback about which are wrong."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "password": {"type": "string", "description": "The employee system password found in emails"},
                "date": {"type": "string", "description": "Attack date in YYYY-MM-DD format"},
                "confirmation_code": {
                    "type": "string",
                    "description": "Security ticket confirmation code (SEC- + 32 chars = 36 chars total)",
                },
            },
            "required": ["password", "date", "confirmation_code"],
        },
    },
]


# ── Tool dispatcher ──────────────────────────────────────────────────────────

def execute_tool(name: str, tool_input: dict) -> str:
    if name == "zmail_call":
        action = tool_input.pop("action")
        # Remove None values
        kwargs = {k: v for k, v in tool_input.items() if v is not None}
        return zmail_call(action, **kwargs)
    if name == "verify_answer":
        return verify_answer(tool_input["password"], tool_input["date"], tool_input["confirmation_code"])
    return json.dumps({"error": f"Unknown tool: {name}"})


# ── Agentic loop ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an intelligence agent searching through an operator's email inbox via the zmail API.

Your mission: find three pieces of information hidden in the emails:
1. **date** – when the security department plans to attack the power plant (YYYY-MM-DD)
2. **password** – the employee system password
3. **confirmation_code** – confirmation code from a security department ticket (format: SEC- + 32 characters = 36 total)

What you know:
- A person named Wiktor sent an email from a proton.me domain (he is an informant)
- The API search supports Gmail-like operators: from:, to:, subject:, OR, AND
- The inbox is active – new messages may arrive at any time

CRITICAL STRATEGY – follow this exact order:
1. FIRST call zmail_call with action="help" to discover ALL available actions and their EXACT parameter names. Read the response carefully – the action for reading a single message may not be called "getMessage".
2. Use targeted searches: start with "from:proton.me" to find Wiktor's email, then "from:security" or "SEC-" for the ticket.
3. ALWAYS read full message content using the correct read-message action BEFORE drawing any conclusions. Search results only show metadata/snippets, not full bodies.
4. Search for password-related emails: try "hasło", "password", "logowanie", "system pracowniczy", "credentials", "konto".
5. Be economical with API calls – plan searches carefully to avoid rate limiting.
6. Once you have all three values, call verify_answer.
7. If verification says some values are wrong, keep searching with different terms or retry (new messages may have arrived).
8. If you get rate-limited (429), wait and retry – the tool has built-in retry logic.
"""


def run() -> str:
    client_kwargs = {}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    if LLM_API_KEY:
        client_kwargs["api_key"] = LLM_API_KEY
    client = anthropic.Anthropic(**client_kwargs)
    messages = [{"role": "user", "content": "Begin the mission. Start by calling help to discover available API actions."}]

    max_iterations = 40
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

        # Print any text blocks
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
                    print(f"  ← {result[:800]}{'...' if len(result) > 800 else ''}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                    # Check if we got a flag
                    if block.name == "verify_answer" and "FLG:" in result:
                        print(f"\n{'='*60}")
                        print(f"FLAG FOUND: {result}")
                        print(f"{'='*60}")
                        return result

            messages.append({"role": "user", "content": tool_results})
            continue

        print(f"Unexpected stop_reason: {response.stop_reason}")
        break

    return "(max iterations reached)"


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = run()
    print(f"\nFinal result: {result}")
