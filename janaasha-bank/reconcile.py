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
    r"(?:CHRG|CHARGE|CGST|SGST|IGST|GST|"
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


def peek_bank_date(path, bank_code="CANARA"):
    """Dispatch to the right per-bank peek function.
    Returns the statement's first-row date as YYYY-MM-DD, or None.
    The PEEK_DATE_BY_BANK dict it consults is built at the bottom of
    this module so that the real KVB/SBI/IOB peek functions are bound
    by the time the lookup happens.
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


# ---------------------------------------------------------------------
# KVB / SBI / IOB cash-deposit parsers.
#
# Unlike Canara (which is a UPI-credit account), these three banks hold
# the company's CDM / BNA cash deposits. Cash deposits don't carry a UTR
# the way UPI does, so the contract `(UTR, Bank Amount, Particulars)` is
# preserved by SYNTHESIZING a UTR per row from the bank's reference
# data — date + machine ID + sequence number where available.
# ---------------------------------------------------------------------

def _strip_money(v):
    """Parse a monetary cell that may carry CR/DR suffix or embedded newlines
    (e.g. Indian Bank balance '105126.00CR' or '105126.00C\\nR'). Returns
    a float or None."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).replace("\n", "").replace(",", "").strip()
    s = re.sub(r"\s*(CR|DR)\s*$", "", s, flags=re.I)
    if not s or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_dmy(v):
    """Parse a DD/MM/YYYY date that may have an embedded newline
    ('01/04\\n/2026' as Indian Bank exports it). Returns YYYY-MM-DD or None."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).replace("\n", "").strip()
    if not s:
        return None
    try:
        return pd.to_datetime(s, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


# ===== KVB =============================================================
# Header: Txn Date | Value Date | Brn Code | Particulars | Ref. No | Debit | Credit | Balance
# Multi-page: header repeats every ~25 rows. Cash-deposit row pattern:
#   particulars = "CASH DEPOSIT AT CDM-S1ECDxxxxxx", credit > 0
# Charge row pattern:
#   particulars = "CDM CASH DEPOSIT CHARGES", debit = 59
KVB_CDM_RX = re.compile(r"CASH\s+DEPOSIT\s+AT\s+CDM[-\s]+(\S+)", re.I)


def _load_kvb_data(path):
    """Walk every header on every page of a KVB statement and return one
    DataFrame of all transaction rows (skips B/F, footers, blank pages)."""
    raw = _read_excel_any(path, header=None, dtype=str, keep_default_na=False)
    header_indices = []
    for i in range(len(raw)):
        cells = [str(c).strip().lower() for c in raw.iloc[i].values]
        if "txn date" in cells and "particulars" in cells and "credit" in cells:
            header_indices.append(i)
    if not header_indices:
        raise RuntimeError(
            "KVB statement: header row not found "
            "(expected 'Txn Date | Particulars | Credit' on the same row)"
        )

    rows = []
    for k, h in enumerate(header_indices):
        header_cells = [str(c).strip() for c in raw.iloc[h].values]
        col = {c.lower(): i for i, c in enumerate(header_cells) if c}
        next_h = header_indices[k + 1] if k + 1 < len(header_indices) else len(raw)
        for j in range(h + 1, next_h):
            row = raw.iloc[j].values
            d = normalize_date(row[col["txn date"]]) if "txn date" in col else None
            if not d:
                continue
            credit = _strip_money(row[col["credit"]]) if "credit" in col else None
            debit  = _strip_money(row[col["debit"]])  if "debit"  in col else None
            if credit is None and debit is None:
                continue  # B/F or other rows with only balance
            rows.append({
                "Date": d,
                "Brn Code":   str(row[col["brn code"]]).strip()    if "brn code"    in col else "",
                "Particulars": str(row[col["particulars"]]).strip() if "particulars" in col else "",
                "Ref No":     str(row[col.get("ref. no", -1)]).strip() if "ref. no" in col else "",
                "Debit": debit,
                "Credit": credit,
                "Balance": _strip_money(row[col["balance"]]) if "balance" in col else None,
            })
    return pd.DataFrame(rows)


def _read_kvb(path):
    df = _load_kvb_data(path)
    if df.empty:
        return pd.DataFrame(columns=["UTR", "Bank Amount", "Particulars"])
    mask = (
        df["Credit"].notna()
        & (df["Credit"] > 0)
        & df["Particulars"].str.contains(r"CASH\s+DEPOSIT", flags=re.I, regex=True, na=False)
    )
    df = df[mask].copy().reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(columns=["UTR", "Bank Amount", "Particulars"])

    def make_utr(r):
        m = KVB_CDM_RX.search(r["Particulars"])
        machine = m.group(1) if m else "UNKNOWN"
        return f"KVB-{r['Date']}-{r['Brn Code']}-{machine}-{r.name:03d}"

    df["UTR"] = df.apply(make_utr, axis=1)
    df["Bank Amount"] = df["Credit"]
    return df[["UTR", "Bank Amount", "Particulars"]].reset_index(drop=True)


def _read_kvb_charges(path):
    df = _load_kvb_data(path)
    if df.empty:
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])
    mask = df["Debit"].notna() & (df["Debit"] > 0) & df["Particulars"].str.contains(
        CHARGE_PATTERNS, na=False
    )
    df = df[mask].copy()
    if df.empty:
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])
    df["Bank Amount"] = df["Debit"]
    return df[["Date", "Bank Amount", "Particulars"]].reset_index(drop=True)


def _peek_kvb_date(path):
    df = _load_kvb_data(path)
    return df["Date"].iloc[0] if not df.empty else None


def _check_kvb_balance(path):
    """Best-effort: opening balance = first 'B/F' row balance,
    closing balance = last data-row balance, plus a credits/debits sum."""
    raw = _read_excel_any(path, header=None, dtype=str, keep_default_na=False)
    df = _load_kvb_data(path)
    warnings, stats = [], {
        "rows": int(len(df)),
        "credits_sum": float(df["Credit"].fillna(0).sum()) if not df.empty else 0.0,
        "debits_sum":  float(df["Debit"].fillna(0).sum())  if not df.empty else 0.0,
        "declared_credits": None, "declared_debits": None,
        "opening_balance": None, "closing_balance": None,
    }
    # Opening balance: scan raw rows for "B/F" and grab its balance column
    for i in range(len(raw)):
        for cell in raw.iloc[i].values:
            if "B/F" in str(cell).upper():
                # Last numeric cell on this row is the balance
                for c in reversed(raw.iloc[i].values):
                    v = _strip_money(c)
                    if v is not None:
                        stats["opening_balance"] = v
                        break
                break
        if stats["opening_balance"] is not None:
            break
    if not df.empty:
        stats["closing_balance"] = float(df["Balance"].dropna().iloc[-1]) if df["Balance"].notna().any() else None

    if stats["rows"] == 0:
        warnings.append("Statement contains no transaction rows.")
    return {"ok": not warnings, "warnings": warnings, "stats": stats}


# ===== SBI =============================================================
# Header: Txn Date | Value Date | Description | Ref No./Cheque No. | Branch Code | Debit | Credit | Balance
# Cash deposit pattern: "CSH DEP (CDM)-<machineId>\n<seq>-"
# Charges pattern: "CASH HANDLING CHARGES--<id>"
# Quirk: SBI's Excel export sometimes swaps month/day in the Txn Date
# (e.g. an April-1 transaction shows up as 2026-01-04). The fix: parse
# the "Account Statement from X to Y" line from the metadata block and
# pick whichever interpretation falls inside that period.
SBI_CSH_RX = re.compile(r"CSH\s+DEP\s*\(CDM\)\s*-\s*(\S+?)(?:\s+|\n)(\d+)?-?", re.I)


def _sbi_period(raw):
    for i in range(min(20, len(raw))):
        for cell in raw.iloc[i].values:
            s = str(cell)
            m = re.search(
                r"Account\s+Statement\s+from\s+(\d{1,2}\s+\w+\s+\d{4})\s+to\s+(\d{1,2}\s+\w+\s+\d{4})",
                s, re.I,
            )
            if m:
                try:
                    return (
                        pd.to_datetime(m.group(1)).strftime("%Y-%m-%d"),
                        pd.to_datetime(m.group(2)).strftime("%Y-%m-%d"),
                    )
                except Exception:
                    pass
    return None, None


def _sbi_resolve_date(v, period):
    """Pick the date interpretation (raw vs swapped month/day) that falls
    inside the SBI statement period; fall back to whichever parses."""
    direct = normalize_date(v)
    p_start, p_end = period
    if direct and p_start and p_end and p_start <= direct <= p_end:
        return direct
    try:
        dt = pd.to_datetime(v) if not isinstance(v, str) else pd.to_datetime(v)
        if 1 <= dt.day <= 12:
            sw = pd.Timestamp(year=dt.year, month=dt.day, day=dt.month).strftime("%Y-%m-%d")
            if p_start and p_end and p_start <= sw <= p_end:
                return sw
    except Exception:
        pass
    return direct


def _load_sbi_data(path):
    raw = _read_excel_any(path, header=None, dtype=str, keep_default_na=False)
    header_idx = None
    for i in range(min(40, len(raw))):
        cells = [str(c).strip().lower() for c in raw.iloc[i].values]
        if "txn date" in cells and "description" in cells and "credit" in cells:
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError(
            "SBI statement: header row not found "
            "(expected 'Txn Date | Description | Credit' on the same row)"
        )
    period = _sbi_period(raw)
    header_cells = [str(c).strip() for c in raw.iloc[header_idx].values]
    col = {c.lower(): i for i, c in enumerate(header_cells) if c}

    rows = []
    for j in range(header_idx + 1, len(raw)):
        row = raw.iloc[j].values
        d_raw = row[col["txn date"]] if "txn date" in col else None
        d = _sbi_resolve_date(d_raw, period)
        if not d:
            continue
        credit = _strip_money(row[col["credit"]]) if "credit" in col else None
        debit  = _strip_money(row[col["debit"]])  if "debit"  in col else None
        if credit is None and debit is None:
            continue
        rows.append({
            "Date": d,
            "Description": str(row[col["description"]]).replace("\n", " ").strip()
                if "description" in col else "",
            "Branch Code": str(row[col["branch code"]]).strip() if "branch code" in col else "",
            "Debit": debit, "Credit": credit,
            "Balance": _strip_money(row[col["balance"]]) if "balance" in col else None,
        })
    return pd.DataFrame(rows)


def _read_sbi(path):
    df = _load_sbi_data(path)
    if df.empty:
        return pd.DataFrame(columns=["UTR", "Bank Amount", "Particulars"])
    mask = (
        df["Credit"].notna()
        & (df["Credit"] > 0)
        & df["Description"].str.contains(r"CSH\s*DEP|CASH\s*DEP", flags=re.I, regex=True, na=False)
    )
    df = df[mask].copy().reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(columns=["UTR", "Bank Amount", "Particulars"])

    def make_utr(r):
        m = SBI_CSH_RX.search(r["Description"])
        if m:
            machine = m.group(1)
            seq = m.group(2) or ""
            return f"SBI-{r['Date']}-{machine}-{seq}-{r.name:03d}"
        return f"SBI-{r['Date']}-UNKNOWN-{r.name:03d}"

    df["UTR"] = df.apply(make_utr, axis=1)
    df["Bank Amount"] = df["Credit"]
    df["Particulars"] = df["Description"]
    return df[["UTR", "Bank Amount", "Particulars"]].reset_index(drop=True)


def _read_sbi_charges(path):
    df = _load_sbi_data(path)
    if df.empty:
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])
    mask = df["Debit"].notna() & (df["Debit"] > 0) & df["Description"].str.contains(
        CHARGE_PATTERNS, na=False
    )
    df = df[mask].copy()
    if df.empty:
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])
    df["Bank Amount"] = df["Debit"]
    df["Particulars"] = df["Description"]
    return df[["Date", "Bank Amount", "Particulars"]].reset_index(drop=True)


def _peek_sbi_date(path):
    df = _load_sbi_data(path)
    return df["Date"].iloc[0] if not df.empty else None


def _check_sbi_balance(path):
    df = _load_sbi_data(path)
    stats = {
        "rows": int(len(df)),
        "credits_sum": float(df["Credit"].fillna(0).sum()) if not df.empty else 0.0,
        "debits_sum":  float(df["Debit"].fillna(0).sum())  if not df.empty else 0.0,
        "declared_credits": None, "declared_debits": None,
        "opening_balance": None,
        "closing_balance": float(df["Balance"].dropna().iloc[-1])
            if (not df.empty and df["Balance"].notna().any()) else None,
    }
    warnings = [] if stats["rows"] else ["Statement contains no transaction rows."]
    return {"ok": not warnings, "warnings": warnings, "stats": stats}


# ===== Indian Bank (parser routed under the "IOB" code) =================
# NOTE: the file we built this against is from "INDIAN BANK" (IFSC IDIB...)
# which is a different bank from "Indian Overseas Bank" (IOB / IOBA...).
# The parser is wired into the IOB slot per the user's labelling. If a
# real IOB statement turns up later, this needs a separate parser.
#
# Header: Value Date | Post Date | Remitter Branch | Description | Cheque No | DR | CR | Balance
# Quirks:
#   - Date cells split across newlines: "01/04\n/2026"
#   - Balance cells carry CR/DR suffix, sometimes mid-newline: "105126.00C\nR"
#   - Some rows are continuation rows (TRAN DATE / TRAN TIME) that hold
#     no DR/CR — must be skipped.
# Cash deposit pattern: "ONUS BNA DEP BNA SEQ NO<N> ATM ID <id>"
# Charge pattern: "CHG FOR ATM ONUS DEP"
IB_BNA_RX = re.compile(r"BNA\s*SEQ\s*NO\s*(\d+)", re.I)
IB_ATM_RX = re.compile(r"ATM\s*ID\s*(\S+)", re.I)


def _load_ib_data(path):
    raw = _read_excel_any(path, header=None, dtype=str, keep_default_na=False)
    header_idx = None
    for i in range(min(40, len(raw))):
        cells = [str(c).strip().lower() for c in raw.iloc[i].values]
        if "value date" in cells and "description" in cells and "cr" in cells:
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError(
            "Indian Bank statement: header row not found "
            "(expected 'Value Date | Description | CR' on the same row)"
        )
    header_cells = [str(c).strip() for c in raw.iloc[header_idx].values]
    col = {c.lower(): i for i, c in enumerate(header_cells) if c}

    rows = []
    for j in range(header_idx + 1, len(raw)):
        row = raw.iloc[j].values
        d = _normalize_dmy(row[col["value date"]]) if "value date" in col else None
        if not d:
            continue
        cr = _strip_money(row[col["cr"]]) if "cr" in col else None
        dr = _strip_money(row[col["dr"]]) if "dr" in col else None
        if cr is None and dr is None:
            continue  # continuation rows (TRAN DATE / TRAN TIME) — skip
        rows.append({
            "Date": d,
            "Branch": str(row[col["remitter branch"]]).strip() if "remitter branch" in col else "",
            "Description": str(row[col["description"]]).replace("\n", " ").strip()
                if "description" in col else "",
            "DR": dr, "CR": cr,
            "Balance": _strip_money(row[col["balance"]]) if "balance" in col else None,
        })
    return pd.DataFrame(rows)


def _read_iob(path):
    df = _load_ib_data(path)
    if df.empty:
        return pd.DataFrame(columns=["UTR", "Bank Amount", "Particulars"])
    mask = (
        df["CR"].notna()
        & (df["CR"] > 0)
        & df["Description"].str.contains(r"BNA|CASH|DEP|CDM", flags=re.I, regex=True, na=False)
    )
    df = df[mask].copy().reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(columns=["UTR", "Bank Amount", "Particulars"])

    def make_utr(r):
        m_seq = IB_BNA_RX.search(r["Description"])
        m_atm = IB_ATM_RX.search(r["Description"])
        seq = m_seq.group(1) if m_seq else ""
        atm = m_atm.group(1) if m_atm else ""
        return f"IB-{r['Date']}-{atm}-{seq}-{r.name:03d}"

    df["UTR"] = df.apply(make_utr, axis=1)
    df["Bank Amount"] = df["CR"]
    df["Particulars"] = df["Description"]
    return df[["UTR", "Bank Amount", "Particulars"]].reset_index(drop=True)


def _read_iob_charges(path):
    df = _load_ib_data(path)
    if df.empty:
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])
    mask = df["DR"].notna() & (df["DR"] > 0) & df["Description"].str.contains(
        r"CHG|CHARGE|" + CHARGE_PATTERNS.pattern,
        flags=re.I, regex=True, na=False,
    )
    df = df[mask].copy()
    if df.empty:
        return pd.DataFrame(columns=["Date", "Bank Amount", "Particulars"])
    df["Bank Amount"] = df["DR"]
    df["Particulars"] = df["Description"]
    return df[["Date", "Bank Amount", "Particulars"]].reset_index(drop=True)


def _peek_iob_date(path):
    df = _load_ib_data(path)
    return df["Date"].iloc[0] if not df.empty else None


def _check_iob_balance(path):
    df = _load_ib_data(path)
    stats = {
        "rows": int(len(df)),
        "credits_sum": float(df["CR"].fillna(0).sum()) if not df.empty else 0.0,
        "debits_sum":  float(df["DR"].fillna(0).sum())  if not df.empty else 0.0,
        "declared_credits": None, "declared_debits": None,
        "opening_balance": None,
        "closing_balance": float(df["Balance"].dropna().iloc[-1])
            if (not df.empty and df["Balance"].notna().any()) else None,
    }
    # Opening balance: scan raw for "BALANCE B/F" row, take next numeric cell
    raw = _read_excel_any(path, header=None, dtype=str, keep_default_na=False)
    for i in range(len(raw)):
        joined = " ".join(str(c) for c in raw.iloc[i].values).upper()
        if "BALANCE B/F" in joined or "B/F" in joined:
            for c in raw.iloc[i].values:
                v = _strip_money(c)
                if v is not None and v != 0:
                    stats["opening_balance"] = v
                    break
            break
    warnings = [] if stats["rows"] else ["Statement contains no transaction rows."]
    return {"ok": not warnings, "warnings": warnings, "stats": stats}


# Axis still has no representative sample — keep the Canara fallback.
_read_axis        = _read_canara          # TODO: implement once an Axis sample is on hand
_read_axis_charges = _read_canara_charges # TODO: ditto
_peek_axis_date   = _peek_canara_date     # TODO: ditto
_check_axis_balance = _check_canara_balance  # TODO: ditto

READ_BANK_BY_CODE = {
    "CANARA": _read_canara,
    "SBI":    _read_sbi,
    "KVB":    _read_kvb,
    "IOB":    _read_iob,
    "AXIS":   _read_axis,
}

READ_CHARGES_BY_CODE = {
    "CANARA": _read_canara_charges,
    "SBI":    _read_sbi_charges,
    "KVB":    _read_kvb_charges,
    "IOB":    _read_iob_charges,
    "AXIS":   _read_axis_charges,
}

CHECK_BALANCE_BY_CODE = {
    "CANARA": _check_canara_balance,
    "SBI":    _check_sbi_balance,
    "KVB":    _check_kvb_balance,
    "IOB":    _check_iob_balance,
    "AXIS":   _check_axis_balance,
}

PEEK_DATE_BY_BANK = {
    "CANARA": _peek_canara_date,
    "SBI":    _peek_sbi_date,
    "KVB":    _peek_kvb_date,
    "IOB":    _peek_iob_date,
    "AXIS":   _peek_axis_date,
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


def read_bank_cash_deposits(path, bank_code):
    """Cash-pipeline reader: returns real cash-deposit rows from KVB / SBI /
    IOB statements, without the synthetic-UTR fit.

    Columns: Date · Bank Amount · Bank Code · Machine · Ref · Particulars

    Canara is a UPI account, so it returns an empty frame here.
    Axis has no real parser yet, so it returns empty.
    """
    code = (bank_code or "").upper()
    cols = ["Date", "Bank Amount", "Bank Code", "Machine", "Ref", "Particulars"]
    if code == "KVB":
        df = _load_kvb_data(path)
        if df.empty:
            return pd.DataFrame(columns=cols)
        mask = (
            df["Credit"].notna()
            & (df["Credit"] > 0)
            & df["Particulars"].str.contains(r"CASH\s+DEPOSIT", flags=re.I, regex=True, na=False)
        )
        df = df[mask].copy()
        df["Bank Amount"] = df["Credit"]
        df["Bank Code"] = "KVB"
        df["Machine"] = df["Particulars"].str.extract(KVB_CDM_RX.pattern, flags=re.I)[0].fillna("")
        df["Ref"] = df["Brn Code"]
        return df[cols].reset_index(drop=True)

    if code == "SBI":
        df = _load_sbi_data(path)
        if df.empty:
            return pd.DataFrame(columns=cols)
        mask = (
            df["Credit"].notna()
            & (df["Credit"] > 0)
            & df["Description"].str.contains(r"CSH\s*DEP|CASH\s*DEP", flags=re.I, regex=True, na=False)
        )
        df = df[mask].copy()
        df["Bank Amount"] = df["Credit"]
        df["Bank Code"] = "SBI"
        ext = df["Description"].str.extract(r"CSH\s+DEP\s*\(CDM\)\s*-\s*(\S+?)(?:\s+|$)\s*(\d+)?", flags=re.I)
        df["Machine"] = ext[0].fillna("")
        df["Ref"] = ext[1].fillna("")
        df["Particulars"] = df["Description"]
        return df[cols].reset_index(drop=True)

    if code == "IOB":
        df = _load_ib_data(path)
        if df.empty:
            return pd.DataFrame(columns=cols)
        mask = (
            df["CR"].notna()
            & (df["CR"] > 0)
            & df["Description"].str.contains(r"BNA|CASH|DEP|CDM", flags=re.I, regex=True, na=False)
        )
        df = df[mask].copy()
        df["Bank Amount"] = df["CR"]
        df["Bank Code"] = "IOB"
        df["Machine"] = df["Description"].str.extract(IB_ATM_RX.pattern, flags=re.I)[0].fillna("")
        df["Ref"] = df["Description"].str.extract(IB_BNA_RX.pattern, flags=re.I)[0].fillna("")
        df["Particulars"] = df["Description"]
        return df[cols].reset_index(drop=True)

    return pd.DataFrame(columns=cols)


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
