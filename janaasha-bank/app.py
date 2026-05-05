"""
Flask backend for Priya's reconciliation workspace.

Handles per-branch file uploads, runs the reconciliation engine from
reconcile.py, stores normalised rows in SQLite, and serves a filtered view
to the single-page UI. Resolved state is keyed on (utr, status) so that a
new conflict on the same UTR reopens the row.
"""

import datetime as dt
import io
import os
import re
import sqlite3

import pandas as pd
from flask import Flask, g, jsonify, request, send_file, send_from_directory

import reconcile as rec
import cash_reconcile as cash_rec

APP_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
LEDGER_DIR = os.path.join(UPLOAD_DIR, "ledger")
# Cash-pipeline ledger CSVs (digitized handwritten ledgers). Kept separate
# from the photo uploads in LEDGER_DIR so the two ingest paths don't tangle.
LEDGER_CSV_DIR = os.path.join(UPLOAD_DIR, "ledger_csv")
# Legacy: Canara-only statements used to live here. New uploads go to
# BANK_DIR/<bank_code>/. The constant is kept so the one-shot migration can
# relocate any files written by older versions.
CANARA_DIR = os.path.join(UPLOAD_DIR, "canara")
BANK_DIR = os.path.join(UPLOAD_DIR, "bank")
RESOLVE_ATTACH_DIR = os.path.join(UPLOAD_DIR, "resolve_attachments")
DB_PATH = os.path.join(APP_DIR, "recon.db")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LEDGER_DIR, exist_ok=True)
os.makedirs(LEDGER_CSV_DIR, exist_ok=True)
os.makedirs(CANARA_DIR, exist_ok=True)
os.makedirs(BANK_DIR, exist_ok=True)
os.makedirs(RESOLVE_ATTACH_DIR, exist_ok=True)
for _code in rec.SUPPORTED_BANKS:
    os.makedirs(os.path.join(BANK_DIR, _code), exist_ok=True)

LEDGER_EXT = (".jpg", ".jpeg", ".png")
LEDGER_CSV_EXT = (".csv",)
CASH_BANK_CODES = ("KVB", "SBI", "IOB")  # banks that hold cash deposits

STATUS_CODE = {
    "MATCHED": "MATCHED",
    "AMOUNT MISMATCH": "MISMATCH",
    "MISSING FROM BANK": "MISSING",
    "UNRECORDED IN EXCEL": "UNRECORDED",
    "DUPLICATE (branch)": "DUPLICATE",
    "DUPLICATE (bank)": "DUPLICATE",
    "BANK CHARGE": "BANK_CHARGE",
}

ACCEPTED_BANK_EXTS = (".xls", ".xlsx", ".csv")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB per upload


