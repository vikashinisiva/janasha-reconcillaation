"""
Reverse-direction check: for each bank statement (KVB / SBI / Indian Bank),
extract cash-deposit credits on 09-Apr-2026 and report whether each amount
appears in the handwritten ledger.

Bank statements don't carry depositor names for CDM/BNA cash deposits, so
matching is amount-based.
"""

import os
import re
import pandas as pd

from fuzzy_match_ledger import LEDGER, LEDGER_DATE

ROOT = os.path.dirname(__file__)
KVB  = os.path.join(ROOT, "1721013000000052 _ 01-APR-2026_14-APR-2026 kvb (1).xlsx")
SBI  = os.path.join(ROOT, "1775103090904sqkLDtWjVuE0CARX (1) (1).xlsx")
IB   = os.path.join(ROOT, "Indian bank.xlsx")


def parse_amt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).replace(",", "").strip()
    s = re.sub(r"(CR|DR)$", "", s, flags=re.I).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_header(raw, must_have):
    must_have = [m.lower() for m in must_have]
    for i in range(min(len(raw), 40)):
        low = [str(c).strip().lower() for c in raw.iloc[i].values]
        if all(any(m == c or m in c for c in low) for m in must_have):
            return i
    return None


def kvb_deposits(date_iso):
    raw = pd.read_excel(KVB, sheet_name="Table 1", header=None)
    h = find_header(raw, ["txn date", "credit", "particulars"])
    df = pd.read_excel(KVB, sheet_name="Table 1", header=h)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["Txn Date"].notna()].copy()
    df["Txn Date"] = pd.to_datetime(df["Txn Date"], errors="coerce")
    df["Credit"] = df["Credit"].apply(parse_amt)
    df = df[df["Credit"].notna() & (df["Credit"] > 0)]
    df = df[df["Particulars"].astype(str).str.upper().str.contains("CASH DEP")]
    df = df[df["Txn Date"].dt.strftime("%Y-%m-%d") == date_iso]
    return [(r["Credit"], str(r["Particulars"]).replace("\n", " "))
            for _, r in df.iterrows()]


def sbi_deposits(date_iso):
    raw = pd.read_excel(SBI, sheet_name="Table 1", header=None)
    h = find_header(raw, ["txn date", "credit", "description"])
    df = pd.read_excel(SBI, sheet_name="Table 1", header=h)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["Txn Date"].notna()].copy()
    df["Txn Date"] = pd.to_datetime(df["Txn Date"], errors="coerce")
    df["Credit"] = df["Credit"].apply(parse_amt)
    df = df[df["Credit"].notna() & (df["Credit"] > 0)]
    df = df[df["Description"].astype(str).str.upper().str.contains(
        "CSH DEP|CASH DEP|CDM", regex=True)]
    df = df[df["Txn Date"].dt.strftime("%Y-%m-%d") == date_iso]
    return [(r["Credit"], str(r["Description"]).replace("\n", " "))
            for _, r in df.iterrows()]


def ib_deposits(date_iso):
    """Indian Bank statement uses 'Value Date' (DD/MM/YYYY) and 'CR' column."""
    raw = pd.read_excel(IB, sheet_name="Table 1", header=None)
    h = find_header(raw, ["value date", "cr", "description"])
    df = pd.read_excel(IB, sheet_name="Table 1", header=h)
    df.columns = [str(c).strip() for c in df.columns]
    if "Value Date" not in df.columns:
        return []
    df = df[df["Value Date"].notna()].copy()
    # Value Date stored as "DD/MM\n/YYYY" string in this file
    df["__d"] = pd.to_datetime(
        df["Value Date"].astype(str).str.replace("\n", "", regex=False),
        dayfirst=True, errors="coerce",
    )
    df = df[df["__d"].notna()]
    df["CR"] = df["CR"].apply(parse_amt)
    df = df[df["CR"].notna() & (df["CR"] > 0)]
    df = df[df["Description"].astype(str).str.upper().str.contains(
        "BNA|CASH|CDM|DEP", regex=True)]
    df = df[df["__d"].dt.strftime("%Y-%m-%d") == date_iso]
    return [(r["CR"], str(r["Description"]).replace("\n", " "))
            for _, r in df.iterrows()]


def report(bank_name, deposits):
    print("=" * 72)
    print(f"{bank_name}: cash deposits on {LEDGER_DATE}")
    print("=" * 72)
    if not deposits:
        print(f"  No cash-deposit credits in this statement on {LEDGER_DATE}.")
        return
    bank_amounts = [b for *_, b in [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in LEDGER]]
    # Build a multiset of ledger amounts (cash + bank columns) so we can mark
    # whether the bank-side amount appears at all on this date in the ledger.
    ledger_amts = []
    for sl, name, pol, biz, mid, cash, bank in LEDGER:
        for v in (cash, bank):
            if v is not None:
                ledger_amts.append((sl, name, pol, v, "cash" if v == cash else "bank"))

    total = 0.0
    for amt, particulars in deposits:
        total += amt
        hits = [r for r in ledger_amts if abs(r[3] - amt) < 0.01]
        if hits:
            tag = ", ".join(f"row {r[0]} {r[1]}({r[4]})" for r in hits)
            print(f"  {amt:>9.0f}  IN LEDGER -> {tag}")
        else:
            print(f"  {amt:>9.0f}  NOT IN LEDGER  ::  {particulars[:55]}")
    print(f"  ---")
    print(f"  Total bank cash deposits on {LEDGER_DATE}: {total:,.0f}")


if __name__ == "__main__":
    ledger_total = sum((r[5] or 0) + (r[6] or 0) for r in LEDGER)
    print(f"Ledger total (cash + bank columns) on {LEDGER_DATE}: "
          f"{ledger_total:,.0f}\n")

    report("KVB",         kvb_deposits(LEDGER_DATE))
    print()
    report("SBI",         sbi_deposits(LEDGER_DATE))
    print()
    report("INDIAN BANK", ib_deposits(LEDGER_DATE))
