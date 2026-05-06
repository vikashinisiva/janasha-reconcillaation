import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtAmount } from "../helpers.js";

/**
 * Cross-pipeline summary banner. Sits above the UPI / Cash toggle so the
 * accountant always sees one combined picture regardless of which
 * pipeline they're currently looking at.
 *
 * Auto-refreshes whenever `refreshKey` bumps (parent bumps it after a
 * reconcile run or a resolve action).
 */
export default function CombinedSummary({
  refreshKey = 0,
  onSwitchPipeline,   // (which: "upi" | "cash") → void
  onOpenCrossCheck,   // () → void
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchIt = useCallback(async () => {
    try {
      const d = await api.getCombinedSummary();
      setData(d);
    } catch (_e) {
      /* swallow — non-critical surface */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getCombinedSummary()
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (loading && !data) {
    return (
      <div style={{ padding: "10px 18px", color: "#888", fontSize: 12 }}>
        Loading combined summary…
      </div>
    );
  }
  if (!data) return null;

  const { upi, cash, combined, duplicates } = data;
  const hasIssues = combined.issues > 0 || duplicates.total > 0;

  return (
    <div style={{
      margin: "8px 18px 0",
      background: "#fff",
      border: hasIssues ? "1px solid #c99" : "1px solid #d0d0d0",
      borderLeft: hasIssues ? "4px solid #b6342a" : "4px solid #1b5b1b",
      borderRadius: 6,
      padding: "10px 14px",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 8,
      }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#444",
                      letterSpacing: "0.04em" }}>
          ALL RECONCILIATION ACTIVITY
        </div>
        <div style={{ fontSize: 11, color: "#888" }}>
          {hasIssues
            ? `${combined.issues} flagged${duplicates.total ? ` · ${duplicates.total} cross-pipeline dup${duplicates.total === 1 ? "" : "s"}` : ""}`
            : "all clear"}
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr auto",
        gap: 12,
      }}>
        {/* UPI column */}
        <div
          onClick={() => onSwitchPipeline?.("upi")}
          style={{
            background: "#fafafa",
            border: "1px solid #e6e6e6",
            borderRadius: 4,
            padding: "8px 10px",
            cursor: "pointer",
          }}
        >
          <div style={{ fontSize: 10, fontWeight: 700, color: "#888",
                        letterSpacing: "0.06em" }}>
            UPI · BRANCH EXCEL ↔ CANARA
          </div>
          <div style={{ display: "flex", gap: 14, marginTop: 4, fontSize: 13 }}>
            <span><strong>{upi.matched}</strong> matched</span>
            <span style={{ color: upi.issues ? "#9a1f1f" : "#888" }}>
              <strong>{upi.issues}</strong> issues
            </span>
            {upi.pending > 0 && (
              <span style={{ color: "#8b5a14" }}>
                <strong>{upi.pending}</strong> pending
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
            ₹{fmtAmount(upi.amount || 0)}
          </div>
        </div>

        {/* Cash column */}
        <div
          onClick={() => onSwitchPipeline?.("cash")}
          style={{
            background: "#fafafa",
            border: "1px solid #e6e6e6",
            borderRadius: 4,
            padding: "8px 10px",
            cursor: "pointer",
          }}
        >
          <div style={{ fontSize: 10, fontWeight: 700, color: "#888",
                        letterSpacing: "0.06em" }}>
            CASH · LEDGER ↔ KVB / SBI / IOB / AXIS
          </div>
          <div style={{ display: "flex", gap: 14, marginTop: 4, fontSize: 13 }}>
            <span><strong>{cash.matched}</strong> matched</span>
            <span style={{ color: cash.issues ? "#9a1f1f" : "#888" }}>
              <strong>{cash.issues}</strong> issues
            </span>
            {cash.in_hand > 0 && (
              <span style={{ color: "#3a3a8c" }}>
                <strong>{cash.in_hand}</strong> in hand
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
            ₹{fmtAmount(cash.amount || 0)}
          </div>
        </div>

        {/* Combined column */}
        <div style={{
          background: hasIssues ? "#fbeeed" : "#e8f5e8",
          border: "1px solid " + (hasIssues ? "#e6c2c0" : "#c2dec2"),
          borderRadius: 4,
          padding: "8px 10px",
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#444",
                        letterSpacing: "0.06em" }}>
            COMBINED
          </div>
          <div style={{ display: "flex", gap: 14, marginTop: 4, fontSize: 13 }}>
            <span style={{ color: "#1b5b1b" }}>
              <strong>{combined.matched}</strong> matched
            </span>
            <span style={{ color: combined.issues ? "#9a1f1f" : "#888" }}>
              <strong>{combined.issues}</strong> issues
            </span>
          </div>
          <div style={{ fontSize: 11, color: "#444", marginTop: 2,
                        fontWeight: 600 }}>
            ₹{fmtAmount(combined.total_amount || 0)}
          </div>
        </div>

        {/* Cross-check column */}
        <div
          onClick={onOpenCrossCheck}
          style={{
            display: "flex", flexDirection: "column",
            justifyContent: "center", alignItems: "center",
            background: duplicates.total ? "#fbdcdc" : "#fafafa",
            border: "1px solid " + (duplicates.total ? "#e6a8a8" : "#e6e6e6"),
            borderRadius: 4,
            padding: "8px 14px",
            cursor: "pointer",
            minWidth: 130,
          }}
        >
          <div style={{ fontSize: 10, fontWeight: 700,
                        color: duplicates.total ? "#9a1f1f" : "#888",
                        letterSpacing: "0.06em" }}>
            CROSS-PIPELINE
          </div>
          <div style={{ fontSize: 18, fontWeight: 700,
                        color: duplicates.total ? "#9a1f1f" : "#444" }}>
            {duplicates.total}
          </div>
          <div style={{ fontSize: 10, color: "#666", marginTop: 2 }}>
            {duplicates.strong > 0 && `${duplicates.strong} strong · `}
            {duplicates.moderate > 0 && `${duplicates.moderate} moderate`}
            {duplicates.total === 0 && "no duplicates"}
          </div>
        </div>
      </div>
    </div>
  );
}