# ----- DB helpers -----

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utr TEXT,
            branch TEXT,
            customer_name TEXT,
            agent_id TEXT,
            policy_no TEXT,
            policy_type TEXT,
            excel_amount REAL,
            bank_amount REAL,
            status TEXT,
            category TEXT,
            resolved INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS resolved_keys (
            utr TEXT,
            status TEXT,
            PRIMARY KEY (utr, status)
        );
        CREATE TABLE IF NOT EXISTS uploads (
            kind TEXT,
            branch TEXT,
            filename TEXT,
            stored_as TEXT,
            uploaded_at TEXT,
            PRIMARY KEY (kind, branch)
        );
        CREATE TABLE IF NOT EXISTS canara_statements (
            date TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            credits INTEGER,
            uploaded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bank_statements (
            date TEXT NOT NULL,
            bank_code TEXT NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            credits INTEGER,
            uploaded_at TEXT NOT NULL,
            PRIMARY KEY (date, bank_code)
        );
        CREATE TABLE IF NOT EXISTS historical_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            branch TEXT,
            customer_name TEXT,
            agent_id TEXT,
            utr TEXT NOT NULL,
            excel_amount REAL,
            bank_amount REAL,
            status TEXT NOT NULL,
            canara_filename TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT,
            resolved_reason TEXT,
            UNIQUE(date, utr, status)
        );
        CREATE INDEX IF NOT EXISTS idx_flags_open
            ON historical_flags(resolved_at, date);
        CREATE INDEX IF NOT EXISTS idx_flags_date
            ON historical_flags(date);
        CREATE TABLE IF NOT EXISTS cash_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ledger_date TEXT,
            sl INTEGER,
            name TEXT,
            policy_no TEXT,
            ledger_amount REAL,
            bank_date TEXT,
            bank_code TEXT,
            bank_amount REAL,
            machine TEXT,
            ref TEXT,
            status TEXT NOT NULL,
            resolved INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cash_rows_status
            ON cash_rows(status, resolved);
        CREATE INDEX IF NOT EXISTS idx_cash_rows_date
            ON cash_rows(ledger_date, bank_date);
        CREATE TABLE IF NOT EXISTS ledger_csv_uploads (
            date TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            row_count INTEGER,
            uploaded_at TEXT NOT NULL
        );
        """
    )
    # Migrations: add columns to existing tables if they're missing.
    for stmt in (
        "ALTER TABLE uploads ADD COLUMN row_count INTEGER",
        "ALTER TABLE rows ADD COLUMN pending_date TEXT",
        "ALTER TABLE rows ADD COLUMN bank_code TEXT",
        "ALTER TABLE historical_flags ADD COLUMN bank_code TEXT",
        "ALTER TABLE historical_flags ADD COLUMN resolved_attachment TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    # Legacy cleanup: previous versions stored canara under the uploads
    # table. It now lives in bank_statements, so drop any stale row.
    conn.execute("DELETE FROM uploads WHERE kind = 'canara'")

    # One-shot migration: copy any rows from the old canara_statements table
    # into bank_statements, tagging them as CANARA. Safe to re-run (INSERT OR
    # IGNORE skips rows already promoted).
    try:
        legacy = conn.execute(
            "SELECT date, filename, filepath, credits, uploaded_at "
            "FROM canara_statements"
        ).fetchall()
        for r in legacy:
            new_dir = os.path.join(BANK_DIR, "CANARA")
            os.makedirs(new_dir, exist_ok=True)
            new_path = os.path.join(new_dir, f"{r[0]}.xls")
            # Move the physical file into the new per-bank directory if it
            # still lives under the old CANARA_DIR layout.
            if os.path.exists(r[2]) and os.path.abspath(r[2]) != os.path.abspath(new_path):
                try:
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.replace(r[2], new_path)
                except OSError:
                    new_path = r[2]  # fall back to leaving it where it was
            elif os.path.exists(r[2]):
                new_path = r[2]
            else:
                new_path = r[2]
            conn.execute(
                "INSERT OR IGNORE INTO bank_statements "
                "(date, bank_code, filename, filepath, credits, uploaded_at) "
                "VALUES (?, 'CANARA', ?, ?, ?, ?)",
                (r[0], r[1], new_path, r[3], r[4]),
            )
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


init_db()


# ----- Upload helpers -----

def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def branch_stored_name(branch):
    return f"branch_{slug(branch)}.xls"


# ----- Routes -----

DIST_DIR = os.path.join(APP_DIR, "static", "dist")


@app.route("/")
@app.route("/kannabran")
@app.route("/nandhakumar")
def index():
    # SPA routes all serve the same built index.html; React inspects
    # window.location.pathname and renders the appropriate view.
    return send_from_directory(DIST_DIR, "index.html")


@app.route("/api/config")
def api_config():
    ordered = [
        {"code": code, "name": rec.BRANCH_CODE_MAP[code]}
        for code in sorted(rec.BRANCH_CODE_MAP.keys())
    ]
    banks = [
        {"code": code, "name": rec.BANK_LABELS[code]}
        for code in rec.SUPPORTED_BANKS
    ]
    return jsonify(
        {
            "today": dt.date.today().strftime("%d %b %Y"),
            "branches": ordered,
            "branchCount": len(ordered),
            "banks": banks,
        }
    )


@app.route("/api/state")
def api_state():
    """Which files have been uploaded (for the UI top bar + setup overlay)."""
    db = get_db()
    branch_rows = db.execute(
        "SELECT branch, filename, row_count FROM uploads WHERE kind = 'branch'"
    ).fetchall()
    bank_rows = db.execute(
        "SELECT date, bank_code, filename, credits, uploaded_at "
        "FROM bank_statements ORDER BY date DESC, bank_code"
    ).fetchall()
    bank_library = [
        {
            "date": r["date"],
            "bankCode": r["bank_code"],
            "filename": r["filename"],
            "credits": r["credits"],
            "uploadedAt": r["uploaded_at"],
        }
        for r in bank_rows
    ]
    # Legacy shape: the existing React frontend still reads canaraLibrary,
    # so surface a CANARA-only slice until the UI is rebuilt.
    canara_library_compat = [
        entry for entry in bank_library if entry["bankCode"] == "CANARA"
    ]
    return jsonify(
        {
            "bankLibrary": bank_library,
            "canaraLibrary": canara_library_compat,
            "branches": [
                {
                    "branch": r["branch"],
                    "filename": r["filename"],
                    "rowCount": r["row_count"],
                }
                for r in branch_rows
            ],
        }
    )


def _save_bank_statement(f, bank_code):
    """Shared upload-processing logic for /api/upload/bank and the legacy
    /api/upload/canara endpoint. Returns a Flask (response, status) tuple.
    Accepts .xls / .xlsx / .csv.
    """
    bank_code = (bank_code or "CANARA").upper().strip()
    if not f:
        return jsonify({"error": "No file provided"}), 400
    if bank_code not in rec.SUPPORTED_BANKS:
        return jsonify({"error": f"Unsupported bank: {bank_code}"}), 400

    ext = os.path.splitext(f.filename or "")[1].lower() or ".xls"
    if ext not in ACCEPTED_BANK_EXTS:
        return jsonify(
            {"error": f"Unsupported file type: {ext}. Use .xls, .xlsx, or .csv."}
        ), 400

    bank_dir = os.path.join(BANK_DIR, bank_code)
    os.makedirs(bank_dir, exist_ok=True)

    # Stage the upload to a temp path so we can parse the date before
    # committing it to the library layout. Preserve the extension so the
    # right pandas engine picks it up.
    tmp_path = os.path.join(
        bank_dir,
        f"_staging_{int(dt.datetime.now().timestamp() * 1000)}{ext}",
    )
    f.save(tmp_path)

    integrity = {"ok": True, "warnings": [], "stats": {}}
    try:
        statement_date = rec.peek_bank_date(tmp_path, bank_code)
        if not statement_date:
            raise ValueError("Could not read a statement date from this file.")
        bank_df = rec.read_bank(tmp_path, bank_code)
        credits = int(len(bank_df))
        integrity = rec.check_statement_integrity(tmp_path, bank_code)
    except Exception as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return jsonify(
            {"error": f"Could not parse {bank_code} file: {e}"}
        ), 400

    # Promote to canonical location (one file per (date, bank), re-upload
    # replaces). Clear any stale file with a different extension for the
    # same date so we don't end up with two siblings (.xls + .csv).
    for old_ext in ACCEPTED_BANK_EXTS:
        old = os.path.join(bank_dir, f"{statement_date}{old_ext}")
        if os.path.exists(old):
            os.remove(old)
    final_path = os.path.join(bank_dir, f"{statement_date}{ext}")
    os.replace(tmp_path, final_path)

    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO bank_statements "
        "(date, bank_code, filename, filepath, credits, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            statement_date,
            bank_code,
            f.filename,
            final_path,
            credits,
            dt.datetime.now().isoformat(),
        ),
    )
    # Keep legacy canara_statements in sync so any older readers still see it.
    if bank_code == "CANARA":
        db.execute(
            "INSERT OR REPLACE INTO canara_statements "
            "(date, filename, filepath, credits, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                statement_date,
                f.filename,
                final_path,
                credits,
                dt.datetime.now().isoformat(),
            ),
        )
    db.commit()
    return jsonify(
        {
            "filename": f.filename,
            "bankCode": bank_code,
            "date": statement_date,
            "credits": credits,
            "integrity": integrity,
        }
    )


@app.route("/api/upload/bank", methods=["POST"])
def upload_bank():
    """Generic bank statement upload. Expects form fields: file, bank_code."""
    return _save_bank_statement(
        request.files.get("file"),
        request.form.get("bank_code") or "CANARA",
    )


@app.route("/api/upload/canara", methods=["POST"])
def upload_canara():
    """Legacy endpoint — forces bank_code=CANARA."""
    return _save_bank_statement(request.files.get("file"), "CANARA")


@app.route("/api/reset/date", methods=["POST"])
def api_reset_date():
    """Surgical undo: wipe every trace of a single date — bank statements
    (all banks for that date), historical flags, and any rows tagged with
    that date as their pending date. Use this when a wrong file went in
    for a single day and you want a clean slate for that day without
    losing the rest of the audit trail.

    Body: {"date": "YYYY-MM-DD", "confirm": "RESET"}
    """
    data = request.get_json(silent=True) or {}
    if data.get("confirm") != "RESET":
        return jsonify({"error": "confirm field must equal 'RESET'"}), 400
    date = (data.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return jsonify(
            {"error": "date must be YYYY-MM-DD"}
        ), 400

    db = get_db()
    # Collect the bank statement file paths so we can delete the files too.
    rows = db.execute(
        "SELECT filepath FROM bank_statements WHERE date = ?",
        (date,),
    ).fetchall()
    for r in rows:
        try:
            if r["filepath"] and os.path.exists(r["filepath"]):
                os.remove(r["filepath"])
        except OSError as e:
            app.logger.warning(f"reset-date: could not remove {r['filepath']}: {e}")

    db.execute("DELETE FROM bank_statements WHERE date = ?", (date,))
    db.execute("DELETE FROM canara_statements WHERE date = ?", (date,))
    db.execute("DELETE FROM historical_flags WHERE date = ?", (date,))
    # Wipe the current-run rows table entirely. The `rows` table has no
    # per-date column for non-pending statuses (MATCHED/MISMATCH/MISSING/
    # UNRECORDED are only date-tagged at reconcile time), so we can't
    # selectively delete just this date. Clearing the whole table is safe:
    # the next reconcile will rebuild it from whatever bank + branch files
    # remain, and the caller (frontend) triggers that reconcile.
    db.execute("DELETE FROM rows")
    db.commit()

    return jsonify({"ok": True, "date": date})


@app.route("/api/bank/statement", methods=["DELETE"])
def delete_bank_statement():
    """Remove a single uploaded bank statement (both the file on disk and
    the bank_statements row). Expects query params: date, bank_code."""
    date = (request.args.get("date") or "").strip()
    bank_code = (request.args.get("bank_code") or "").upper().strip()
    if not date or not bank_code:
        return jsonify({"error": "date and bank_code are required"}), 400

    db = get_db()
    row = db.execute(
        "SELECT filepath FROM bank_statements "
        "WHERE date = ? AND bank_code = ?",
        (date, bank_code),
    ).fetchone()
    if row is None:
        return jsonify({"error": "statement not found"}), 404

    try:
        if row["filepath"] and os.path.exists(row["filepath"]):
            os.remove(row["filepath"])
    except OSError as e:
        app.logger.warning(f"could not remove file {row['filepath']}: {e}")

    db.execute(
        "DELETE FROM bank_statements WHERE date = ? AND bank_code = ?",
        (date, bank_code),
    )
    # Mirror the legacy table so older readers stay consistent.
    if bank_code == "CANARA":
        db.execute("DELETE FROM canara_statements WHERE date = ?", (date,))
    db.commit()
    return jsonify({"ok": True, "date": date, "bankCode": bank_code})


@app.route("/api/bank/library")
def bank_library():
    db = get_db()
    rows = db.execute(
        "SELECT date, bank_code, filename, credits, uploaded_at "
        "FROM bank_statements ORDER BY date DESC, bank_code"
    ).fetchall()
    return jsonify(
        {
            "statements": [
                {
                    "date": r["date"],
                    "bankCode": r["bank_code"],
                    "filename": r["filename"],
                    "credits": r["credits"],
                    "uploadedAt": r["uploaded_at"],
                }
                for r in rows
            ]
        }
    )


@app.route("/api/canara/library")
def canara_library():
    """Legacy shape — returns only CANARA rows from the unified table."""
    db = get_db()
    rows = db.execute(
        "SELECT date, filename, credits, uploaded_at "
        "FROM bank_statements WHERE bank_code = 'CANARA' ORDER BY date DESC"
    ).fetchall()
    return jsonify(
        {
            "statements": [
                {
                    "date": r["date"],
                    "filename": r["filename"],
                    "credits": r["credits"],
                    "uploadedAt": r["uploaded_at"],
                }
                for r in rows
            ]
        }
    )


@app.route("/api/upload/branch", methods=["POST"])
def upload_branch():
    f = request.files.get("file")
    branch = (request.form.get("branch") or "").strip()
    if not f or not branch:
        return jsonify({"error": "File and branch are both required"}), 400
    stored = branch_stored_name(branch)
    f.save(os.path.join(UPLOAD_DIR, stored))

    # Count rows in the uploaded branch file so the Add Branch review step can
    # show "X rows detected" without running the full reconciliation.
    row_count = None
    try:
        df = rec.read_corporate(os.path.join(UPLOAD_DIR, stored))
        row_count = int(len(df))
    except Exception as e:
        app.logger.warning(f"branch parse failed: {e}")

    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO uploads (kind, branch, filename, stored_as, uploaded_at, row_count) "
        "VALUES ('branch', ?, ?, ?, ?, ?)",
        (branch, f.filename, stored, dt.datetime.now().isoformat(), row_count),
    )
    db.commit()
    return jsonify({"filename": f.filename, "branch": branch, "rowCount": row_count})


def _read_all_corporate():
    """Read every uploaded branch file, merge into one dataframe.

    We overwrite BRANCH NAME with the branch Priya selected at upload time.
    The Excel's own BRANCH NAME column is free text ("M. PALADA" vs
    "M.Palada") and can't be matched reliably against the canonical branch
    list used by the sidebar, filters, and branch-mismatch detection. The
    upload-time selection is the authoritative branch for a given file.

    We also attach a normalized "__date__" column (YYYY-MM-DD) derived from
    the "AMOUNT RECEIVED DATE" column. The reconciliation engine routes rows
    to the correct Canara statement via this column.
    """
    db = get_db()
    files = db.execute(
        "SELECT branch, stored_as FROM uploads WHERE kind='branch'"
    ).fetchall()
    frames = []
    errors = []
    for row in files:
        path = os.path.join(UPLOAD_DIR, row["stored_as"])
        if not os.path.exists(path):
            continue
        try:
            df = rec.read_corporate(path)
        except Exception as e:
            errors.append(f"{row['branch']}: {e}")
            continue
        df["BRANCH NAME"] = row["branch"]
        date_col = next(
            (c for c in df.columns if "AMOUNT RECEIVED DATE" in str(c).upper()),
            None,
        )
        df["__date__"] = (
            df[date_col].apply(rec.normalize_date) if date_col else None
        )
        frames.append(df)
    if not frames:
        return None, errors
    return pd.concat(frames, ignore_index=True), errors


def _val(v):
    """Coerce pandas scalars to JSON-safe Python primitives."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _persist_historical_flags(
    db,
    mismatch_all,
    missing_all,
    unrecorded_all,
    pending_all,
    duplicates_all,
    date_to_filename,
):
    """Sync the historical_flags table with the current reconciliation run.

    - Flags in this run that aren't in the table → INSERT
    - Unresolved flags in the table that aren't in this run → auto-resolve
    - Manually resolved flags that still appear → leave alone (sticky)
    """
    now = dt.datetime.now().isoformat()

    current_keys = set()
    current_data = {}

    def collect(rows, status_code, date_attr):
        for r in rows:
            utr = r.get("UTR")
            if not utr:
                continue
            date = r.get(date_attr) or ""
            key = (date, str(utr), status_code)
            current_keys.add(key)
            current_data[key] = {
                "branch": r.get("Branch") or "",
                "customer_name": r.get("Customer Name") or "",
                "agent_id": r.get("Agent ID") or "",
                "excel_amount": r.get("Excel Amount"),
                "bank_amount": r.get("Bank Amount"),
                "canara_filename": date_to_filename.get(date),
                "bank_code": r.get("Bank Code"),
            }

    collect(mismatch_all,   "MISMATCH",       "__date__")
    collect(missing_all,    "MISSING",        "__date__")
    collect(unrecorded_all, "UNRECORDED",     "__date__")
    collect(pending_all,    "CANARA_PENDING", "Pending Date")
    collect(duplicates_all, "DUPLICATE",      "__date__")

    # Load every existing flag (including resolved ones) so we know whether
    # to INSERT, skip, auto-resolve, or reopen.
    existing = db.execute(
        "SELECT id, date, utr, status, resolved_at, resolved_by FROM historical_flags"
    ).fetchall()
    existing_by_key = {
        ((r["date"] or ""), str(r["utr"]), r["status"]): (
            r["id"],
            r["resolved_at"],
            r["resolved_by"],
        )
        for r in existing
    }

    # 1. For every existing flag, decide auto-resolve / reopen / leave alone.
    #
    #    - unresolved + not in current  → auto-resolve
    #    - auto-resolved + back in current → reopen (auto resolution is
    #      reactive, not sticky — the issue came back, surface it)
    #    - manually resolved → leave alone in all cases (audit trail)
    #    - unresolved + still in current → leave alone
    for key, (row_id, resolved_at, resolved_by) in existing_by_key.items():
        present = key in current_keys
        if resolved_by == "manual":
            continue  # manual resolution is sticky
        if resolved_at is None and not present:
            db.execute(
                "UPDATE historical_flags SET resolved_at = ?, resolved_by = 'auto' "
                "WHERE id = ?",
                (now, row_id),
            )
        elif resolved_at is not None and resolved_by == "auto" and present:
            db.execute(
                "UPDATE historical_flags SET resolved_at = NULL, resolved_by = NULL "
                "WHERE id = ?",
                (row_id,),
            )

    # 2. Insert brand-new flags (not in the table at all).
    for key in current_keys:
        if key in existing_by_key:
            continue
        date, utr, status = key
        d = current_data[key]
        db.execute(
            """INSERT INTO historical_flags
               (date, branch, customer_name, agent_id, utr, excel_amount,
                bank_amount, status, canara_filename, created_at, bank_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                date,
                d["branch"],
                d["customer_name"],
                d["agent_id"],
                str(utr),
                d["excel_amount"],
                d["bank_amount"],
                status,
                d["canara_filename"],
                now,
                d["bank_code"],
            ),
        )


def _build_pending_row(corp_row, pending_date):
    return {
        "Branch": corp_row.get("BRANCH NAME", ""),
        "Customer Name": corp_row.get("CUSTOMER NAME", ""),
        "Agent ID": corp_row.get("AGENT ID", ""),
        "Policy No": corp_row.get("policy_no_raw"),
        "Policy Type": corp_row.get("decoded_policy_type"),
        "UTR": corp_row["UTR"],
        "Excel Amount": corp_row["AMOUNT"],
        "Bank Amount": None,
        "Status": "CANARA_PENDING",
        "Pending Date": pending_date,
    }


@app.route("/api/reconcile", methods=["POST"])
def api_reconcile():
    db = get_db()

    # Load every bank statement in the library into memory, grouped by date.
    # Within a date, rows from all uploaded banks (CANARA/SBI/KVB/IOB/AXIS)
    # are merged into one pool so a UTR is looked up against the union of
    # all banks' credits for that day.
    library_rows = db.execute(
        "SELECT date, bank_code, filepath, filename "
        "FROM bank_statements ORDER BY date, bank_code"
    ).fetchall()
    if not library_rows:
        return jsonify(
            {"error": "Upload at least one bank statement."}
        ), 400

    date_to_bank = {}       # date -> merged DataFrame (UTR, Bank Amount, Particulars, Bank Code)
    date_to_filename = {}   # date -> human-readable label for the historical-flag audit trail
    load_errors = []
    bank_charges_all = []   # cross-date list of {Date, Bank Amount, Particulars, Bank Code}

    per_date_frames = {}    # date -> list of per-bank DataFrames (pre-merge)
    for s in library_rows:
        if not os.path.exists(s["filepath"]):
            load_errors.append(
                f"missing file: {s['filepath']} ({s['bank_code']})"
            )
            continue
        try:
            df = rec.read_bank(s["filepath"], s["bank_code"]).copy()
            df["Bank Code"] = s["bank_code"]
            per_date_frames.setdefault(s["date"], []).append(df)
        except Exception as e:
            load_errors.append(
                f"{s['date']} ({s['bank_code']}): {e}"
            )

        # Pull bank-side charges/fees so they don't pollute the UNRECORDED
        # bucket. Best-effort — a parser miss here just means no charges
        # surface for this statement, not a reconcile failure.
        try:
            charges_df = rec.read_bank_charges(
                s["filepath"], s["bank_code"]
            )
            for _, c in charges_df.iterrows():
                bank_charges_all.append(
                    {
                        "Date": c.get("Date") or s["date"],
                        "Bank Amount": c.get("Bank Amount"),
                        "Particulars": c.get("Particulars") or "",
                        "Bank Code": s["bank_code"],
                    }
                )
        except Exception as e:
            load_errors.append(
                f"{s['date']} ({s['bank_code']}) charges: {e}"
            )

        # Build a "Canara file | SBI file | ..." label per date so the
        # historical_flags table keeps a useful breadcrumb.
        label = f"{s['bank_code']}:{s['filename']}"
        if s["date"] in date_to_filename:
            date_to_filename[s["date"]] += " | " + label
        else:
            date_to_filename[s["date"]] = label

    for date, frames in per_date_frames.items():
        merged = pd.concat(frames, ignore_index=True)
        # If the same UTR somehow appears in two different banks for one
        # date, keep the first (NPCI UTRs are globally unique, so this
        # should be rare and usually indicates a file-labeling error).
        merged = merged.drop_duplicates(subset=["UTR"], keep="first")
        date_to_bank[date] = merged

    corp_df, read_errors = _read_all_corporate()
    errors = list(load_errors) + list(read_errors)
    if corp_df is None:
        corp_df = pd.DataFrame(
            columns=[
                "UTR", "BRANCH NAME", "CUSTOMER NAME", "AGENT ID", "AMOUNT",
                "policy_no_raw", "decoded_branch_code", "decoded_policy_type",
                "decoded_branch_name", "__date__",
            ]
        )

    # Branch-mismatch detection is policy-number-vs-branch-name. It doesn't
    # care about the bank side, so it runs once on the whole corp frame.
    branch_mismatches = rec.find_branch_mismatches(corp_df)

    matched_all, mismatch_all, missing_all, unrecorded_all, pending_all, duplicates_all = (
        [], [], [], [], [], [],
    )

    # Corp rows with an unparseable / blank date can't be routed to any
    # statement — surface them as CANARA_PENDING with no specific date.
    if not corp_df.empty:
        undated = corp_df[corp_df["__date__"].isna()]
        for _, row in undated.iterrows():
            pending_all.append(_build_pending_row(row, None))

    # Iterate every date that appears in either the corp data or the library.
    #
    # IMPORTANT: routing is per-ROW, not per-file. A single branch Excel may
    # contain rows dated 2026-04-01 AND 2026-03-28 — each row is routed to
    # the statement matching ITS OWN Amount Received Date. We never assume
    # all rows in one file share a date. corp_df is the concatenation of
    # every branch file's rows, each carrying its normalized __date__.
    corp_dates = (
        set(corp_df["__date__"].dropna().unique()) if not corp_df.empty else set()
    )
    all_dates = corp_dates | set(date_to_bank.keys())

    for date in sorted(all_dates):
        date_corp = (
            corp_df[corp_df["__date__"] == date]
            if not corp_df.empty
            else pd.DataFrame(columns=corp_df.columns)
        )
        bank_df = date_to_bank.get(date)

        if bank_df is None:
            # Library has no statement for this date → everything pending.
            for _, row in date_corp.iterrows():
                pending_all.append(_build_pending_row(row, date))
            continue

        matched, mismatch, missing, unrecorded, duplicates = rec.reconcile(
            date_corp, bank_df
        )
        # Tag each result with its reconciliation date so the historical-
        # flag sync can key on (date, utr, status) later.
        for r in matched:    r["__date__"] = date
        for r in mismatch:   r["__date__"] = date
        for r in missing:    r["__date__"] = date
        for r in unrecorded: r["__date__"] = date
        for r in duplicates: r["__date__"] = date
        matched_all.extend(matched)
        mismatch_all.extend(mismatch)
        missing_all.extend(missing)
        unrecorded_all.extend(unrecorded)
        duplicates_all.extend(duplicates)

    now = dt.datetime.now().isoformat()
    db.execute("DELETE FROM rows")

    def insert(rows, category):
        for r in rows:
            raw_status = r["Status"]
            code = STATUS_CODE.get(raw_status, raw_status)
            if category == "branch_mismatch":
                code = "BRANCH_MISMATCH"
            db.execute(
                """
                INSERT INTO rows (utr, branch, customer_name, agent_id,
                    policy_no, policy_type, excel_amount, bank_amount,
                    status, category, resolved, created_at, pending_date,
                    bank_code)
                VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?)
                """,
                (
                    _val(r.get("UTR")),
                    _val(r.get("Branch")),
                    _val(r.get("Customer Name")),
                    _val(r.get("Agent ID")),
                    _val(r.get("Policy No")),
                    _val(r.get("Policy Type")),
                    _val(r.get("Excel Amount")),
                    _val(r.get("Bank Amount")),
                    code,
                    category,
                    now,
                    _val(r.get("Pending Date")),
                    _val(r.get("Bank Code")),
                ),
            )

    insert(matched_all, "active")
    insert(mismatch_all, "active")
    insert(missing_all, "active")
    insert(unrecorded_all, "active")
    insert(pending_all, "active")
    insert(duplicates_all, "active")
    insert(branch_mismatches, "branch_mismatch")

    # Bank charges: informational only. They live in their own category so
    # the existing tab queries (active / pending / branch_mismatch) ignore
    # them, but they are still queryable via tab=bank_charge.
    for c in bank_charges_all:
        db.execute(
            """
            INSERT INTO rows (utr, branch, customer_name, agent_id,
                policy_no, policy_type, excel_amount, bank_amount,
                status, category, resolved, created_at, pending_date,
                bank_code)
            VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?)
            """,
            (
                None,
                "",
                (c.get("Particulars") or "")[:120],
                None,
                None,
                None,
                None,
                _val(c.get("Bank Amount")),
                "BANK_CHARGE",
                "bank_charge",
                now,
                _val(c.get("Date")),
                _val(c.get("Bank Code")),
            ),
        )

    # Sync the long-lived historical_flags table. This is what powers the
    # History tab across dates and survives the wipe-and-reinsert cycle of
    # the `rows` table above.
    _persist_historical_flags(
        db,
        mismatch_all,
        missing_all,
        unrecorded_all,
        pending_all,
        duplicates_all,
        date_to_filename,
    )

    # Re-apply sticky resolved flags.
    db.execute(
        """
        UPDATE rows SET resolved = 1
        WHERE EXISTS (
            SELECT 1 FROM resolved_keys k
            WHERE k.utr = rows.utr AND k.status = rows.status
        )
        """
    )
    db.commit()

    return jsonify({"ok": True, "errors": errors})


def _query_rows(tab, branch, policy_type, status, search, bank_code=None):
    db = get_db()
    params = []
    clauses = []

    if tab == "resolved":
        clauses.append("resolved = 1")
    elif tab == "branch_mismatch":
        clauses.append("category = 'branch_mismatch' AND resolved = 0")
    elif tab == "pending":
        # The Pending / Excess tab covers two related buckets: branch
        # entries waiting on a bank statement (CANARA_PENDING) and bank
        # credits with no matching branch entry (UNRECORDED).
        clauses.append(
            "category = 'active' AND resolved = 0 "
            "AND status IN ('CANARA_PENDING', 'UNRECORDED')"
        )
    elif tab == "bank_charge":
        clauses.append("category = 'bank_charge' AND resolved = 0")
    else:  # active
        # Hide the pending/excess buckets from the main Active tab so they
        # don't double-count once the Pending tab exists. MATCHED stays
        # here so Priya can spot-check successful rows.
        clauses.append(
            "category = 'active' AND resolved = 0 "
            "AND status NOT IN ('CANARA_PENDING', 'UNRECORDED')"
        )

    if branch:
        clauses.append("branch = ?")
        params.append(branch)
    if policy_type:
        clauses.append("policy_type = ?")
        params.append(policy_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if bank_code:
        clauses.append("bank_code = ?")
        params.append(bank_code)
    if search:
        like = f"%{search}%"
        clauses.append(
            "(customer_name LIKE ? OR utr LIKE ? OR branch LIKE ?)"
        )
        params.extend([like, like, like])

    where = " AND ".join(clauses)
    sql = f"SELECT * FROM rows WHERE {where} ORDER BY branch, customer_name"
    return db.execute(sql, params).fetchall()


def _summary_counts():
    db = get_db()
    row = db.execute(
        """
        SELECT
          SUM(CASE WHEN category='active' AND status NOT IN ('UNRECORDED')
                   THEN 1 ELSE 0 END) AS total_excel,
          SUM(CASE WHEN status='MATCHED'        AND resolved=0 THEN 1 ELSE 0 END) AS matched,
          SUM(CASE WHEN status='MISMATCH'       AND resolved=0 THEN 1 ELSE 0 END) AS mismatch,
          SUM(CASE WHEN status='MISSING'        AND resolved=0 THEN 1 ELSE 0 END) AS missing,
          SUM(CASE WHEN status='UNRECORDED'     AND resolved=0 THEN 1 ELSE 0 END) AS unrecorded,
          SUM(CASE WHEN status='CANARA_PENDING' AND resolved=0 THEN 1 ELSE 0 END) AS canara_pending,
          SUM(CASE WHEN status='BANK_CHARGE'    AND resolved=0 THEN 1 ELSE 0 END) AS bank_charge
        FROM rows
        """
    ).fetchone()
    return {
        "total_excel":    row["total_excel"]    or 0,
        "matched":        row["matched"]        or 0,
        "mismatch":       row["mismatch"]       or 0,
        "missing":        row["missing"]        or 0,
        "unrecorded":     row["unrecorded"]     or 0,
        "canara_pending": row["canara_pending"] or 0,
        "bank_charge":    row["bank_charge"]    or 0,
    }


@app.route("/api/data")
def api_data():
    tab = request.args.get("tab", "active")
    branch = request.args.get("branch") or None
    policy_type = request.args.get("policy_type") or None
    status = request.args.get("status") or None
    search = request.args.get("search") or None
    bank_code = (request.args.get("bank") or request.args.get("bank_code") or "").upper() or None

    rows = _query_rows(tab, branch, policy_type, status, search, bank_code)
    data = [dict(r) for r in rows]
    return jsonify({"rows": data, "summary": _summary_counts()})


@app.route("/api/resolve/<int:row_id>", methods=["POST"])
def api_resolve(row_id):
    db = get_db()
    row = db.execute("SELECT utr, status FROM rows WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404
    db.execute("UPDATE rows SET resolved = 1 WHERE id = ?", (row_id,))
    db.execute(
        "INSERT OR IGNORE INTO resolved_keys (utr, status) VALUES (?, ?)",
        (row["utr"], row["status"]),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/unresolve/<int:row_id>", methods=["POST"])
def api_unresolve(row_id):
    """Undo a resolve. Flips the row back to unresolved AND drops the
    sticky (utr, status) entry from resolved_keys — otherwise the next
    reconcile would auto-resolve it again.
    """
    db = get_db()
    row = db.execute("SELECT utr, status FROM rows WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404
    db.execute("UPDATE rows SET resolved = 0 WHERE id = ?", (row_id,))
    db.execute(
        "DELETE FROM resolved_keys WHERE utr = ? AND status = ?",
        (row["utr"], row["status"]),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/export")
def api_export():
    tab = request.args.get("tab", "active")
    branch = request.args.get("branch") or None
    policy_type = request.args.get("policy_type") or None
    status = request.args.get("status") or None
    search = request.args.get("search") or None
    bank_code = (request.args.get("bank") or request.args.get("bank_code") or "").upper() or None

    rows = _query_rows(tab, branch, policy_type, status, search, bank_code)
    records = [
        {
            "Branch": r["branch"],
            "Bank": r["bank_code"],
            "Customer Name": r["customer_name"],
            "Agent ID": r["agent_id"],
            "Policy No": r["policy_no"],
            "Policy Type": r["policy_type"],
            "UTR": r["utr"],
            "Excel Amount": r["excel_amount"],
            "Bank Amount": r["bank_amount"],
            "Status": r["status"],
        }
        for r in rows
    ]
    df = pd.DataFrame(records)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Export", index=False)
    buf.seek(0)
    filename = f"reconciliation_{tab}_{dt.date.today().isoformat()}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ----- Historical flags (persist across reconciliation runs) -----

@app.route("/api/flags/history")
def api_flags_history():
    """List historical flags. Supports filtering by branch, date range,
    status, and resolution mode. Default mode = 'open' (unresolved only).
    """
    branch = request.args.get("branch") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    status = request.args.get("status") or None
    resolved_mode = (request.args.get("resolved") or "open").lower()

    clauses = []
    params = []

    if resolved_mode == "open":
        clauses.append("resolved_at IS NULL")
    elif resolved_mode == "manual":
        clauses.append("resolved_at IS NOT NULL AND resolved_by = 'manual'")
    elif resolved_mode == "auto":
        clauses.append("resolved_at IS NOT NULL AND resolved_by = 'auto'")
    # "all" adds no filter

    if branch:
        clauses.append("branch = ?")
        params.append(branch)
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to)
    if status:
        clauses.append("status = ?")
        params.append(status)

    bank_code = (request.args.get("bank") or request.args.get("bank_code") or "").upper() or None
    if bank_code:
        clauses.append("bank_code = ?")
        params.append(bank_code)

    where = " AND ".join(clauses) if clauses else "1=1"
    sql = f"""
        SELECT id, date, branch, customer_name, agent_id, utr,
               excel_amount, bank_amount, status, canara_filename,
               bank_code, resolved_attachment, created_at, resolved_at,
               resolved_by, resolved_reason
        FROM historical_flags
        WHERE {where}
        ORDER BY date DESC, id DESC
    """

    db = get_db()
    rows = db.execute(sql, params).fetchall()
    return jsonify({
        "flags": [dict(r) for r in rows],
        "total": len(rows),
    })


@app.route("/api/flags/summary")
def api_flags_summary():
    """Per-date counts + overall totals for the calendar heatmap and the
    4 stat cards above it."""
    db = get_db()

    per_date = db.execute(
        """
        SELECT date,
               SUM(CASE WHEN resolved_at IS NULL      THEN 1 ELSE 0 END) AS open_count,
               SUM(CASE WHEN resolved_at IS NOT NULL  THEN 1 ELSE 0 END) AS resolved_count
        FROM historical_flags
        WHERE date IS NOT NULL AND date != ''
        GROUP BY date
        """
    ).fetchall()

    by_date = {
        r["date"]: {
            "open": r["open_count"] or 0,
            "resolved": r["resolved_count"] or 0,
        }
        for r in per_date
    }

    totals_row = db.execute(
        """
        SELECT COUNT(*)                                AS open_total,
               MIN(NULLIF(date, ''))                   AS oldest_date,
               COUNT(DISTINCT NULLIF(branch, ''))      AS branch_count,
               COUNT(DISTINCT NULLIF(date, ''))        AS date_count
        FROM historical_flags
        WHERE resolved_at IS NULL
        """
    ).fetchone()

    oldest_days = None
    if totals_row and totals_row["oldest_date"]:
        try:
            oldest = dt.date.fromisoformat(totals_row["oldest_date"])
            oldest_days = (dt.date.today() - oldest).days
        except (ValueError, TypeError):
            pass

    statement_dates = [
        r["date"]
        for r in db.execute(
            "SELECT DISTINCT date FROM bank_statements"
        ).fetchall()
    ]

    # Recurring-issue detection: branches with open flags on 3+ distinct
    # dates for the same status. Catches patterns like "M.Palada has had
    # UNRECORDED credits for 4 consecutive days" — doesn't require the
    # days to actually be consecutive, but the signal is equivalent.
    recurring_rows = db.execute(
        """
        SELECT branch, status, COUNT(DISTINCT date) AS days,
               MIN(date) AS first_date, MAX(date) AS last_date
        FROM historical_flags
        WHERE resolved_at IS NULL AND branch IS NOT NULL AND branch != ''
        GROUP BY branch, status
        HAVING days >= 3
        ORDER BY days DESC, branch
        """
    ).fetchall()
    recurring = [
        {
            "branch":    r["branch"],
            "status":    r["status"],
            "days":      r["days"],
            "firstDate": r["first_date"],
            "lastDate":  r["last_date"],
        }
        for r in recurring_rows
    ]

    return jsonify({
        "byDate": by_date,
        "statementDates": statement_dates,
        "totals": {
            "open": (totals_row["open_total"] or 0) if totals_row else 0,
            "oldestDays": oldest_days,
            "branches": (totals_row["branch_count"] or 0) if totals_row else 0,
            "dates": (totals_row["date_count"] or 0) if totals_row else 0,
        },
        "recurring": recurring,
    })


@app.route("/api/flags/<int:flag_id>/resolve", methods=["POST"])
def api_flag_resolve(flag_id):
    """Mark a flag as manually resolved with a reason (audit trail).

    Accepts either JSON {reason} or multipart form with 'reason' + optional
    'attachment' file (screenshot / PDF / whatever proof Priya wants to
    attach). The attachment is stored under uploads/resolve_attachments/
    and downloadable via /api/flags/<id>/attachment.
    """
    attachment = None
    reason = ""

    if request.content_type and request.content_type.startswith("multipart/"):
        reason = (request.form.get("reason") or "").strip()
        attachment = request.files.get("attachment")
    else:
        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()

    if not reason:
        return jsonify({"error": "Reason is required"}), 400

    db = get_db()
    row = db.execute(
        "SELECT id FROM historical_flags WHERE id = ? AND resolved_at IS NULL",
        (flag_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Flag not found or already resolved"}), 404

    stored_attachment = None
    if attachment and attachment.filename:
        safe = re.sub(r"[^a-zA-Z0-9._-]", "_", attachment.filename)
        stored_name = f"{flag_id}_{int(dt.datetime.now().timestamp() * 1000)}_{safe}"
        attachment.save(os.path.join(RESOLVE_ATTACH_DIR, stored_name))
        stored_attachment = stored_name

    db.execute(
        """UPDATE historical_flags
           SET resolved_at = ?, resolved_by = 'manual', resolved_reason = ?,
               resolved_attachment = ?
           WHERE id = ?""",
        (
            dt.datetime.now().isoformat(),
            reason,
            stored_attachment,
            flag_id,
        ),
    )
    db.commit()
    return jsonify({"ok": True, "attachment": stored_attachment})


@app.route("/api/flags/<int:flag_id>/reopen", methods=["POST"])
def api_flag_reopen(flag_id):
    """Undo a manual resolve: flip the flag back to open, drop the saved
    reason, and delete the attachment file from disk. Used when a resolve
    was done by mistake (wrong reason, wrong proof, wrong flag, etc.).
    """
    db = get_db()
    row = db.execute(
        "SELECT id, resolved_attachment, resolved_by "
        "FROM historical_flags WHERE id = ?",
        (flag_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Flag not found"}), 404
    if row["resolved_by"] != "manual":
        return jsonify({"error": "Only manual resolutions can be reopened"}), 400

    # Remove the stored attachment file (best-effort; don't block on errors).
    if row["resolved_attachment"]:
        path = os.path.join(RESOLVE_ATTACH_DIR, row["resolved_attachment"])
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            app.logger.warning(f"reopen: could not remove {path}: {e}")

    db.execute(
        """UPDATE historical_flags
           SET resolved_at = NULL, resolved_by = NULL,
               resolved_reason = NULL, resolved_attachment = NULL
           WHERE id = ?""",
        (flag_id,),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/flags/<int:flag_id>/attachment")
def api_flag_attachment(flag_id):
    """Serve the proof attachment that was uploaded when the flag was
    manually resolved. Returns 404 if no attachment exists."""
    db = get_db()
    row = db.execute(
        "SELECT resolved_attachment FROM historical_flags WHERE id = ?",
        (flag_id,),
    ).fetchone()
    if row is None or not row["resolved_attachment"]:
        return jsonify({"error": "No attachment"}), 404
    return send_from_directory(
        RESOLVE_ATTACH_DIR, row["resolved_attachment"], as_attachment=False
    )


@app.route("/api/flags/export")
def api_flags_export():
    """Download currently-filtered historical flags as xlsx."""
    branch = request.args.get("branch") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    status = request.args.get("status") or None
    resolved_mode = (request.args.get("resolved") or "open").lower()

    clauses = []
    params = []
    if resolved_mode == "open":
        clauses.append("resolved_at IS NULL")
    elif resolved_mode == "manual":
        clauses.append("resolved_at IS NOT NULL AND resolved_by = 'manual'")
    if branch:
        clauses.append("branch = ?")
        params.append(branch)
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = " AND ".join(clauses) if clauses else "1=1"

    db = get_db()
    rows = db.execute(
        f"""SELECT date, branch, customer_name, agent_id, utr,
                   excel_amount, bank_amount, status, canara_filename,
                   created_at, resolved_at, resolved_by, resolved_reason
            FROM historical_flags
            WHERE {where}
            ORDER BY date DESC, id DESC""",
        params,
    ).fetchall()

    records = [
        {
            "Date": r["date"],
            "Branch": r["branch"],
            "Customer Name": r["customer_name"],
            "Agent ID": r["agent_id"],
            "UTR": r["utr"],
            "Excel Amount": r["excel_amount"],
            "Bank Amount": r["bank_amount"],
            "Status": r["status"],
            "Canara File": r["canara_filename"],
            "First Flagged": r["created_at"],
            "Resolved At": r["resolved_at"],
            "Resolved By": r["resolved_by"],
            "Resolve Reason": r["resolved_reason"],
        }
        for r in rows
    ]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(records).to_excel(
            writer, sheet_name="Open Flags", index=False
        )
    buf.seek(0)
    filename = f"historical_flags_{dt.date.today().isoformat()}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ----- End of day tally (money-in-bank vs money-from-branches) -----

@app.route("/api/tally")
def api_tally():
    """Sums the active-tab rows so Priya can answer
    'does the money in Canara match what the branches recorded?'.

    Canara side = rows where the UTR was found in the bank statement
                  (MATCHED + MISMATCH + UNRECORDED) summed on bank_amount.
    Branch side = rows a branch logged
                  (MATCHED + MISMATCH + MISSING) summed on excel_amount.
    Difference  = Canara - Branches. Ideal end-of-day value is zero.
    """
    db = get_db()
    row = db.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN status IN ('MATCHED','MISMATCH','MISSING')
                            THEN excel_amount END), 0) AS branches_total,
          COALESCE(SUM(CASE WHEN status IN ('MATCHED','MISMATCH','UNRECORDED')
                            THEN bank_amount END), 0) AS canara_total,
          COALESCE(SUM(CASE WHEN status = 'MATCHED'
                            THEN excel_amount END), 0) AS matched_total,
          COALESCE(SUM(CASE WHEN status = 'MISMATCH'
                            THEN excel_amount END), 0) AS mismatch_excel,
          COALESCE(SUM(CASE WHEN status = 'MISMATCH'
                            THEN bank_amount END), 0) AS mismatch_bank,
          COALESCE(SUM(CASE WHEN status = 'MISSING'
                            THEN excel_amount END), 0) AS missing_total,
          COALESCE(SUM(CASE WHEN status = 'UNRECORDED'
                            THEN bank_amount END), 0) AS unrecorded_total,
          COALESCE(SUM(CASE WHEN status = 'CANARA_PENDING'
                            THEN excel_amount END), 0) AS pending_total,
          SUM(CASE WHEN status = 'MATCHED'        THEN 1 ELSE 0 END) AS matched_count,
          SUM(CASE WHEN status = 'MISMATCH'       THEN 1 ELSE 0 END) AS mismatch_count,
          SUM(CASE WHEN status = 'MISSING'        THEN 1 ELSE 0 END) AS missing_count,
          SUM(CASE WHEN status = 'UNRECORDED'     THEN 1 ELSE 0 END) AS unrecorded_count,
          SUM(CASE WHEN status = 'CANARA_PENDING' THEN 1 ELSE 0 END) AS pending_count
        FROM rows
        WHERE category = 'active'
        """
    ).fetchone()

    canara = float(row["canara_total"])
    branches = float(row["branches_total"])
    return jsonify(
        {
            "canaraTotal": canara,
            "branchesTotal": branches,
            "matchedTotal": float(row["matched_total"]),
            "difference": canara - branches,
            "mismatch": {
                "excelTotal": float(row["mismatch_excel"]),
                "bankTotal": float(row["mismatch_bank"]),
                "count": int(row["mismatch_count"] or 0),
            },
            "missing": {
                "total": float(row["missing_total"]),
                "count": int(row["missing_count"] or 0),
            },
            "unrecorded": {
                "total": float(row["unrecorded_total"]),
                "count": int(row["unrecorded_count"] or 0),
            },
            "canaraPending": {
                "total": float(row["pending_total"]),
                "count": int(row["pending_count"] or 0),
            },
            "matchedCount": int(row["matched_count"] or 0),
        }
    )


