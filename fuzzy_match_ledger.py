"""
Fuzzy reconciliation of the 9-Apr-2026 handwritten cash deposit ledger.

Three checks:
  1. Decode + validate every policy number (branch / type lookup).
  2. Fuzzy-match names within the ledger to surface likely duplicates
     (same person, two rows; or near-spelling variants).
  3. Match the bank-column rows (entries 18-31 in the ledger) against
     KVB statement credits on 09-Apr-2026 by amount, with a small
     tolerance, and report MATCHED / MISSING / UNRECORDED.
"""

import os
import re
import sys
from difflib import SequenceMatcher

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "janaasha-bank"))
from reconcile import (
    BRANCH_CODE_MAP,
    POLICY_TYPE_MAP,
    decode_policy_number,
    parse_amount,
)

LEDGER_DATE = "2026-04-09"

# Transcribed from the handwritten ledger image. (sl, name, policy, business,
# m_id_amt, cash, bank). N flag = note in image (likely "new").
LEDGER = [
    (1,  "KALAIVANI",         "044600186", 100,   None, 100,  None),
    (2,  "MARIMUTHU",         "044300173", 1000,  None, 1000, None),
    (3,  "MAGESH BABU",       "044300094", 1000,  None, 1000, None),
    (4,  "R. SIVARAJ",        "044600005", 4400,  None, 4400, None),
    (5,  "NITHYA",            "044600276", 200,   None, 200,  None),
    (6,  "DEVARAJ NANDHI",    "044600269", 200,   None, 200,  None),
    (7,  "VASANTHI",          "044600287", 500,   None, 500,  None),
    (8,  "SAGANA",            "044600271", 500,   None, 500,  None),
    (9,  "ROHAN",             "044600218", 500,   None, 500,  None),
    (10, "SURESH KUMAR",      "044600279", 100,   None, 100,  None),
    (11, "RENUGA",            "044600197", 100,   None, 100,  None),
    (12, "YOGESH GOWTHAM",    "044600115", 500,   None, 500,  None),
    (13, "VIMALA",            "044600087", 500,   None, 500,  None),
    (14, "AMIZI ROSY",        "044600089", 200,   None, 200,  None),
    (15, "SANTHA",            "044600226", 600,   None, 600,  None),
    (16, "SEKARAN.N",         "044600229", 1000,  None, 1000, None),
    (17, "B. JOGHEE",         "044300003", 1000,  None, 1000, None),
    (18, "BANUPRIYA",         "044600215", 1000,  None, None, 1000),
    (19, "HARIKRISHNAN",      "044600216", 1000,  None, None, 1000),
    (20, "SARAVANAN",         "044600260", 5100,  None, None, 5100),
    (21, "ARUN KUMAR",        "044600254", 1000,  None, None, 1000),
    (22, "VINOTH KUMAR",      "044600249", 200,   None, None, 200),
    (23, "MUTHU SAMY",        "044600067", 2000,  None, None, 2000),
    (24, "KALAIVANI",         "044600289", 100,   None, None, 100),
    (25, "JOGHEE",            "044600004", 500,   None, None, 500),
    (26, "MURUGANANDHAM",     "044600232", 500,   None, None, 500),
    (27, "RANI",              "044300090", 2000,  None, None, 2000),
    (28, "PRANESH",           "044600278", 1200,  None, None, 1200),
    (29, "VISWANATHAN",       "044600228", 200,   None, None, 200),
    (30, "NAVEEN KUMAR",      "044600246", 500,   None, None, 500),
    (31, "HALAN SIVASANKAR",  "044600205", 100,   None, None, 100),
    (32, "AJAI",              "044600295", 200,   None, 200,  None),  # N
    (33, "VIVEK",             "044600244", 200,   None, 200,  None),  # N
    (34, "NITHYA",             "044300085", 1000,  None, 1000, None),
    (35, "SANTHI",            "044600282", 2100,  None, 2100, None),
    (36, "NARAYANAN",         "044600043", 11400, None, 11400,None),
    (37, "INDHU RANI",        "044600296", 100,   100,  200,  None),  # N
    (38, "INDHU RANI",        "044600297", 100,   None, 100,  None),  # N
    (39, "RAJI",              "044600128", 100,   None, 100,  None),
    (40, "ANITHA",            "044600187", 300,   None, 300,  None),
    (41, "SASIKALA",          "044600111", 500,   None, 500,  None),
    (42, "VASANTHI",          "044600203", 400,   None, 400,  None),
    (43, "VASANTHI",          "044600265", 200,   None, 200,  None),
]


