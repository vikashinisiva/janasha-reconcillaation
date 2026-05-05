"""
Reconciliation library for Janaasha Nidhi.

Reads bank statements (Canara / SBI / KVB / IOB / Axis) + one or more branch
Excel files and produces matched / mismatch / missing / unrecorded row sets
plus a branch-mismatch check based on decoded policy numbers. Imported by the
Flask app — no CLI.
"""

import os
import re
import pandas as pd

UTR_REGEX = re.compile(r"UPI/CR/(\d{9,12})/")

# Bank-side debit lines that look like fees/charges/interest rather than
# customer activity. Surfaced separately so they don't pollute the
# UNRECORDED-IN-EXCEL bucket (which is supposed to be real customer
# credits the branch missed logging).
CHARGE_PATTERNS = re.compile(
    r"(CHRG|CHARGE|CGST|SGST|IGST|GST|"
    r"SMS[\s-]*ALERT|SMS[\s-]*CHARGE|"
    r"AMC|ATM[\s-]*FEE|"
    r"INT\.?\s*PD|INT[\s-]*PAID|INTEREST[\s-]*PAID|"
    r"PENALTY|FEE|TAX|MIN[\s-]*BAL|MAB[\s-]*CHRG|"
    r"SERVICE[\s-]*CH|MAINTENANCE|FOLIO)",
    re.IGNORECASE,
)

SUPPORTED_BANKS = ["CANARA", "SBI", "KVB", "IOB", "AXIS"]
BANK_LABELS = {
    "CANARA": "Canara",
    "SBI":    "State Bank of India",
    "KVB":    "Karur Vysya Bank",
    "IOB":    "Indian Overseas Bank",
    "AXIS":   "Axis Bank",
}