# ----- Ledger photo storage (persistent, per-branch, viewable by oversight) -----

@app.route("/api/ledger/upload", methods=["POST"])
def ledger_upload():
    branch = (request.form.get("branch") or "").strip()
    f = request.files.get("file")
    if not branch or not f:
        return jsonify({"error": "branch and file required"}), 400
    if not (f.filename or "").lower().endswith(LEDGER_EXT):
        return jsonify({"error": "jpg, jpeg, png only"}), 400
    branch_slug = slug(branch)
    d = os.path.join(LEDGER_DIR, branch_slug)
    os.makedirs(d, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", f.filename)
    stored = f"{int(dt.datetime.now().timestamp() * 1000)}_{safe_name}"
    f.save(os.path.join(d, stored))
    return jsonify(
        {
            "id": stored,
            "name": f.filename,
            "url": f"/api/ledger/file/{branch_slug}/{stored}",
        }
    )


@app.route("/api/ledger/list")
def ledger_list():
    branch = (request.args.get("branch") or "").strip()
    if not branch:
        return jsonify({"photos": []})
    branch_slug = slug(branch)
    d = os.path.join(LEDGER_DIR, branch_slug)
    if not os.path.isdir(d):
        return jsonify({"photos": []})
    photos = []
    for name in sorted(os.listdir(d)):
        if not name.lower().endswith(LEDGER_EXT):
            continue
        # Strip the leading "<ms>_" prefix for display.
        original = name
        if "_" in name:
            head, tail = name.split("_", 1)
            if head.isdigit():
                original = tail
        photos.append(
            {
                "id": name,
                "name": original,
                "url": f"/api/ledger/file/{branch_slug}/{name}",
            }
        )
    return jsonify({"photos": photos})


@app.route("/api/ledger/file/<branch_slug>/<filename>")
def ledger_file(branch_slug, filename):
    # send_from_directory prevents path traversal out of the branch directory.
    return send_from_directory(
        os.path.join(LEDGER_DIR, branch_slug), filename
    )


# ============ Cash pipeline (KVB / SBI / IOB ↔ digitized ledger) ============
#
# Three endpoints, intentionally parallel to the UPI pipeline above:
#   POST /api/cash/upload-ledger  — uploads a ledger CSV for a date
#   POST /api/cash/reconcile      — runs the matcher for a date,
#                                    persists results to cash_rows
#   GET  /api/cash/data           — queries persisted results by tab + date
#
# Why a new pipeline (vs reusing /api/reconcile):
# UPI deposits carry a UTR; cash deposits don't. The matchers therefore
# join on different keys (UTR vs amount+date). Mixing them in one route
# would force every caller to pick a strategy per row.

CASH_STATUSES = {
    "matched":              "MATCHED",
    "missing_from_bank":    "MISSING_FROM_BANK",
    "unrecorded_in_ledger": "UNRECORDED_IN_LEDGER",
    "cash_in_hand":         "CASH_IN_HAND",
}


@app.route("/api/cash/upload-ledger", methods=["POST"])
def cash_upload_ledger():
    """Accept a digitized ledger CSV and store it under uploads/ledger_csv/.

    Form fields:
      file (required) — CSV with columns: date, sl, name, policy_no,
                         business, m_id_amt, cash, bank, note
      date (optional) — if given, the file is keyed under that date;
                         otherwise the date is taken from the first row.
    """
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file required"}), 400
    if not (f.filename or "").lower().endswith(LEDGER_CSV_EXT):
        return jsonify({"error": "csv only"}), 400

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", f.filename)
    stored = f"{int(dt.datetime.now().timestamp() * 1000)}_{safe_name}"
    path = os.path.join(LEDGER_CSV_DIR, stored)
    f.save(path)

    # Parse to validate + pull out the canonical date for keying.
    try:
        df = cash_rec.read_ledger_csv(path)
    except Exception as e:
        try:
            os.remove(path)
        except OSError:
            pass
        return jsonify({"error": f"could not parse CSV: {e}"}), 400

    date_arg = (request.form.get("date") or "").strip()
    if not date_arg:
        if df.empty:
            return jsonify({"error": "ledger has no rows"}), 400
        date_arg = df["date"].iloc[0]

    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO ledger_csv_uploads "
        "(date, filename, filepath, row_count, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (date_arg, f.filename, path, int(len(df)),
         dt.datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    return jsonify({
        "date": date_arg,
        "rows": int(len(df)),
        "filename": f.filename,
        "stored_as": stored,
    })


def _bank_paths_for_date(db, date):
    """Look up uploaded KVB/SBI/IOB statements that cover the given date.

    The bank_statements table is keyed by (date, bank_code) — the date there
    is the *first* date of the statement. Cash deposits often arrive a day
    or two later, so we accept any statement whose key date is within ±14
    days of the ledger date and let the parsers do their own date filtering.
    """
    paths = {}
    rows = db.execute(
        "SELECT bank_code, filepath FROM bank_statements "
        "WHERE bank_code IN (?, ?, ?) "
        "AND date >= date(?, '-14 days') "
        "AND date <= date(?, '+14 days')",
        ("KVB", "SBI", "IOB", date, date),
    ).fetchall()
    for r in rows:
        # If multiple statements cover the date, prefer the one that includes
        # the date itself (key date == requested date), else the earliest.
        if r["bank_code"] not in paths:
            paths[r["bank_code"]] = r["filepath"]
    return paths


@app.route("/api/cash/reconcile", methods=["POST"])
def cash_reconcile():
    """Run the cash-pipeline matcher for a given ledger date.

    JSON / form body:
      date (required)             — ISO date of the ledger (YYYY-MM-DD)
      date_window_days (optional) — search bank rows N days after the
                                     ledger date (default: 1)
    """
    data = request.get_json(silent=True) or request.form
    date = (data.get("date") or "").strip()
    if not date:
        return jsonify({"error": "date required"}), 400
    try:
        window = int(data.get("date_window_days") or 1)
    except (TypeError, ValueError):
        window = 1

    db = get_db()
    upload = db.execute(
        "SELECT filepath FROM ledger_csv_uploads WHERE date = ?", (date,)
    ).fetchone()
    if not upload:
        return jsonify({"error": f"no ledger CSV uploaded for {date}"}), 404

    try:
        ledger = cash_rec.read_ledger_csv(upload["filepath"])
    except Exception as e:
        return jsonify({"error": f"could not read ledger: {e}"}), 500

    bank_paths = _bank_paths_for_date(db, date)
    bank_df = cash_rec.collect_bank_cash_deposits(bank_paths)
    result = cash_rec.reconcile_cash(
        ledger, bank_df, date_window_days=window
    )

    # Wipe existing cash rows for this date and re-insert. Resolved rows
    # are preserved across re-runs by re-applying their resolved flag below.
    resolved_keys = {
        (r["status"], r["ledger_date"], r["sl"], r["bank_date"],
         r["bank_code"], r["bank_amount"])
        for r in db.execute(
            "SELECT status, ledger_date, sl, bank_date, bank_code, bank_amount "
            "FROM cash_rows WHERE resolved = 1 "
            "AND (ledger_date = ? OR bank_date = ?)",
            (date, date),
        ).fetchall()
    }
    db.execute(
        "DELETE FROM cash_rows WHERE ledger_date = ? OR bank_date = ?",
        (date, date),
    )
    now = dt.datetime.now().isoformat(timespec="seconds")
    counts = {}

    for tab in ("matched", "missing_from_bank", "unrecorded_in_ledger"):
        df = result[tab]
        counts[tab] = int(len(df))
        for _, row in df.iterrows():
            key = (
                CASH_STATUSES[tab],
                row.get("Ledger Date"),
                int(row["Sl"]) if pd.notna(row.get("Sl")) else None,
                row.get("Bank Date"),
                row.get("Bank Code"),
                float(row["Bank Amount"]) if pd.notna(row.get("Bank Amount")) else None,
            )
            db.execute(
                "INSERT INTO cash_rows "
                "(ledger_date, sl, name, policy_no, ledger_amount, "
                " bank_date, bank_code, bank_amount, machine, ref, "
                " status, resolved, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("Ledger Date"),
                    int(row["Sl"]) if pd.notna(row.get("Sl")) else None,
                    row.get("Name"),
                    row.get("Policy No"),
                    float(row["Ledger Amount"]) if pd.notna(row.get("Ledger Amount")) else None,
                    row.get("Bank Date"),
                    row.get("Bank Code"),
                    float(row["Bank Amount"]) if pd.notna(row.get("Bank Amount")) else None,
                    row.get("Machine"),
                    row.get("Ref"),
                    CASH_STATUSES[tab],
                    1 if key in resolved_keys else 0,
                    now,
                ),
            )

    cih = result["cash_in_hand"]
    counts["cash_in_hand"] = int(len(cih))
    for _, row in cih.iterrows():
        key = (CASH_STATUSES["cash_in_hand"], row["date"],
               int(row["sl"]) if pd.notna(row["sl"]) else None,
               None, None, None)
        db.execute(
            "INSERT INTO cash_rows "
            "(ledger_date, sl, name, policy_no, ledger_amount, "
            " bank_date, bank_code, bank_amount, machine, ref, "
            " status, resolved, created_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?)",
            (
                row["date"],
                int(row["sl"]) if pd.notna(row["sl"]) else None,
                row["name"],
                row["policy_no"],
                float(row["cash"]) if pd.notna(row["cash"]) else None,
                CASH_STATUSES["cash_in_hand"],
                1 if key in resolved_keys else 0,
                now,
            ),
        )

    db.commit()

    # Build the daily summary inline (not persisted — derivable on demand).
    daily = result["daily_summary"].to_dict(orient="records")
    return jsonify({
        "date": date,
        "counts": counts,
        "banks_used": sorted(bank_paths.keys()),
        "daily_summary": daily,
    })


