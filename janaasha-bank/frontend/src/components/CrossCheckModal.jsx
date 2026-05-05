import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtAmount } from "../helpers.js";

/**
 * Surfaces potential double-bookings: same customer + same amount
 * recorded in both the UPI pipeline (branch Excel) AND the cash
 * pipeline (handwritten ledger). Grades each pair STRONG (policy
 * number matches too) or MODERATE (name + amount only).
 *
 * Read-only UI — the accountant uses this to spot the dup, then
 * goes to the relevant pipeline tab to resolve the wrong-side row.
 */
export default function CrossCheckModal({ onClose, showToast }) {
  const [loading, setLoading] = useState(true);
  const [duplicates, setDuplicates] = useState([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.getCrossCheckDuplicates();
        if (!cancelled) setDuplicates(d.duplicates || []);
      } catch (e) {
        if (!cancelled) showToast(e.message, { error: true });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [showToast]);

  const strong = duplicates.filter((d) => d.confidence === "STRONG");
  const moderate = duplicates.filter((d) => d.confidence === "MODERATE");

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff", borderRadius: 8, width: "min(900px, 92vw)",
          maxHeight: "85vh", overflow: "auto", padding: 20,
          boxShadow: "0 12px 40px rgba(0,0,0,0.3)",
        }}
      >
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 12,
        }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Cross-pipeline duplicate check</h2>
          <button
            onClick={onClose}
            style={{
              background: "transparent", border: "1px solid #ccc",
              padding: "4px 12px", borderRadius: 4, cursor: "pointer",
            }}
          >
            Close
          </button>
        </div>

        <p style={{ color: "#666", fontSize: 13, marginTop: 0 }}>
          Same customer + same amount appearing in both UPI and Cash pipelines.
          Likely a double-booking. <strong>STRONG</strong> = policy numbers
          also match (almost certainly the same payment booked twice).
          <strong> MODERATE</strong> = name + amount only.
        </p>

        {loading ? (
          <div style={{ padding: 30, textAlign: "center", color: "#888" }}>
            Checking…
          </div>
        ) : duplicates.length === 0 ? (
          <div style={{
            padding: 24, textAlign: "center",
            background: "#e8f5e8", color: "#1b5b1b",
            borderRadius: 6, fontWeight: 600,
          }}>
            ✓ No cross-pipeline duplicates found.
          </div>
        ) : (
          <>
            <div style={{ marginBottom: 12, fontSize: 13 }}>
              <span style={{
                background: "#fbdcdc", color: "#9a1f1f", padding: "2px 8px",
                borderRadius: 10, marginRight: 8, fontWeight: 600,
              }}>
                {strong.length} STRONG
              </span>
              <span style={{
                background: "#ffeacf", color: "#8b5a14", padding: "2px 8px",
                borderRadius: 10, fontWeight: 600,
              }}>
                {moderate.length} MODERATE
              </span>
            </div>

            <table style={{
              width: "100%", borderCollapse: "collapse", fontSize: 12,
            }}>
              <thead style={{ background: "#f0f0f0" }}>
                <tr>
                  <th style={{ padding: "6px 8px", textAlign: "left" }}>Customer</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>Amount</th>
                  <th style={{ padding: "6px 8px", textAlign: "left" }}>UPI side (branch Excel)</th>
                  <th style={{ padding: "6px 8px", textAlign: "left" }}>Cash side (ledger)</th>
                  <th style={{ padding: "6px 8px", textAlign: "center" }}>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {duplicates.map((d, i) => (
                  <tr
                    key={`${d.upi_id}-${d.cash_id}`}
                    style={{
                      background: i % 2 === 0 ? "#fff" : "#fafafa",
                      borderBottom: "1px solid #eee",
                    }}
                  >
                    <td style={{ padding: "6px 8px" }}>{d.upi_name}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right", fontWeight: 600 }}>
                      {fmtAmount(d.upi_amount)}
                    </td>
                    <td style={{ padding: "6px 8px", color: "#444" }}>
                      <div>policy {d.upi_policy_no || "—"}</div>
                      <div style={{ fontSize: 10, color: "#888" }}>
                        UTR {d.upi_utr} · {d.upi_branch} · {d.upi_status}
                      </div>
                    </td>
                    <td style={{ padding: "6px 8px", color: "#444" }}>
                      <div>policy {d.cash_policy_no || "—"}</div>
                      <div style={{ fontSize: 10, color: "#888" }}>
                        {d.cash_ledger_date} · {d.cash_status}
                      </div>
                    </td>
                    <td style={{ padding: "6px 8px", textAlign: "center" }}>
                      <span style={{
                        background: d.confidence === "STRONG" ? "#fbdcdc" : "#ffeacf",
                        color: d.confidence === "STRONG" ? "#9a1f1f" : "#8b5a14",
                        padding: "2px 8px", borderRadius: 10, fontWeight: 600,
                        fontSize: 10,
                      }}>
                        {d.confidence}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