def normalize_date(v):
    """Coerce various pandas/Excel date values to a YYYY-MM-DD string.
    Returns None for blanks or unparseable values.
    """
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%Y-%m-%d")
        except Exception:
            pass
    s = str(v).strip()
    if not s:
        return None
    # Try ISO (YYYY-MM-DD) first so "2026-04-01" isn't misread as day-first.
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        try:
            return pd.to_datetime(s).strftime("%Y-%m-%d")
        except Exception:
            pass
    try:
        return pd.to_datetime(s, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def _file_ext(path):
    return os.path.splitext(path)[1].lower()


def _read_excel_any(path, **kwargs):
    """Read an Excel file regardless of .xls vs .xlsx. xlrd only handles
    legacy .xls; openpyxl handles .xlsx."""
    if _file_ext(path) == ".xlsx":
        return pd.read_excel(path, engine="openpyxl", **kwargs)
    return pd.read_excel(path, engine="xlrd", **kwargs)


def _find_header_row(raw_df):
    """Locate the data-table header row in a raw (header=None) read.
    Looks for a row containing 'Date' plus 'Remarks' or 'Particulars'.
    Returns the 0-based row index, or None if not found.
    """
    for i in range(min(len(raw_df), 30)):
        cells = [str(c).strip().lower() for c in raw_df.iloc[i].values]
        if "date" in cells and any(
            c in cells for c in ("remarks", "particulars")
        ):
            return i
    return None


def _load_canara_table(path):
    """Format-tolerant Canara loader: returns (data_df, preheader_rows).

    Accepts .xls, .xlsx, and .csv. Scans for the header row so a template
    that drifts from the canonical 'header=9' layout still parses. The
    pre-header rows (statement metadata: opening / closing balance, totals)
    are returned alongside so the integrity check can read them.
    """
    ext = _file_ext(path)
    if ext == ".csv":
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
        idx = _find_header_row(raw)
        if idx is None:
            raise RuntimeError(
                "Could not locate header row in CSV — expected 'Date' + "
                "'Remarks'/'Particulars' columns somewhere in the first 30 rows."
            )
        preheader = raw.iloc[:idx].values.tolist()
        df = pd.read_csv(path, header=idx)
    else:
        raw = _read_excel_any(path, header=None)
        idx = _find_header_row(raw)
        if idx is None:
            idx = 9  # canonical Canara template
        preheader = raw.iloc[:idx].values.tolist()
        df = _read_excel_any(path, header=idx)
    df.columns = [str(c).strip() for c in df.columns]
    return df, preheader


def _canara_cols(df):
    """Locate the relevant Canara columns by lowercased name."""
    cols = {str(c).strip().lower(): c for c in df.columns}
    return {
        "remarks": next(
            (cols[k] for k in ("remarks", "particulars", "narration", "description")
             if k in cols), None,
        ),
        "deposit": next(
            (cols[k] for k in ("deposits", "deposit", "credit", "credits", "cr amount")
             if k in cols), None,
        ),
        "withdrawal": next(
            (cols[k] for k in ("withdrawals", "withdrawal", "debit", "debits", "dr amount")
             if k in cols), None,
        ),
        "date": next(
            (cols[k] for k in ("date", "txn date", "transaction date", "value date")
             if k in cols), None,
        ),
        "balance": next(
            (cols[k] for k in ("balance", "running balance", "closing balance")
             if k in cols), None,
        ),
    }


def _peek_canara_date(path):
    """Read just enough of a Canara statement (XLS/XLSX/CSV) to discover
    its statement date. Returns the first valid date in the Date column
    as YYYY-MM-DD, or None.
    """
    df, _ = _load_canara_table(path)
    cols = _canara_cols(df)
    if not cols["date"]:
        return None
    for v in df[cols["date"]]:
        d = normalize_date(v)
        if d:
            return d
    return None


# Until real samples arrive for SBI/KVB/IOB/Axis, each placeholder falls
# back to the Canara layout. Replace each function body once you have a
# representative statement file for that bank.
_peek_sbi_date  = _peek_canara_date  # TODO: verify against real SBI sample
_peek_kvb_date  = _peek_canara_date  # TODO: verify against real KVB sample
_peek_iob_date  = _peek_canara_date  # TODO: verify against real IOB sample
_peek_axis_date = _peek_canara_date  # TODO: verify against real Axis sample

PEEK_DATE_BY_BANK = {
    "CANARA": _peek_canara_date,
    "SBI":    _peek_sbi_date,
    "KVB":    _peek_kvb_date,
    "IOB":    _peek_iob_date,
    "AXIS":   _peek_axis_date,
}


def peek_bank_date(path, bank_code="CANARA"):
    """Dispatch to the right per-bank peek function.
    Returns the statement's first-row date as YYYY-MM-DD, or None.
    """
    fn = PEEK_DATE_BY_BANK.get((bank_code or "").upper())
    if fn is None:
        raise ValueError(f"Unknown bank code: {bank_code}")
    return fn(path)


# Backwards-compat alias for existing callers.
peek_canara_date = _peek_canara_date
AMOUNT_TOLERANCE = 0.01

REQUIRED_CORP_COLS = {
    "BRANCH NAME",
    "CUSTOMER NAME",
    "AGENT ID",
    "AMOUNT",
}

OUTPUT_COLS = [
    "Branch",
    "Customer Name",
    "Agent ID",
    "Policy No",
    "Policy Type",
    "UTR",
    "Excel Amount",
    "Bank Amount",
    "Status",
]

POLICY_TYPE_MAP = {"3": "RD", "4": "FD", "5": "MIS", "6": "DRD"}

BRANCH_CODE_MAP = {
    "001": "Coimbatore", "002": "Ooty", "003": "Erode", "004": "Gudalur",
    "005": "Kotagiri", "006": "PNP Rural", "007": "NSN Palayam", "008": "Sholur",
    "009": "Yedakadu", "010": "Manjoor", "011": "Kochadai", "012": "Salem",
    "013": "Rasipuram", "014": "Tiruchengode", "015": "PNP Town", "016": "Coonoor",
    "017": "Mettupalayam", "018": "Yellanalli", "019": "Karamadai", "020": "Ithalar",
    "021": "Sirumugai", "022": "Kavundampalayam", "023": "Tirupur 1", "024": "Tirupur 2",
    "025": "Avinashi", "026": "Annur", "027": "Kovilpalayam", "028": "Saravanampatti",
    "029": "Singanallur", "030": "Kamarajar Salai", "031": "Simmakkal", "032": "Mattuthavani",
    "033": "Agalar", "034": "Ganapathy", "035": "Anthiyur", "036": "Namakkal",
    "037": "Omalur", "038": "Aruvangadu", "039": "Selas", "040": "Pandalur",
    "041": "Cherambadi", "042": "Devarshola", "043": "Kattabettu", "044": "M.Palada",
    "045": "Denadukombai", "046": "Vadavalli", "047": "Tirunelveli", "048": "Kacheri",
}


def clean_utr(value):
    if pd.isna(value):
        return None
    s = str(value).strip()
    if not s or s.lower() == "total":
        return None
    try:
        return str(int(float(s)))
    except (ValueError, OverflowError):
        return None


def parse_amount(value):
    if pd.isna(value):
        return None
    s = str(value).replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_utr_column(columns):
    for c in columns:
        if "UTR" in str(c).upper():
            return c
    return None


def find_policy_column(columns):
    for c in columns:
        u = str(c).upper()
        if "POLICY" in u and ("NO" in u or "NUMBER" in u or u.strip() == "POLICY"):
            return c
    return None


def normalize_branch_name(name):
    if name is None:
        return ""
    try:
        if pd.isna(name):
            return ""
    except (TypeError, ValueError):
        pass
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def decode_policy_number(value):
    """Return (branch_code, type_digit, policy_type, branch_name) or all None."""
    if pd.isna(value):
        return None, None, None, None
    s = str(value).strip()
    try:
        s = str(int(float(s)))
    except (ValueError, OverflowError):
        pass
    if s.isdigit() and len(s) < 9:
        s = s.zfill(9)
    if not (len(s) == 9 and s.isdigit()):
        return None, None, None, None
    branch_code = s[:3]
    type_digit = s[3]
    return (
        branch_code,
        type_digit,
        POLICY_TYPE_MAP.get(type_digit),
        BRANCH_CODE_MAP.get(branch_code),
    )


def read_corporate(path):
    """Read all branch sheets, concat into one dataframe with cleaned UTRs."""
    xls = pd.ExcelFile(path, engine="xlrd")
    frames = []
    skipped = []

    for sheet in xls.sheet_names:
        if "LOAN" in sheet.upper():
            skipped.append((sheet, "loan disbursement sheet"))
            continue

        # Header is on the second row (row 0 is a section title).
        try:
            df = pd.read_excel(xls, sheet_name=sheet, header=1)
        except Exception as e:
            skipped.append((sheet, f"read error: {e}"))
            continue

        df.columns = [str(c).strip() for c in df.columns]
        utr_col = find_utr_column(df.columns)

        if utr_col is None or not REQUIRED_CORP_COLS.issubset(set(df.columns)):
            skipped.append((sheet, "missing required columns"))
            continue

        df = df.rename(columns={utr_col: "UTR"})
        df["UTR"] = df["UTR"].apply(clean_utr)
        df = df.dropna(subset=["UTR"])
        df["AMOUNT"] = df["AMOUNT"].apply(parse_amount)
        df = df.dropna(subset=["AMOUNT"])

        policy_col = find_policy_column(df.columns)
        if policy_col is not None:
            df["policy_no_raw"] = df[policy_col].astype(str).str.strip()
            decoded = df[policy_col].apply(decode_policy_number)
            df["decoded_branch_code"] = [d[0] for d in decoded]
            df["decoded_policy_type"] = [d[2] for d in decoded]
            df["decoded_branch_name"] = [d[3] for d in decoded]
        else:
            df["policy_no_raw"] = None
            df["decoded_branch_code"] = None
            df["decoded_policy_type"] = None
            df["decoded_branch_name"] = None

        df["__sheet__"] = sheet
        frames.append(df)

    if not any(
        f["decoded_branch_code"].notna().any() for f in frames
    ):
        print(
            "Note: no policy number column detected in corporate file "
            "-- branch mismatch validation will be empty."
        )

    if skipped:
        print("Skipped sheets:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")

    if not frames:
        raise RuntimeError("No valid branch sheets found in corporate file.")

    master = pd.concat(frames, ignore_index=True)
    return master


def _read_canara(path):
    """Extract UPI credit rows from the Canara statement (XLS/XLSX/CSV)."""
    df, _ = _load_canara_table(path)
    cols = _canara_cols(df)
    if cols["remarks"] is None or cols["deposit"] is None:
        raise RuntimeError(
            f"Bank file missing expected columns. Got: {list(df.columns)}"
        )

    if cols["date"] is not None:
        df = df[df[cols["date"]].notna()]

    df[cols["remarks"]] = df[cols["remarks"]].astype(str)
    df["UTR"] = df[cols["remarks"]].apply(
        lambda s: (m.group(1) if (m := UTR_REGEX.search(s)) else None)
    )
    df = df[df["UTR"].notna()].copy()
    df["Bank Amount"] = df[cols["deposit"]].apply(parse_amount)
    df = df.dropna(subset=["Bank Amount"])

    return df[["UTR", "Bank Amount", cols["remarks"]]].rename(
        columns={cols["remarks"]: "Particulars"}
    )


def _read_canara_charges(path):
    """Extract bank-side charge / fee rows from the Canara statement.

    Looks at the withdrawals column for rows whose remarks match the
    CHARGE_PATTERNS regex. Returns a DataFrame with columns:
    Date, Bank Amount, Particulars. Bank Amount is positive (the size
    of the charge), not signed.
    """
    df, _ = _load_canara_table(path)
    cols = _canara_cols(df)
    if cols["remarks"] is None or cols["withdrawal"] is None:
        # No withdrawal column → nothing to extract. Return an empty frame
        # rather than raising, since charges are an optional enhancement.
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])

    if cols["date"] is not None:
        df = df[df[cols["date"]].notna()].copy()

    df[cols["remarks"]] = df[cols["remarks"]].astype(str)
    df["__amt__"] = df[cols["withdrawal"]].apply(parse_amount)
    df = df[df["__amt__"].notna() & (df["__amt__"] > 0)]
    mask = df[cols["remarks"]].str.contains(CHARGE_PATTERNS, na=False)
    df = df[mask].copy()
    if df.empty:
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])

    df["Date"] = (
        df[cols["date"]].apply(normalize_date) if cols["date"] else None
    )
    df["Bank Amount"] = df["__amt__"]
    df["Particulars"] = df[cols["remarks"]]
    return df[["Date", "Bank Amount", "Particulars"]].reset_index(drop=True)


