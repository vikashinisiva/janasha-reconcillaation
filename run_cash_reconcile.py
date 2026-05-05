"""
Demo of the new cash pipeline:

  Ledger CSV  +  KVB / SBI / IOB statements
       │              │
       └──────┬───────┘
              ▼
        cash_reconcile.reconcile_cash()
              │
              ▼
   matched / missing / unrecorded / cash-in-hand / daily-totals
"""

import os
import sys

ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(ROOT, "janaasha-bank"))

from cash_reconcile import (
    read_ledger_csv,
    collect_bank_cash_deposits,
    reconcile_cash,
    print_report,
)

LEDGER_CSV = os.path.join(ROOT, "ledger_2026-04-09.csv")
BANK_PATHS = {
    "KVB": os.path.join(ROOT, "1721013000000052 _ 01-APR-2026_14-APR-2026 kvb (1).xlsx"),
    "SBI": os.path.join(ROOT, "1775103090904sqkLDtWjVuE0CARX (1) (1).xlsx"),
    "IOB": os.path.join(ROOT, "Indian bank (1).xlsx"),
}


def main():
    ledger = read_ledger_csv(LEDGER_CSV)
    print(f"Loaded ledger: {len(ledger)} rows from {LEDGER_CSV}")
    print(f"  cash-column rows:  {ledger['cash'].notna().sum()}  "
          f"(total {ledger['cash'].sum():,.0f})")
    print(f"  bank-column rows:  {ledger['bank'].notna().sum()}  "
          f"(total {ledger['bank'].sum():,.0f})")

    bank = collect_bank_cash_deposits(BANK_PATHS)
    print(f"\nLoaded bank cash deposits: {len(bank)} rows")
    if not bank.empty:
        for code, n in bank["Bank Code"].value_counts().items():
            tot = bank.loc[bank["Bank Code"] == code, "Bank Amount"].sum()
            print(f"  {code}: {n} rows, total {tot:,.0f}")

    # Cash on a branch ledger usually hits the bank same day or +1.
    result = reconcile_cash(ledger, bank, date_window_days=1)
    print()
    print_report(result)


if __name__ == "__main__":
    main()