@app.route("/api/cash/data")
def cash_data():
    """Query persisted cash rows.

    Query params:
      tab (required)        — matched | missing_from_bank |
                               unrecorded_in_ledger | cash_in_hand
      date (optional)       — YYYY-MM-DD; matches either ledger_date or bank_date
      include_resolved (opt)— '1' to include resolved rows (default: '0')
    """
    tab = (request.args.get("tab") or "").strip()
    if tab not in CASH_STATUSES:
        return jsonify({
            "error": "tab must be one of: " + ", ".join(CASH_STATUSES.keys())
        }), 400
    status = CASH_STATUSES[tab]

    sql = "SELECT * FROM cash_rows WHERE status = ?"
    params = [status]

    date = (request.args.get("date") or "").strip()
    if date:
        sql += " AND (ledger_date = ? OR bank_date = ?)"
        params.extend([date, date])

    if (request.args.get("include_resolved") or "0") != "1":
        sql += " AND resolved = 0"

    sql += " ORDER BY id"
    rows = [dict(r) for r in get_db().execute(sql, params).fetchall()]
    return jsonify({"rows": rows, "count": len(rows)})


@app.route("/api/cash/resolve/<int:row_id>", methods=["POST"])
def cash_resolve(row_id):
    db = get_db()
    db.execute("UPDATE cash_rows SET resolved = 1 WHERE id = ?", (row_id,))
    db.commit()
    return jsonify({"id": row_id, "resolved": True})