def _peek_balance_value(preheader, label_keywords):
    """Search the pre-header metadata block for a labelled value.
    Returns the first numeric value found in a row whose first non-empty
    cell contains any of the label keywords (case-insensitive), or None.
    """
    for row in preheader:
        cells = [str(c).strip() for c in row if str(c).strip() and str(c).strip().lower() != "nan"]
        if not cells:
            continue
        joined = " ".join(cells).lower()
        if not any(kw in joined for kw in label_keywords):
            continue
        for cell in cells:
            v = parse_amount(cell)
            if v is not None:
                return v
    return None


def _check_canara_balance(path):
    """Best-effort statement-integrity check.

    Reads the Canara statement's pre-header metadata block (rows above
    the data table) to pull declared totals, then compares against the
    sum of the parsed credit / debit columns. Returns a dict:

      {
        "ok": bool,           # all detected checks passed
        "warnings": [str],    # human-readable warnings
        "stats": {            # whatever was extractable
          "rows": int,
          "credits_sum": float | None,
          "debits_sum": float | None,
          "declared_credits": float | None,
          "declared_debits": float | None,
          "opening_balance": float | None,
          "closing_balance": float | None,
        },
      }

    All checks are best-effort — if the metadata isn't where we expect,
    we return ok=True with no warnings rather than blocking the upload.
    """
    df, preheader = _load_canara_table(path)
    cols = _canara_cols(df)

    warnings = []
    stats = {
        "rows": int(len(df)),
        "credits_sum": None,
        "debits_sum": None,
        "declared_credits": None,
        "declared_debits": None,
        "opening_balance": None,
        "closing_balance": None,
    }

    if cols["deposit"]:
        stats["credits_sum"] = float(
            df[cols["deposit"]].apply(parse_amount).fillna(0).sum()
        )
    if cols["withdrawal"]:
        stats["debits_sum"] = float(
            df[cols["withdrawal"]].apply(parse_amount).fillna(0).sum()
        )

    stats["declared_credits"] = _peek_balance_value(
        preheader, ["total deposit", "total credit", "total credits"]
    )
    stats["declared_debits"] = _peek_balance_value(
        preheader, ["total withdrawal", "total debit", "total debits"]
    )
    stats["opening_balance"] = _peek_balance_value(
        preheader, ["opening balance", "opening bal"]
    )
    stats["closing_balance"] = _peek_balance_value(
        preheader, ["closing balance", "closing bal"]
    )

    # Tolerance: 1 paise per row, capped at ₹1 for full statements.
    tol = max(1.0, stats["rows"] * 0.01)

    if (stats["declared_credits"] is not None
            and stats["credits_sum"] is not None
            and abs(stats["declared_credits"] - stats["credits_sum"]) > tol):
        warnings.append(
            f"Declared total credits ({stats['declared_credits']:.2f}) does "
            f"not match parsed credits ({stats['credits_sum']:.2f})."
        )

    if (stats["declared_debits"] is not None
            and stats["debits_sum"] is not None
            and abs(stats["declared_debits"] - stats["debits_sum"]) > tol):
        warnings.append(
            f"Declared total debits ({stats['declared_debits']:.2f}) does "
            f"not match parsed debits ({stats['debits_sum']:.2f})."
        )

    if (stats["opening_balance"] is not None
            and stats["closing_balance"] is not None
            and stats["credits_sum"] is not None
            and stats["debits_sum"] is not None):
        derived = (
            stats["opening_balance"]
            + stats["credits_sum"]
            - stats["debits_sum"]
        )
        if abs(derived - stats["closing_balance"]) > tol:
            warnings.append(
                f"Running balance off: opening ({stats['opening_balance']:.2f}) "
                f"+ credits ({stats['credits_sum']:.2f}) − debits "
                f"({stats['debits_sum']:.2f}) = {derived:.2f}, but the "
                f"statement declares closing balance {stats['closing_balance']:.2f}."
            )

    if stats["rows"] == 0:
        warnings.append("Statement contains no transaction rows.")

    return {"ok": not warnings, "warnings": warnings, "stats": stats}