def norm_name(s: str) -> str:
    s = s.upper()
    s = re.sub(r"[^A-Z]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_name(a), norm_name(b)).ratio()


# --- 1. Validate policy numbers ----------------------------------------
def check_policies():
    print("=" * 72)
    print("POLICY NUMBER VALIDATION (decoded via reconcile.decode_policy_number)")
    print("=" * 72)
    bad = []
    type_counts = {}
    branch_counts = {}
    for sl, name, pol, *_ in LEDGER:
        bcode, tdig, ptype, bname = decode_policy_number(pol)
        if bcode is None:
            bad.append((sl, name, pol, "INVALID FORMAT"))
            continue
        if ptype is None:
            bad.append((sl, name, pol, f"unknown type digit '{tdig}'"))
        if bname is None:
            bad.append((sl, name, pol, f"unknown branch code '{bcode}'"))
        type_counts[ptype] = type_counts.get(ptype, 0) + 1
        branch_counts[bname] = branch_counts.get(bname, 0) + 1

    print(f"Branch distribution: {branch_counts}")
    print(f"Policy type distribution: {type_counts}")
    if bad:
        print("\nIssues:")
        for sl, name, pol, reason in bad:
            print(f"  Row {sl:2}  {name:20}  {pol}  -> {reason}")
    else:
        print("\nAll 43 policy numbers decode cleanly.")


# --- 2. Fuzzy duplicate names in the ledger ---------------------------
def fuzzy_duplicates(threshold: float = 0.85):
    print("\n" + "=" * 72)
    print(f"FUZZY DUPLICATE NAMES IN LEDGER (similarity >= {threshold})")
    print("=" * 72)
    rows = LEDGER
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            sim = name_similarity(rows[i][1], rows[j][1])
            if sim >= threshold:
                pairs.append((sim, rows[i], rows[j]))
    pairs.sort(key=lambda p: -p[0])
    if not pairs:
        print("No fuzzy-duplicate names found.")
        return
    print(f"{'sim':>5}  {'row1':>4}  {'name1':22} {'pol1':12}  "
          f"{'row2':>4}  {'name2':22} {'pol2':12}")
    for sim, a, b in pairs:
        same_pol = "SAME POLICY" if a[2] == b[2] else ""
        print(f"{sim:5.2f}  {a[0]:>4}  {a[1]:22} {a[2]:12}  "
              f"{b[0]:>4}  {b[1]:22} {b[2]:12}  {same_pol}")


# --- 3. Match bank-column rows to KVB credits on 09-Apr-2026 -----------
KVB_PATH = os.path.join(
    os.path.dirname(__file__),
    "1721013000000052 _ 01-APR-2026_14-APR-2026 kvb (1).xlsx",
)


def load_kvb_credits(date_iso: str | None = None) -> pd.DataFrame:
    """All KVB credit rows; optionally filtered to a single ISO date."""
    raw = pd.read_excel(KVB_PATH, sheet_name="Table 1", header=None)
    header_idx = None
    for i in range(min(len(raw), 30)):
        cells = [str(c).strip() for c in raw.iloc[i].values]
        low = [c.lower() for c in cells]
        if "txn date" in low and "credit" in low:
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("Could not locate KVB header row")
    df = pd.read_excel(KVB_PATH, sheet_name="Table 1", header=header_idx)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["Txn Date"].notna()].copy()
    df["Txn Date"] = pd.to_datetime(df["Txn Date"], errors="coerce")
    df["Credit"] = df["Credit"].apply(parse_amount)
    df = df[df["Credit"].notna() & (df["Credit"] > 0)]
    if date_iso:
        df = df[df["Txn Date"].dt.strftime("%Y-%m-%d") == date_iso]
    return df[["Txn Date", "Particulars", "Credit"]].reset_index(drop=True)


