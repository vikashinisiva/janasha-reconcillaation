"""
OCR adapter for digitizing handwritten ledgers.

Runtime path:
    image (jpg/png)  ──►  extract_ledger_rows(path)  ──►  list[dict]
                                      │
                                      ▼
                            Claude Vision (claude-sonnet-4-6 or similar)
                            via anthropic.Anthropic().messages.create()

The actual API call happens in `_extract_via_claude_vision`. The rest of
this module is plumbing: lazy import of `anthropic`, reading the API key
from env, validating + normalizing the rows Claude returns, and a clear
error path when neither the SDK nor the key is set yet.

Plug-in checklist (when the key is ready):
    1. pip install anthropic
    2. set ANTHROPIC_API_KEY=sk-ant-...   (Windows: setx ANTHROPIC_API_KEY ...)
    3. nothing else — the existing /api/cash/ocr-ledger route
       will start working automatically.
"""

import base64
import json
import os
import re
from typing import Optional

# Lazy import — let the rest of the app import this module even when
# `anthropic` isn't installed yet. The check happens at call time.
try:
    import anthropic  # type: ignore
except ImportError:
    anthropic = None  # type: ignore


# Default to a Claude 4.x model that supports vision. Override at deploy
# time via OCR_MODEL env var if you want to pin to a specific version.
DEFAULT_MODEL = os.environ.get("OCR_MODEL", "claude-sonnet-4-6")

# The columns we expect in a row (matches cash_reconcile.LEDGER_COLS minus
# the date, which we add server-side from the request).
ROW_FIELDS = ("sl", "name", "policy_no", "business", "m_id_amt",
              "cash", "bank", "note")

OCR_PROMPT = """You are looking at a handwritten cash-deposit ledger from \
Janaasha TN Nidhi Ltd, Coimbatore.

Each row records one customer payment. Columns from left to right are:
  S.No  |  Particulars (customer name)  |  Member Number  |  Policy No  |  \
Business  |  M/ID Amt  |  Cash  |  Bank

Policy numbers are 9-digit codes (e.g. 044600186, 044300173).
Amounts are in Indian rupees, written as plain integers (no commas).
Cash and Bank are mutually exclusive per row — exactly one (or neither)
will be filled. M/ID Amt is usually blank.

For each row in the image, output one JSON object with these keys:
  sl          (integer)
  name        (string, uppercase, may include initials and dots)
  policy_no   (string, exactly 9 digits)
  business    (number or null)
  m_id_amt    (number or null)
  cash        (number or null)
  bank        (number or null)
  note        (string or null — set to "N" if you see a "N" mark)

Return a single JSON array containing one object per row. Output ONLY the
JSON array — no markdown fences, no commentary, no explanation. If a cell
is unreadable, use null rather than guessing."""


class OCRUnavailable(RuntimeError):
    """Raised when the OCR backend (SDK + API key) is not configured."""


def is_available() -> tuple[bool, Optional[str]]:
    """Probe whether OCR can run right now.

    Returns (True, None) when ready, or (False, '<reason>') otherwise so
    the API can surface a precise error to the user.
    """
    if anthropic is None:
        return False, "anthropic SDK not installed (pip install anthropic)"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY env var is not set"
    return True, None


def _image_b64(path: str) -> tuple[str, str]:
    """Read an image file and return (mime_type, base64_payload)."""
    ext = os.path.splitext(path)[1].lower()
    mime = {
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".webp": "image/webp",
        ".gif":  "image/gif",
    }.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        data = f.read()
    return mime, base64.standard_b64encode(data).decode("ascii")


def _extract_via_claude_vision(image_path: str, model: str) -> str:
    """One Claude Vision call → returns the raw text response."""
    client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY from env
    mime, b64 = _image_b64(image_path)
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": mime, "data": b64,
                }},
                {"type": "text", "text": OCR_PROMPT},
            ],
        }],
    )
    return "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    )


def _parse_json_payload(text: str) -> list:
    """Extract the JSON array from Claude's response, tolerating a stray
    code-fence or commentary wrapper if the model lapses."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip ``` fences
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if m:
        return json.loads(m.group(1))
    # Find the first [...] block in the text
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        return json.loads(m.group(0))
    raise ValueError("Could not find JSON array in OCR response")


def _normalize_row(row: dict, default_date: str) -> dict:
    """Coerce one Claude-returned row into the ledger CSV schema."""
    out = {"date": default_date}
    for k in ROW_FIELDS:
        v = row.get(k)
        if v in ("", "null", None):
            out[k] = None
        elif k in ("sl",):
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                out[k] = None
        elif k in ("business", "m_id_amt", "cash", "bank"):
            try:
                out[k] = float(v) if v is not None else None
            except (TypeError, ValueError):
                out[k] = None
        else:
            out[k] = str(v).strip() if v is not None else None
    return out


def extract_ledger_rows(image_path: str, *, default_date: str,
                        model: str = DEFAULT_MODEL) -> list[dict]:
    """Run OCR on a ledger image and return rows ready for CSV writing.

    Raises OCRUnavailable if the SDK or API key is missing — caller
    should surface the message verbatim so the user knows what to fix.
    """
    ok, reason = is_available()
    if not ok:
        raise OCRUnavailable(reason)
    raw = _extract_via_claude_vision(image_path, model)
    parsed = _parse_json_payload(raw)
    if not isinstance(parsed, list):
        raise ValueError("OCR response was not a JSON array")
    return [_normalize_row(r, default_date) for r in parsed if isinstance(r, dict)]


def rows_to_csv_text(rows: list[dict]) -> str:
    """Serialize the normalized rows back to the ledger CSV format the
    rest of the cash pipeline already understands."""
    import csv, io
    buf = io.StringIO()
    fieldnames = ["date"] + list(ROW_FIELDS)
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k))
                    for k in fieldnames})
    return buf.getvalue()