# Placeholder parsers — each currently delegates to the Canara parser.
# When a real SBI/KVB/IOB/Axis statement sample arrives, replace the
# matching function body (keep the return-shape contract:
# columns UTR, Bank Amount, Particulars).
_read_sbi  = _read_canara  # TODO: implement once an SBI sample is on hand
_read_kvb  = _read_canara  # TODO: implement once a KVB sample is on hand
_read_iob  = _read_canara  # TODO: implement once an IOB sample is on hand
_read_axis = _read_canara  # TODO: implement once an Axis sample is on hand

READ_BANK_BY_CODE = {
    "CANARA": _read_canara,
    "SBI":    _read_sbi,
    "KVB":    _read_kvb,
    "IOB":    _read_iob,
    "AXIS":   _read_axis,
}

READ_CHARGES_BY_CODE = {
    "CANARA": _read_canara_charges,
    "SBI":    _read_canara_charges,
    "KVB":    _read_canara_charges,
    "IOB":    _read_canara_charges,
    "AXIS":   _read_canara_charges,
}

CHECK_BALANCE_BY_CODE = {
    "CANARA": _check_canara_balance,
    "SBI":    _check_canara_balance,
    "KVB":    _check_canara_balance,
    "IOB":    _check_canara_balance,
    "AXIS":   _check_canara_balance,
}