@app.route("/api/cash/unresolve/<int:row_id>", methods=["POST"])
def cash_unresolve(row_id):
    db = get_db()
    db.execute("UPDATE cash_rows SET resolved = 0 WHERE id = ?", (row_id,))
    db.commit()
    return jsonify({"id": row_id, "resolved": False})


# ============ Cross-pipeline duplicate check ============================
#
# Catches the real fraud/error pattern where one customer payment is
# booked twice: once in the branch Excel as a UPI receipt, and again in
# the handwritten ledger as a cash receipt. Symptoms:
#   - rows table   has  (customer_name, excel_amount, policy_no)
#   - cash_rows    has  (name,          ledger_amount, policy_no)
#   - both unresolved, same customer, same amount
#
# We grade each candidate by signal strength:
#   STRONG   : policy_no matches AND amount matches  (almost certainly dup)
#   MODERATE : name matches AND amount matches, no policy match
#              (possible — same customer with multiple policies?)
#
# The accountant gets the candidates as a list and decides per row.

@app.route("/api/cross-check/duplicates")
def cross_check_duplicates():
    """List potential double-bookings spanning both pipelines."""
    db = get_db()
    sql = """
        SELECT
            r.id              AS upi_id,
            r.utr             AS upi_utr,
            r.customer_name   AS upi_name,
            r.excel_amount    AS upi_amount,
            r.bank_amount     AS upi_bank_amount,
            r.policy_no       AS upi_policy_no,
            r.branch          AS upi_branch,
            r.status          AS upi_status,
            r.resolved        AS upi_resolved,
            c.id              AS cash_id,
            c.name            AS cash_name,
            c.ledger_amount   AS cash_amount,
            c.bank_amount     AS cash_bank_amount,
            c.policy_no       AS cash_policy_no,
            c.ledger_date     AS cash_ledger_date,
            c.status          AS cash_status,
            c.resolved        AS cash_resolved
        FROM rows r
        JOIN cash_rows c
          ON UPPER(TRIM(r.customer_name)) = UPPER(TRIM(c.name))
         AND ABS(IFNULL(r.excel_amount, 0) - IFNULL(c.ledger_amount, 0)) < 0.01
         AND IFNULL(r.excel_amount, 0) > 0
        WHERE r.resolved = 0 AND c.resolved = 0
          AND r.customer_name IS NOT NULL AND r.customer_name <> ''
          AND c.name IS NOT NULL AND c.name <> ''
        ORDER BY r.customer_name, c.ledger_date
    """
    out = []
    for row in db.execute(sql).fetchall():
        d = dict(row)
        # Grade: STRONG if policy_no matches, else MODERATE.
        upi_pol = (d.get("upi_policy_no") or "").strip()
        cash_pol = (d.get("cash_policy_no") or "").strip()
        d["confidence"] = (
            "STRONG" if upi_pol and cash_pol and upi_pol == cash_pol
            else "MODERATE"
        )
        out.append(d)
    return jsonify({"duplicates": out, "count": len(out)})