load_kvb_credits_on = load_kvb_credits


def match_bank_column(tolerance: float = 0.01):
    print("\n" + "=" * 72)
    print(f"BANK-COLUMN LEDGER ROWS (18-31)  vs  KVB CREDITS on {LEDGER_DATE}")
    print("=" * 72)
    bank_rows = [r for r in LEDGER if r[6] is not None]
    kvb = load_kvb_credits_on(LEDGER_DATE)
    print(f"\nLedger bank-column rows: {len(bank_rows)} "
          f"(total {sum(r[6] for r in bank_rows):,.0f})")
    print(f"KVB credits on {LEDGER_DATE}: {len(kvb)} "
          f"(total {kvb['Credit'].sum():,.0f})")

    # Greedy amount matching (one bank row per ledger row).
    used = set()
    matched, missing = [], []
    for sl, name, pol, biz, mid, cash, bank in bank_rows:
        amt = bank
        hit = None
        for idx, row in kvb.iterrows():
            if idx in used:
                continue
            if abs(row["Credit"] - amt) <= tolerance:
                hit = (idx, row)
                break
        if hit:
            idx, row = hit
            used.add(idx)
            matched.append((sl, name, pol, amt, row["Credit"], row["Particulars"]))
        else:
            missing.append((sl, name, pol, amt))

    unrecorded = [
        (idx, row["Credit"], str(row["Particulars"]).replace("\n", " ")[:60])
        for idx, row in kvb.iterrows() if idx not in used
    ]

    print(f"\nMATCHED ({len(matched)}):")
    for sl, name, pol, exp, got, part in matched:
        print(f"  Row {sl:>2}  {name:20} {pol}  ledger={exp:>6.0f} "
              f"kvb={got:>6.0f}  ::  {str(part).replace(chr(10),' ')[:48]}")

    print(f"\nMISSING from KVB ({len(missing)}):")
    for sl, name, pol, exp in missing:
        print(f"  Row {sl:>2}  {name:20} {pol}  ledger={exp:>6.0f}")

    print(f"\nUNRECORDED in ledger (KVB credits with no ledger match) ({len(unrecorded)}):")
    for idx, amt, part in unrecorded:
        print(f"  KVB idx={idx:>3}  credit={amt:>8.0f}  ::  {part}")


def expanded_amount_search():
    """Bank-column amounts compared to ALL KVB credits (any date in window),
    so we can see whether the cash hit the bank a day or two late."""
    print("\n" + "=" * 72)
    print("EXPANDED SEARCH: bank-column amounts vs ALL KVB credits 01-14 Apr")
    print("=" * 72)
    kvb = load_kvb_credits()
    print(f"Total KVB credit rows in window: {len(kvb)} "
          f"(sum {kvb['Credit'].sum():,.0f})")
    bank_rows = [r for r in LEDGER if r[6] is not None]
    for sl, name, pol, biz, mid, cash, bank in bank_rows:
        hits = kvb[kvb["Credit"] == bank]
        if hits.empty:
            print(f"  Row {sl:>2} {name:18} {pol}  {bank:>6.0f}  -> no exact KVB credit")
        else:
            dates = ", ".join(hits["Txn Date"].dt.strftime("%d-%b").unique())
            print(f"  Row {sl:>2} {name:18} {pol}  {bank:>6.0f}  -> "
                  f"{len(hits)} KVB hit(s) on {dates}")


if __name__ == "__main__":
    check_policies()
    fuzzy_duplicates(0.85)
    match_bank_column()
    expanded_amount_search()