def read_bank(path, bank_code="CANARA"):
    """Dispatch to the right per-bank parser.
    Returns a DataFrame with columns: UTR, Bank Amount, Particulars.
    """
    fn = READ_BANK_BY_CODE.get((bank_code or "").upper())
    if fn is None:
        raise ValueError(f"Unknown bank code: {bank_code}")
    return fn(path)


def read_bank_charges(path, bank_code="CANARA"):
    """Dispatch to the right per-bank charges parser.
    Returns a DataFrame with columns: Date, Bank Amount, Particulars.
    """
    fn = READ_CHARGES_BY_CODE.get((bank_code or "").upper())
    if fn is None:
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])
    return fn(path)


def check_statement_integrity(path, bank_code="CANARA"):
    """Dispatch to the right per-bank integrity check.
    Returns {"ok": bool, "warnings": [str], "stats": {...}}.
    """
    fn = CHECK_BALANCE_BY_CODE.get((bank_code or "").upper())
    if fn is None:
        return {"ok": True, "warnings": [], "stats": {}}
    try:
        return fn(path)
    except Exception as e:
        return {
            "ok": False,
            "warnings": [f"Could not run integrity check: {e}"],
            "stats": {},
        }


def build_excel_row(excel_row, bank_amount, status, bank_code=None):
    return {
        "Branch": excel_row.get("BRANCH NAME", ""),
        "Customer Name": excel_row.get("CUSTOMER NAME", ""),
        "Agent ID": excel_row.get("AGENT ID", ""),
        "Policy No": excel_row.get("policy_no_raw"),
        "Policy Type": excel_row.get("decoded_policy_type"),
        "UTR": excel_row["UTR"],
        "Excel Amount": excel_row["AMOUNT"],
        "Bank Amount": bank_amount,
        "Bank Code": bank_code,
        "Status": status,
    }


