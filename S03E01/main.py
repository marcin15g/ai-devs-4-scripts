"""
S03E01 – Sensor Anomaly Detection Agent
Analyzes sensor readings from a power plant to find anomalies:
  - Measurement data out of valid range
  - Inactive sensor fields that should be 0 but aren't
  - Operator notes claiming OK when data is bad
  - Operator notes claiming problems when data is OK
Submits anomaly file IDs to /verify endpoint.
"""

import json
import os
import ssl
import certifi
import time
import urllib.request
import zipfile

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
SENSORS_URL = "https://hub.ag3nts.org/dane/sensors.zip"

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SENSORS_DIR = os.path.join(SCRIPT_DIR, "sensors")


# ── Valid ranges for active sensor fields ────────────────────────────────────

RANGES = {
    "temperature_K": (553, 873),
    "pressure_bar": (60, 160),
    "water_level_meters": (5.0, 15.0),
    "voltage_supply_v": (229.0, 231.0),
    "humidity_percent": (40.0, 80.0),
}

# Mapping from sensor_type component to its measurement fields
SENSOR_FIELDS = {
    "temperature": ["temperature_K"],
    "pressure": ["pressure_bar"],
    "water": ["water_level_meters"],
    "voltage": ["voltage_supply_v"],
    "humidity": ["humidity_percent"],
}

# Phrases indicating the operator is reporting a problem
PROBLEM_PHRASES = [
    "i am not comfortable",
    "i am seeing an unexpected",
    "i can see a clear irregularity",
    "numbers feel inconsistent",
    "report does not look healthy",
    "signal profile looks unusual",
    "readings look suspicious",
    "check did not look right",
    "state looks unstable",
    "something is clearly off",
    "current result seems unreliable",
    "latest behavior is concerning",
    "situation requires attention",
    "visible anomaly",
    "output quality is doubtful",
    "not the pattern i expected",
    "report raises serious doubts",
    "questionable behavior",
    "something doesn't look",
    "this does not look right",
    "i have doubts",
    "i cannot approve",
]


# ── HTTP helpers ─────────────────────────────────────────────────────────────

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


def download_sensors():
    """Download and extract sensor data if not already present."""
    if os.path.isdir(SENSORS_DIR) and len(os.listdir(SENSORS_DIR)) > 0:
        print(f"Sensors already extracted: {len(os.listdir(SENSORS_DIR))} files")
        return

    zip_path = os.path.join(SCRIPT_DIR, "sensors.zip")
    if not os.path.exists(zip_path):
        print(f"Downloading sensors from {SENSORS_URL} ...")
        req = urllib.request.Request(SENSORS_URL)
        with urllib.request.urlopen(req, timeout=120, context=_SSL_CTX) as resp:
            with open(zip_path, "wb") as f:
                f.write(resp.read())
        print(f"  Downloaded: {os.path.getsize(zip_path)} bytes")

    print("Extracting sensors ...")
    os.makedirs(SENSORS_DIR, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(SENSORS_DIR)
    # Handle nested directory (zip may extract into sensors/sensors/)
    nested = os.path.join(SENSORS_DIR, "sensors")
    if os.path.isdir(nested):
        for fname in os.listdir(nested):
            os.rename(os.path.join(nested, fname), os.path.join(SENSORS_DIR, fname))
        os.rmdir(nested)
    print(f"  Extracted: {len([f for f in os.listdir(SENSORS_DIR) if f.endswith('.json')])} JSON files")


# ── Anomaly detection ────────────────────────────────────────────────────────

def check_data_anomalies(data: dict) -> list[str]:
    """Check if sensor data has measurement anomalies. Returns list of issues."""
    sensor_types = data["sensor_type"].split("/")
    active_fields = set()
    for st in sensor_types:
        active_fields.update(SENSOR_FIELDS.get(st, []))

    issues = []

    # Check 1: Active fields must be within valid range
    for field in active_fields:
        val = data[field]
        lo, hi = RANGES[field]
        if val < lo or val > hi:
            issues.append(f"{field}={val} out of range [{lo},{hi}]")

    # Check 2: Inactive fields must be 0
    all_fields = set(RANGES.keys())
    inactive_fields = all_fields - active_fields
    for field in inactive_fields:
        if data[field] != 0:
            issues.append(f"{field}={data[field]} should be 0 (sensor_type={data['sensor_type']})")

    return issues


def note_reports_problem(note: str) -> bool:
    """Check if operator note reports a problem/anomaly."""
    nl = note.lower()
    return any(phrase in nl for phrase in PROBLEM_PHRASES)


def find_all_anomalies() -> list[str]:
    """Scan all sensor files and return IDs of those with anomalies."""
    anomalies = []

    json_files = sorted(f for f in os.listdir(SENSORS_DIR) if f.endswith(".json"))
    print(f"Scanning {len(json_files)} sensor files ...")

    data_bad_count = 0
    note_mismatch_count = 0

    for fname in json_files:
        fid = fname.replace(".json", "")
        filepath = os.path.join(SENSORS_DIR, fname)
        with open(filepath) as f:
            data = json.load(f)

        data_issues = check_data_anomalies(data)
        operator_reports_problem = note_reports_problem(data["operator_notes"])

        is_anomaly = False
        reason = ""

        if data_issues:
            # Data is bad — anomaly regardless of what operator says
            is_anomaly = True
            data_bad_count += 1
            reason = f"DATA_BAD: {'; '.join(data_issues)}"

        elif operator_reports_problem:
            # Operator says problem but data is actually OK
            is_anomaly = True
            note_mismatch_count += 1
            reason = f"NOTE_MISMATCH: operator reports problem but data is OK"

        if is_anomaly:
            anomalies.append(fid)
            print(f"  ANOMALY {fid}: {reason}")

    print(f"\nSummary:")
    print(f"  Data anomalies: {data_bad_count}")
    print(f"  Note mismatches (operator wrong): {note_mismatch_count}")
    print(f"  Total anomalies: {len(anomalies)}")

    return anomalies


# ── Submit answer ────────────────────────────────────────────────────────────

def submit_answer(anomaly_ids: list[str]) -> str:
    """Submit anomaly IDs to the verification endpoint."""
    payload = {
        "apikey": API_KEY,
        "task": "evaluation",
        "answer": {
            "recheck": anomaly_ids,
        },
    }
    print(f"\nSubmitting {len(anomaly_ids)} anomaly IDs to /verify ...")
    result = _post(VERIFY_URL, payload)
    print(f"Response: {result}")
    return result


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> str:
    # Step 1: Download sensor data
    download_sensors()

    # Step 2: Find all anomalies programmatically
    anomaly_ids = find_all_anomalies()

    if not anomaly_ids:
        print("No anomalies found!")
        return "No anomalies"

    # Step 3: Submit answer
    result = submit_answer(sorted(anomaly_ids))

    if "FLG:" in result:
        print(f"\n{'='*60}")
        print(f"FLAG FOUND!")
        print(f"{'='*60}")

    return result


if __name__ == "__main__":
    result = run()
    print(f"\nFinal result: {result}")
