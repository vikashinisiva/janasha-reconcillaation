"""
Cash-pipeline reconciliation: handwritten ledger ↔ KVB / SBI / IOB cash deposits.

This is the parallel pipeline to the UTR-based UPI reconciler in reconcile.py.
Cash deposits don't carry UTRs, so matching is by amount + date instead.

Inputs:
  - Ledger DataFrame  (date, sl, name, policy_no, business, cash, bank, ...)
  - Bank cash-deposit DataFrame  (date, bank_amount, bank_code, machine, ref, ...)
    -- typically the concat of read_bank_cash_deposits() output for each of
       KVB/SBI/IOB on the relevant dates.

Outputs (dict):
  matched               – ledger rows paired with a bank row (same amount + date)
  missing_from_bank     – ledger rows claiming a deposit, no bank row found
  unrecorded_in_ledger  – bank deposits with no ledger entry to back them
  cash_in_hand          – ledger cash-column rows (cash kept at the branch,
                           not expected to appear in any bank statement)
  daily_summary         – per-date totals: ledger bank-side vs bank-side,
                           and a delta. Useful when the bank aggregates the
                           day's cash into a different breakdown of amounts.
"""

import os
from typing import Iterable

import pandas as pd

from reconcile import read_bank_cash_deposits


# --- Ledger I/O --------------------------------------------------------

LEDGER_COLS = [
    "date", "sl", "name", "policy_no",
    "business", "m_id_amt", "cash", "bank", "note",
]