def find_branch_mismatches(corp_df):
    """Rows where the decoded branch from policy number doesn't match
    the recorded BRANCH NAME. Rows without a valid policy number are skipped.
    """
    rows = []
    for _, r in corp_df.iterrows():
        decoded = r.get("decoded_branch_name")
        if decoded is None or (isinstance(decoded, float) and pd.isna(decoded)):
            continue
        recorded = r.get("BRANCH NAME", "")
        if normalize_branch_name(recorded) == normalize_branch_name(decoded):
            continue
        rows.append(
            {
                "Branch": recorded,
                "Customer Name": r.get("CUSTOMER NAME", ""),
                "Agent ID": r.get("AGENT ID", ""),
                "Policy No": r.get("policy_no_raw"),
                "Policy Type": r.get("decoded_policy_type"),
                "UTR": r["UTR"],
                "Excel Amount": r["AMOUNT"],
                "Bank Amount": None,
                "Bank Code": None,
                "Status": f"BRANCH MISMATCH (policy says {decoded})",
            }
        )
    return rows


def reconcile(corp_df, bank_df):
    """Match branch-recorded rows against the merged bank-side pool for a date.

    bank_df may carry a "Bank Code" column (when multiple banks' statements
    have been merged for a given date); if absent, matches are tagged with
    bank_code=None and callers can fall back to their own context.

    Returns (matched, mismatch, missing, unrecorded, duplicates). Duplicates
    surface UTRs that appear more than once on either side for a single
    date — a strong signal of a double-entry or a bank re-post. Duplicate
    rows are excluded from the normal match buckets so they don't produce
    misleading MATCHED/MISSING pairs.
    """
    has_bank_code = "Bank Code" in bank_df.columns

    # Detect duplicates on both sides before matching.
    dup_utrs_bank = set(
        bank_df["UTR"][bank_df["UTR"].duplicated(keep=False)].unique()
    )
    dup_utrs_corp = set(
        corp_df["UTR"][corp_df["UTR"].duplicated(keep=False)].unique()
    )
    dup_utrs = dup_utrs_bank | dup_utrs_corp

    duplicates = []
    if dup_utrs:
        for _, row in corp_df[corp_df["UTR"].isin(dup_utrs)].iterrows():
            side = "branch" if row["UTR"] in dup_utrs_corp else "bank"
            duplicates.append(
                build_excel_row(
                    row,
                    None,
                    f"DUPLICATE ({side})",
                    None,
                )
            )
        for _, row in bank_df[bank_df["UTR"].isin(dup_utrs_bank)].iterrows():
            duplicates.append(
                {
                    "Branch": "",
                    "Customer Name": "",
                    "Agent ID": "",
                    "Policy No": None,
                    "Policy Type": None,
                    "UTR": row["UTR"],
                    "Excel Amount": None,
                    "Bank Amount": row["Bank Amount"],
                    "Bank Code": row["Bank Code"] if has_bank_code else None,
                    "Status": "DUPLICATE (bank)",
                }
            )

    # Exclude duplicate UTRs from the normal match paths so a double-entered
    # UTR doesn't accidentally count as two MATCHED rows.
    corp_df = corp_df[~corp_df["UTR"].isin(dup_utrs)]
    bank_df = bank_df[~bank_df["UTR"].isin(dup_utrs)]

    bank_map = {}
    for _, r in bank_df.iterrows():
        utr = r["UTR"]
        if utr in bank_map:
            continue
        bank_map[utr] = (
            r["Bank Amount"],
            r["Bank Code"] if has_bank_code else None,
        )

    matched, mismatch, missing = [], [], []

    for _, row in corp_df.iterrows():
        utr = row["UTR"]
        excel_amt = row["AMOUNT"]
        if utr not in bank_map:
            missing.append(build_excel_row(row, None, "MISSING FROM BANK"))
            continue
        bank_amt, bank_code = bank_map[utr]
        if abs(bank_amt - excel_amt) <= AMOUNT_TOLERANCE:
            matched.append(build_excel_row(row, bank_amt, "MATCHED", bank_code))
        else:
            mismatch.append(
                build_excel_row(row, bank_amt, "AMOUNT MISMATCH", bank_code)
            )

    excel_utrs = set(corp_df["UTR"])
    unrecorded = []
    for _, row in bank_df.iterrows():
        if row["UTR"] in excel_utrs:
            continue
        unrecorded.append(
            {
                "Branch": "",
                "Customer Name": "",
                "Agent ID": "",
                "Policy No": None,
                "Policy Type": None,
                "UTR": row["UTR"],
                "Excel Amount": None,
                "Bank Amount": row["Bank Amount"],
                "Bank Code": row["Bank Code"] if has_bank_code else None,
                "Status": "UNRECORDED IN EXCEL",
            }
        )

    return matched, mismatch, missing, unrecorded, duplicates