EXPORT_SHEETS = [
    ("MATCHED",           {"category": "active", "status": "MATCHED"}),
    ("AMOUNT MISMATCH",   {"category": "active", "status": "MISMATCH"}),
    ("MISSING FROM BANK", {"category": "active", "status": "MISSING"}),
    ("UNRECORDED",        {"category": "active", "status": "UNRECORDED"}),
    ("BRANCH MISMATCHES", {"category": "branch_mismatch"}),
]


@app.route("/api/export/full")
def api_export_full():
    """Full-day report: every category on its own sheet."""
    db = get_db()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, where in EXPORT_SHEETS:
            clauses, params = [], []
            for k, v in where.items():
                clauses.append(f"{k} = ?")
                params.append(v)
            sql = f"SELECT * FROM rows WHERE {' AND '.join(clauses)} ORDER BY branch, customer_name"
            rows = db.execute(sql, params).fetchall()
            records = [
                {
                    "Branch": r["branch"],
                    "Bank": r["bank_code"],
                    "Customer Name": r["customer_name"],
                    "Agent ID": r["agent_id"],
                    "Policy No": r["policy_no"],
                    "Policy Type": r["policy_type"],
                    "UTR": r["utr"],
                    "Excel Amount": r["excel_amount"],
                    "Bank Amount": r["bank_amount"],
                    "Status": r["status"],
                    "Resolved": "Yes" if r["resolved"] else "",
                }
                for r in rows
            ]
            pd.DataFrame(
                records,
                columns=[
                    "Branch", "Bank", "Customer Name", "Agent ID", "Policy No",
                    "Policy Type", "UTR", "Excel Amount", "Bank Amount",
                    "Status", "Resolved",
                ],
            ).to_excel(writer, sheet_name=sheet_name, index=False)
    buf.seek(0)
    filename = f"reconciliation_full_{dt.date.today().isoformat()}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ----- Bulk resolve -----