def read_ledger_csv(path: str) -> pd.DataFrame:
    """Read a digitized handwritten ledger CSV.

    Expected columns: date, sl, name, policy_no, business, m_id_amt, cash, bank, note
    Date should be ISO (YYYY-MM-DD); cash and bank are mutually exclusive
    per row (an entry was either kept as cash or deposited at a bank).
    """
    df = pd.read_csv(path, dtype={"policy_no": str})
    missing = set(LEDGER_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"Ledger CSV missing columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for c in ("business", "m_id_amt", "cash", "bank"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["name"] = df["name"].astype(str).str.strip()
    df["policy_no"] = df["policy_no"].astype(str).str.strip()
    return df


# --- Bank-side aggregator ---------------------------------------------

def collect_bank_cash_deposits(paths_by_code: dict) -> pd.DataFrame:
    """Read every cash-deposit bank statement and return one combined frame.

    paths_by_code: {"KVB": "<path>", "SBI": "<path>", "IOB": "<path>"}.
    Missing entries are skipped, missing files are skipped (with a warning
    so the caller knows we ran with partial data).
    """
    frames = []
    for code, path in paths_by_code.items():
        if not path:
            continue
        if not os.path.exists(path):
            print(f"WARN: {code} statement not found at {path}; skipping")
            continue
        df = read_bank_cash_deposits(path, code)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(
            columns=["Date", "Bank Amount", "Bank Code", "Machine", "Ref", "Particulars"]
        )
    return pd.concat(frames, ignore_index=True)


# --- Matcher -----------------------------------------------------------

def reconcile_cash(
    ledger: pd.DataFrame,
    bank_deposits: pd.DataFrame,
    *,
    date_window_days: int = 0,
    amount_tolerance: float = 0.01,
):
    """Pair ledger bank-column rows with bank cash-deposit rows by amount + date.

    date_window_days = 0 → exact-date match only.
    date_window_days = N → also try N days after the ledger date (deposits
                            often happen the same day; sometimes a day late).

    Greedy strategy: for each ledger row (in original order), claim the first
    unused bank row whose amount matches and whose date is within the window.
    Ties / aggregated deposits surface in daily_summary, not as missing rows.
    """
    # Cash-in-hand: ledger rows with a cash entry but no bank entry.
    # These shouldn't appear in any bank statement — surface them informationally.
    cash_in_hand = ledger[ledger["cash"].notna() & ledger["bank"].isna()].copy()

    # Bank-deposit rows from the ledger: these are the ones we expect to
    # find on the bank side.
    ledger_bank = ledger[ledger["bank"].notna()].copy().reset_index(drop=True)

    # Coerce bank-side date for comparison.
    bd = bank_deposits.copy()
    if not bd.empty:
        bd["Date"] = pd.to_datetime(bd["Date"]).dt.strftime("%Y-%m-%d")

    used_bank_idx = set()
    matched_rows = []
    missing_rows = []

    for _, lrow in ledger_bank.iterrows():
        ldate = lrow["date"]
        lamt = float(lrow["bank"])
        # Build allowed date range
        ldt = pd.to_datetime(ldate)
        allowed_dates = {
            (ldt + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(0, date_window_days + 1)
        }
        hit_idx = None
        for bidx, brow in bd.iterrows():
            if bidx in used_bank_idx:
                continue
            if brow["Date"] not in allowed_dates:
                continue
            if abs(float(brow["Bank Amount"]) - lamt) <= amount_tolerance:
                hit_idx = bidx
                break
        if hit_idx is not None:
            used_bank_idx.add(hit_idx)
            brow = bd.loc[hit_idx]
            matched_rows.append({
                "Ledger Date": ldate,
                "Sl": int(lrow["sl"]),
                "Name": lrow["name"],
                "Policy No": lrow["policy_no"],
                "Ledger Amount": lamt,
                "Bank Date": brow["Date"],
                "Bank Code": brow["Bank Code"],
                "Bank Amount": float(brow["Bank Amount"]),
                "Machine": brow["Machine"],
                "Ref": brow["Ref"],
                "Status": "MATCHED",
            })
        else:
            missing_rows.append({
                "Ledger Date": ldate,
                "Sl": int(lrow["sl"]),
                "Name": lrow["name"],
                "Policy No": lrow["policy_no"],
                "Ledger Amount": lamt,
                "Bank Date": None,
                "Bank Code": None,
                "Bank Amount": None,
                "Machine": None,
                "Ref": None,
                "Status": "MISSING FROM BANK",
            })

    # Bank rows that no ledger row claimed.
    unrecorded_rows = []
    for bidx, brow in bd.iterrows():
        if bidx in used_bank_idx:
            continue
        unrecorded_rows.append({
            "Ledger Date": None,
            "Sl": None,
            "Name": None,
            "Policy No": None,
            "Ledger Amount": None,
            "Bank Date": brow["Date"],
            "Bank Code": brow["Bank Code"],
            "Bank Amount": float(brow["Bank Amount"]),
            "Machine": brow["Machine"],
            "Ref": brow["Ref"],
            "Status": "UNRECORDED IN LEDGER",
        })

    # Daily totals — useful when the bank aggregates the day's cash into
    # different individual amounts but the day-total still matches.
    daily = []
    all_dates = sorted(set(ledger_bank["date"].tolist())
                       | (set(bd["Date"].tolist()) if not bd.empty else set()))
    for d in all_dates:
        l_total = ledger_bank.loc[ledger_bank["date"] == d, "bank"].sum() \
            if not ledger_bank.empty else 0.0
        b_total = bd.loc[bd["Date"] == d, "Bank Amount"].sum() \
            if not bd.empty else 0.0
        daily.append({
            "date": d,
            "ledger_bank_total": float(l_total),
            "bank_deposit_total": float(b_total),
            "delta": float(b_total - l_total),
        })

    return {
        "matched": pd.DataFrame(matched_rows),
        "missing_from_bank": pd.DataFrame(missing_rows),
        "unrecorded_in_ledger": pd.DataFrame(unrecorded_rows),
        "cash_in_hand": cash_in_hand,
        "daily_summary": pd.DataFrame(daily),
    }


# --- Pretty-print helper for CLI use -----------------------------------

def print_report(result: dict) -> None:
    print("=" * 78)
    print("DAILY TOTALS")
    print("=" * 78)
    print(result["daily_summary"].to_string(index=False) if not result["daily_summary"].empty else "  (no dates)")
    for tab in ("matched", "missing_from_bank", "unrecorded_in_ledger"):
        df = result[tab]
        print()
        print("=" * 78)
        print(f"{tab.upper().replace('_', ' ')}  ({len(df)} rows)")
        print("=" * 78)
        if df.empty:
            print("  (none)")
            continue
        cols = [c for c in (
            "Ledger Date", "Sl", "Name", "Policy No", "Ledger Amount",
            "Bank Date", "Bank Code", "Bank Amount", "Machine", "Ref",
        ) if c in df.columns]
        print(df[cols].to_string(index=False))
    print()
    print("=" * 78)
    print(f"CASH IN HAND (kept at branch)  ({len(result['cash_in_hand'])} rows)")
    print("=" * 78)
    cih = result["cash_in_hand"]
    if cih.empty:
        print("  (none)")
    else:
        total = cih["cash"].sum()
        print(f"  Total cash kept at branch: {total:,.2f}")
        print(cih[["date", "sl", "name", "policy_no", "cash"]].to_string(index=False))
