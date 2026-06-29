import os
#!/usr/bin/env python3
"""
radiomonitoring task - intercept radio signals and build a report about "Syjon".

Pipeline:
1. Start session
2. Collect all signals (text transcriptions + binary attachments)
3. Analyze locally (text: direct; binary: decode + inspect by type)
4. Use Claude API for anything needing intelligence
5. Transmit final report
"""

import json, ssl, base64, os, re, time
from urllib.request import urlopen, Request
from pathlib import Path

API_KEY = os.environ["AG3NTS_API_KEY"]
VERIFY = "https://hub.ag3nts.org/verify"
SSL_CTX = ssl._create_unverified_context()

# Save captured data here for inspection
CAPTURE_DIR = Path("/tmp/radiomonitoring")
CAPTURE_DIR.mkdir(exist_ok=True)


def post(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = Request(VERIFY, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, context=SSL_CTX, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        if hasattr(e, "read"):
            body = e.read().decode()
            print(f"HTTP Error: {body[:300]}")
            try:
                return json.loads(body)
            except Exception:
                pass
        raise


def rm(action_payload: dict) -> dict:
    return post({"apikey": API_KEY, "task": "radiomonitoring", "answer": action_payload})


def is_noise(text: str) -> bool:
    """Detect if text is just radio noise (no useful content)."""
    if not text or len(text.strip()) < 5:
        return True
    # Patterns indicating noise
    noise_patterns = [
        r'^[.\-_~*+=/\\|#@!%^&()\[\]{}]+$',  # only symbols
        r'^(\s*[a-z]{1,3}\s*)+$',              # only short random tokens
        r'szum|noise|static|šum|тшр',          # explicit noise words
    ]
    stripped = text.strip()
    for pat in noise_patterns:
        if re.match(pat, stripped, re.IGNORECASE):
            return True
    # Check entropy (too random = noise)
    words = stripped.split()
    if len(words) < 3:
        return True
    return False


def mime_from_meta(meta: str) -> str:
    """Extract MIME type from meta field."""
    if not meta:
        return "unknown"
    meta_lower = meta.lower()
    if "json" in meta_lower:
        return "json"
    if "pdf" in meta_lower:
        return "pdf"
    if "image" in meta_lower or "png" in meta_lower or "jpg" in meta_lower or "jpeg" in meta_lower:
        return "image"
    if "audio" in meta_lower or "mp3" in meta_lower or "wav" in meta_lower:
        return "audio"
    if "text" in meta_lower:
        return "text"
    if "zip" in meta_lower:
        return "zip"
    return "binary"


def decode_attachment(b64_data: str, meta: str, idx: int) -> tuple[str, bytes]:
    """Decode base64 attachment, save locally, return (mime_type, raw_bytes)."""
    try:
        raw = base64.b64decode(b64_data)
        mime = mime_from_meta(meta)

        # Detect from magic bytes
        if raw[:4] == b'%PDF':
            mime = "pdf"
        elif raw[:8] == b'\x89PNG\r\n\x1a\n':
            mime = "image"
        elif raw[:2] in (b'\xff\xd8', ):
            mime = "image"  # JPEG
        elif raw[:2] == b'PK':
            mime = "zip"
        elif raw[:4] == b'RIFF':
            mime = "audio"  # WAV

        ext = {"json": "json", "pdf": "pdf", "image": "png", "audio": "wav", "zip": "zip", "text": "txt"}.get(mime, "bin")
        out_path = CAPTURE_DIR / f"attachment_{idx:03d}.{ext}"
        out_path.write_bytes(raw)
        print(f"    Saved {len(raw)} bytes → {out_path}")

        # Try to read as text if JSON or text
        if mime in ("json", "text"):
            try:
                text = raw.decode("utf-8")
                print(f"    Content preview: {text[:300]}")
            except Exception:
                pass

        return mime, raw
    except Exception as e:
        print(f"    Decode error: {e}")
        return "error", b""


def collect_signals() -> tuple[list[str], list[tuple[str, bytes, int]]]:
    """
    Returns (transcriptions, attachments).
    transcriptions: list of useful text strings
    attachments: list of (mime, raw_bytes, index)
    """
    transcriptions = []
    attachments = []
    idx = 0

    print("Starting session...")
    r = rm({"action": "start"})
    print(f"Start: {r.get('message', r)}")

    print("\nListening for signals...")
    while True:
        r = rm({"action": "listen"})
        code = r.get("code", 0)
        msg = r.get("message", "")
        print(f"\n[Signal {idx}] code={code} msg={msg[:80]}")

        # Check if done
        if code in (200, 201) or "enough" in msg.lower() or "done" in msg.lower() or "finished" in msg.lower() or "no more" in msg.lower() or "koniec" in msg.lower() or "wystarczy" in msg.lower():
            print("  → Session complete!")
            # Check if this last signal also has content
            if "transcription" in r:
                txt = r["transcription"]
                if not is_noise(txt):
                    print(f"  TEXT: {txt[:200]}")
                    transcriptions.append(txt)
            if "attachment" in r:
                mime, raw = decode_attachment(r["attachment"], r.get("meta", ""), idx)
                attachments.append((mime, raw, idx))
            break

        # Process transcription
        if "transcription" in r:
            txt = r["transcription"]
            if is_noise(txt):
                print(f"  NOISE: {txt[:60]}")
            else:
                print(f"  TEXT: {txt[:200]}")
                transcriptions.append(txt)

        # Process attachment
        if "attachment" in r:
            fs = r.get("filesize", len(r["attachment"]))
            print(f"  ATTACHMENT: meta={r.get('meta','?')} filesize={fs}")
            mime, raw = decode_attachment(r["attachment"], r.get("meta", ""), idx)
            attachments.append((mime, raw, idx))

        idx += 1
        time.sleep(0.3)

    return transcriptions, attachments


def extract_info_from_text(texts: list[str]) -> dict:
    """Extract Syjon-related info from text transcriptions."""
    info = {}
    all_text = "\n".join(texts)

    print(f"\n--- All transcriptions ({len(texts)} pieces) ---")
    for i, t in enumerate(texts):
        print(f"[{i}] {t}")

    # Save all text for analysis
    (CAPTURE_DIR / "all_transcriptions.txt").write_text(all_text, encoding="utf-8")
    return info


def analyze_json_attachment(raw: bytes, idx: int) -> dict:
    """Parse JSON attachment and extract relevant info."""
    try:
        data = json.loads(raw.decode("utf-8"))
        print(f"  JSON[{idx}]: {json.dumps(data, ensure_ascii=False)[:500]}")
        return data
    except Exception as e:
        print(f"  JSON parse error: {e}")
        return {}


def main():
    # Collect all signals
    transcriptions, attachments = collect_signals()

    print(f"\n=== COLLECTION COMPLETE ===")
    print(f"Transcriptions: {len(transcriptions)}")
    print(f"Attachments: {len(attachments)}")

    # Extract info from texts
    extract_info_from_text(transcriptions)

    # Analyze attachments
    json_data = []
    for mime, raw, idx in attachments:
        print(f"\nAnalyzing attachment[{idx}] type={mime} size={len(raw)}")
        if mime == "json":
            d = analyze_json_attachment(raw, idx)
            if d:
                json_data.append(d)
        elif mime == "image":
            print(f"  Image file saved, needs vision model analysis")
        elif mime == "pdf":
            print(f"  PDF file saved at {CAPTURE_DIR}/attachment_{idx:03d}.pdf")
        elif mime == "audio":
            print(f"  Audio file saved")
        else:
            # Try as text anyway
            try:
                text = raw.decode("utf-8", errors="replace")
                print(f"  As text: {text[:300]}")
            except Exception:
                pass

    # Print all JSON data found
    print(f"\n=== JSON ATTACHMENTS ({len(json_data)}) ===")
    for d in json_data:
        print(json.dumps(d, indent=2, ensure_ascii=False)[:1000])

    print(f"\nAll files saved to {CAPTURE_DIR}")
    print("Now analyze the data and prepare the report...")


if __name__ == "__main__":
    main()