@app.route("/api/resolve/bulk", methods=["POST"])
def api_resolve_bulk():
    """Resolve multiple current rows in one call.

    Body: {"ids": [int, int, ...]}
    Returns the count of rows actually flipped (rows already resolved or
    not found are silently skipped — bulk operations are idempotent).
    """
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids must be a non-empty list"}), 400
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "ids must be integers"}), 400

    db = get_db()
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT id, utr, status FROM rows "
        f"WHERE id IN ({placeholders}) AND resolved = 0",
        ids,
    ).fetchall()
    if not rows:
        return jsonify({"ok": True, "resolved": 0})

    db.execute(
        f"UPDATE rows SET resolved = 1 WHERE id IN ({placeholders})",
        [r["id"] for r in rows],
    )
    for r in rows:
        if r["utr"]:
            db.execute(
                "INSERT OR IGNORE INTO resolved_keys (utr, status) VALUES (?, ?)",
                (r["utr"], r["status"]),
            )
    db.commit()
    return jsonify({"ok": True, "resolved": len(rows)})


@app.route("/api/flags/bulk-resolve", methods=["POST"])
def api_flags_bulk_resolve():
    """Resolve multiple historical flags with one shared reason.

    Multipart form fields:
      - ids:        repeatable form field, integer flag ids
      - reason:     required, applied to every resolved flag
      - attachment: optional, single file shared across all resolved flags
                    (the same stored filename is recorded on each row).

    Or JSON body: {"ids": [int], "reason": str}.
    """
    attachment = None
    reason = ""
    ids = []

    if request.content_type and request.content_type.startswith("multipart/"):
        reason = (request.form.get("reason") or "").strip()
        attachment = request.files.get("attachment")
        ids = request.form.getlist("ids")
    else:
        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()
        ids = data.get("ids") or []

    if not reason:
        return jsonify({"error": "Reason is required"}), 400
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids must be a non-empty list"}), 400
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "ids must be integers"}), 400

    db = get_db()
    placeholders = ",".join("?" * len(ids))
    open_rows = db.execute(
        f"SELECT id FROM historical_flags "
        f"WHERE id IN ({placeholders}) AND resolved_at IS NULL",
        ids,
    ).fetchall()
    if not open_rows:
        return jsonify({"ok": True, "resolved": 0})

    stored_attachment = None
    if attachment and attachment.filename:
        safe = re.sub(r"[^a-zA-Z0-9._-]", "_", attachment.filename)
        stored_attachment = (
            f"bulk_{int(dt.datetime.now().timestamp() * 1000)}_{safe}"
        )
        attachment.save(os.path.join(RESOLVE_ATTACH_DIR, stored_attachment))

    now = dt.datetime.now().isoformat()
    open_ids = [r["id"] for r in open_rows]
    open_placeholders = ",".join("?" * len(open_ids))
    db.execute(
        f"""UPDATE historical_flags
            SET resolved_at = ?, resolved_by = 'manual',
                resolved_reason = ?, resolved_attachment = ?
            WHERE id IN ({open_placeholders})""",
        [now, reason, stored_attachment, *open_ids],
    )
    db.commit()
    return jsonify({
        "ok": True,
        "resolved": len(open_ids),
        "attachment": stored_attachment,
    })


# ----- Comprehensive reconciliation report -----

def _read_query_records(db, sql, params, mapper):
    return [mapper(r) for r in db.execute(sql, params).fetchall()]


@app.route("/api/report/comprehensive")
def api_report_comprehensive():
    """Build a multi-sheet Excel covering the entire reconciliation state.

    Sheets:
      - Summary:           top-line counts + totals + per-status sums
      - Per-Bank:          rows-by-bank breakdown (matched/mismatch/etc.)
      - Per-Branch:        rows-by-branch breakdown
      - Daily:             per-date counts and totals
      - MATCHED:           every matched row
      - MISMATCH:          every amount-mismatch row
      - MISSING:           every missing-from-bank row
      - UNRECORDED:        every unrecorded-in-excel row
      - CANARA_PENDING:    every pending row (no statement uploaded yet)
      - DUPLICATE:         every duplicate row
      - BANK_CHARGE:       every parsed bank charge / fee
      - BRANCH_MISMATCH:   policy-vs-branch-name mismatches
      - Open Flags:        all open historical flags
      - Resolved Flags:    every resolved historical flag with reason
      - Bank Statements:   the upload library
    """
    db = get_db()
    today = dt.date.today().isoformat()
    summary = _summary_counts()

    # ----- Sheet: Summary -----
    tally_row = db.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN status IN ('MATCHED','MISMATCH','MISSING')
                            THEN excel_amount END), 0) AS branches_total,
          COALESCE(SUM(CASE WHEN status IN ('MATCHED','MISMATCH','UNRECORDED')
                            THEN bank_amount END), 0) AS bank_total,
          COALESCE(SUM(CASE WHEN status='BANK_CHARGE' THEN bank_amount END), 0) AS charges_total
        FROM rows WHERE category IN ('active','bank_charge')
        """
    ).fetchone()
    summary_records = [
        {"Metric": "Report generated",        "Value": dt.datetime.now().isoformat()},
        {"Metric": "Matched (count)",         "Value": summary["matched"]},
        {"Metric": "Amount mismatch (count)", "Value": summary["mismatch"]},
        {"Metric": "Missing from bank (count)", "Value": summary["missing"]},
        {"Metric": "Unrecorded in Excel (count)", "Value": summary["unrecorded"]},
        {"Metric": "Pending statement (count)", "Value": summary["canara_pending"]},
        {"Metric": "Bank charges (count)",    "Value": summary["bank_charge"]},
        {"Metric": "Branch total (₹)",        "Value": float(tally_row["branches_total"])},
        {"Metric": "Bank total (₹)",          "Value": float(tally_row["bank_total"])},
        {"Metric": "Difference (Bank − Branch) (₹)",
         "Value": float(tally_row["bank_total"]) - float(tally_row["branches_total"])},
        {"Metric": "Bank charges total (₹)",  "Value": float(tally_row["charges_total"])},
    ]

    # ----- Sheet: Per-Bank -----
    per_bank = db.execute(
        """
        SELECT COALESCE(bank_code,'') AS bank,
               SUM(CASE WHEN status='MATCHED' THEN 1 ELSE 0 END) AS matched,
               SUM(CASE WHEN status='MISMATCH' THEN 1 ELSE 0 END) AS mismatch,
               SUM(CASE WHEN status='UNRECORDED' THEN 1 ELSE 0 END) AS unrecorded,
               SUM(CASE WHEN status='BANK_CHARGE' THEN 1 ELSE 0 END) AS charges,
               COALESCE(SUM(CASE WHEN status IN ('MATCHED','MISMATCH','UNRECORDED')
                                 THEN bank_amount END), 0) AS bank_total
        FROM rows WHERE category IN ('active','bank_charge')
        GROUP BY COALESCE(bank_code,'')
        ORDER BY bank
        """
    ).fetchall()
    per_bank_records = [
        {
            "Bank":       r["bank"] or "—",
            "Matched":    r["matched"] or 0,
            "Mismatch":   r["mismatch"] or 0,
            "Unrecorded": r["unrecorded"] or 0,
            "Charges":    r["charges"] or 0,
            "Bank Total (₹)": float(r["bank_total"] or 0),
        }
        for r in per_bank
    ]

    # ----- Sheet: Per-Branch -----
    per_branch = db.execute(
        """
        SELECT COALESCE(branch,'') AS branch,
               SUM(CASE WHEN status='MATCHED' THEN 1 ELSE 0 END) AS matched,
               SUM(CASE WHEN status='MISMATCH' THEN 1 ELSE 0 END) AS mismatch,
               SUM(CASE WHEN status='MISSING' THEN 1 ELSE 0 END) AS missing,
               SUM(CASE WHEN status='CANARA_PENDING' THEN 1 ELSE 0 END) AS pending,
               COALESCE(SUM(CASE WHEN status IN ('MATCHED','MISMATCH','MISSING')
                                 THEN excel_amount END), 0) AS branch_total
        FROM rows WHERE category = 'active' AND branch != ''
        GROUP BY branch
        ORDER BY branch
        """
    ).fetchall()
    per_branch_records = [
        {
            "Branch":     r["branch"],
            "Matched":    r["matched"] or 0,
            "Mismatch":   r["mismatch"] or 0,
            "Missing":    r["missing"] or 0,
            "Pending":    r["pending"] or 0,
            "Branch Total (₹)": float(r["branch_total"] or 0),
        }
        for r in per_branch
    ]

    # ----- Sheet: Daily breakdown (from historical_flags) -----
    daily = db.execute(
        """
        SELECT date,
               SUM(CASE WHEN resolved_at IS NULL THEN 1 ELSE 0 END) AS open_count,
               SUM(CASE WHEN resolved_at IS NOT NULL THEN 1 ELSE 0 END) AS resolved_count,
               COUNT(*) AS total
        FROM historical_flags
        WHERE date IS NOT NULL AND date != ''
        GROUP BY date
        ORDER BY date DESC
        """
    ).fetchall()
    daily_records = [
        {
            "Date":     r["date"],
            "Open":     r["open_count"] or 0,
            "Resolved": r["resolved_count"] or 0,
            "Total":    r["total"] or 0,
        }
        for r in daily
    ]

    # ----- Sheet: Bank Statement Library -----
    library = db.execute(
        "SELECT date, bank_code, filename, credits, uploaded_at "
        "FROM bank_statements ORDER BY date DESC, bank_code"
    ).fetchall()
    library_records = [
        {
            "Date":        r["date"],
            "Bank":        r["bank_code"],
            "Filename":    r["filename"],
            "Credits":     r["credits"] or 0,
            "Uploaded At": r["uploaded_at"],
        }
        for r in library
    ]

    # ----- Per-status detail sheets -----
    detail_sheets = [
        ("MATCHED",         "category='active' AND status='MATCHED'"),
        ("MISMATCH",        "category='active' AND status='MISMATCH'"),
        ("MISSING",         "category='active' AND status='MISSING'"),
        ("UNRECORDED",      "category='active' AND status='UNRECORDED'"),
        ("CANARA_PENDING",  "category='active' AND status='CANARA_PENDING'"),
        ("DUPLICATE",       "category='active' AND status='DUPLICATE'"),
        ("BANK_CHARGE",     "category='bank_charge'"),
        ("BRANCH_MISMATCH", "category='branch_mismatch'"),
    ]

    def _row_record(r):
        return {
            "Date":          r["pending_date"] or "",
            "Bank":          r["bank_code"],
            "Branch":        r["branch"],
            "Customer":      r["customer_name"],
            "Agent ID":      r["agent_id"],
            "Policy No":     r["policy_no"],
            "Policy Type":   r["policy_type"],
            "UTR":           r["utr"],
            "Excel Amount":  r["excel_amount"],
            "Bank Amount":   r["bank_amount"],
            "Status":        r["status"],
            "Resolved":      "Yes" if r["resolved"] else "",
        }

    detail_records = {}
    for sheet_name, where in detail_sheets:
        rows = db.execute(
            f"SELECT * FROM rows WHERE {where} ORDER BY branch, customer_name"
        ).fetchall()
        detail_records[sheet_name] = [_row_record(r) for r in rows]

    # ----- Open + resolved historical flags -----
    open_flags = db.execute(
        """SELECT date, branch, customer_name, agent_id, utr,
                  excel_amount, bank_amount, status, bank_code, created_at
           FROM historical_flags WHERE resolved_at IS NULL
           ORDER BY date DESC, id DESC"""
    ).fetchall()
    resolved_flags = db.execute(
        """SELECT date, branch, customer_name, agent_id, utr,
                  excel_amount, bank_amount, status, bank_code,
                  resolved_at, resolved_by, resolved_reason
           FROM historical_flags WHERE resolved_at IS NOT NULL
           ORDER BY resolved_at DESC"""
    ).fetchall()
    open_flag_records = [
        {
            "Date":           r["date"],
            "Bank":           r["bank_code"],
            "Branch":         r["branch"],
            "Customer":       r["customer_name"],
            "Agent ID":       r["agent_id"],
            "UTR":            r["utr"],
            "Excel Amount":   r["excel_amount"],
            "Bank Amount":    r["bank_amount"],
            "Status":         r["status"],
            "First Flagged":  r["created_at"],
        }
        for r in open_flags
    ]
    resolved_flag_records = [
        {
            "Date":            r["date"],
            "Bank":            r["bank_code"],
            "Branch":          r["branch"],
            "Customer":        r["customer_name"],
            "Agent ID":        r["agent_id"],
            "UTR":             r["utr"],
            "Excel Amount":    r["excel_amount"],
            "Bank Amount":     r["bank_amount"],
            "Status":          r["status"],
            "Resolved At":     r["resolved_at"],
            "Resolved By":     r["resolved_by"],
            "Reason":          r["resolved_reason"],
        }
        for r in resolved_flags
    ]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(summary_records).to_excel(
            writer, sheet_name="Summary", index=False
        )
        if per_bank_records:
            pd.DataFrame(per_bank_records).to_excel(
                writer, sheet_name="Per-Bank", index=False
            )
        if per_branch_records:
            pd.DataFrame(per_branch_records).to_excel(
                writer, sheet_name="Per-Branch", index=False
            )
        if daily_records:
            pd.DataFrame(daily_records).to_excel(
                writer, sheet_name="Daily", index=False
            )
        for sheet_name, records in detail_records.items():
            if records:
                pd.DataFrame(records).to_excel(
                    writer, sheet_name=sheet_name, index=False
                )
        if open_flag_records:
            pd.DataFrame(open_flag_records).to_excel(
                writer, sheet_name="Open Flags", index=False
            )
        if resolved_flag_records:
            pd.DataFrame(resolved_flag_records).to_excel(
                writer, sheet_name="Resolved Flags", index=False
            )
        if library_records:
            pd.DataFrame(library_records).to_excel(
                writer, sheet_name="Bank Statements", index=False
            )

    buf.seek(0)
    filename = f"reconciliation_report_{today}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
