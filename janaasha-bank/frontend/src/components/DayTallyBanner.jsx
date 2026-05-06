import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtAmount } from "../helpers.js";

/**
 * Single-line verdict at the very top of the dashboard:
 *   "✓ Tallied — every rupee accounted for"  OR
 *   "⚠ Off by ₹15,400 — branch booked cash deposits the bank never received"
 *
 * Powered by GET /api/day-tally. Auto-refreshes when refreshKey bumps
 * (parent bumps it after every reconcile run).
 *
 * Click the verdict expands a small breakdown panel showing the three
 * sources side-by-side (Branch claimed · Bank received · Cash held).
 */
export default function DayTallyBanner({ refreshKey = 0, today }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getDayTally()
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (loading && !data) {
    return (
      <div style={{ padding: "10px 18px", color: "#888", fontSize: 12 }}>
        Loading day tally…
      </div>
    );
  }
  if (!data) return null;

  const { tally, branch_claimed, bank_received, cash_position } = data;
  const ok = tally.overall_ok;
  const totalDelta = Math.abs(tally.upi_delta) + Math.abs(tally.cash_delta);

  return (
    <div style={{
      margin: "8px 18px 0",
      borderRadius: 6,
      overflow: "hidden",
      border: "1px solid " + (ok ? "#9bc99b" : "#d6a09a"),
    }}>
      {/* ── Verdict line ────────────────────────────────────────── */}
      <div
        onClick={() => setExpanded((e) => !e)}
        style={{
          background: ok ? "#e8f5e8" : "#fbeeed",
          padding: "12px 16px",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <span style={{
          fontSize: 22,
          fontWeight: 700,
          color: ok ? "#1b5b1b" : "#9a1f1f",
          minWidth: 28,
          textAlign: "center",
        }}>
          {ok ? "✓" : "⚠"}
        </span>

        <div style={{ flex: 1 }}>
          <div style={{
            fontSize: 14,
            fontWeight: 700,
            color: ok ? "#1b5b1b" : "#9a1f1f",
            letterSpacing: "0.02em",
          }}>
            {ok
              ? "Day tallied"
              : `Off by ₹${fmtAmount(totalDelta)}`}
            {today && (
              <span style={{
                fontSize: 11, fontWeight: 500, color: "#666",
                marginLeft: 10,
              }}>
                · {today}
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: "#555", marginTop: 2 }}>
            {ok
              ? `₹${fmtAmount(branch_claimed.total)} handled today, every rupee accounted for.`
              : tally.notes[0] || "Branch and bank totals don't match yet."}
          </div>
        </div>

        <span style={{ fontSize: 11, color: "#888", marginLeft: 12 }}>
          {expanded ? "hide details ▴" : "show details ▾"}
        </span>
      </div>

      {/* ── Expanded breakdown ─────────────────────────────────── */}
      {expanded && (
        <div style={{
          background: "#fff",
          padding: "12px 16px",
          borderTop: "1px solid " + (ok ? "#9bc99b" : "#d6a09a"),
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 16,
          fontSize: 12,
        }}>
          {/* Branch claimed */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#666",
                          letterSpacing: "0.06em", marginBottom: 6 }}>
              BRANCH CLAIMED
            </div>
            <div style={{ display: "grid", gap: 3 }}>
              <Row label="UPI"             value={branch_claimed.upi} />
              <Row label="Cash kept"       value={branch_claimed.cash_kept} />
              <Row label="Cash deposited"  value={branch_claimed.cash_deposited} />
              <Row label="Total"           value={branch_claimed.total} bold />
            </div>
          </div>

          {/* Bank received */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#666",
                          letterSpacing: "0.06em", marginBottom: 6 }}>
              BANK RECEIVED
            </div>
            <div style={{ display: "grid", gap: 3 }}>
              <Row label="Canara UPI" value={bank_received.canara_upi} />
              {Object.entries(bank_received.cash_per_bank || {}).map(([code, amt]) => (
                <Row key={code} label={`${code} cash`} value={amt} />
              ))}
              <Row label="Cash total" value={bank_received.cash_total} muted />
              <Row label="Total" value={bank_received.total} bold />
            </div>
          </div>

          {/* Cash held + verdict */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#666",
                          letterSpacing: "0.06em", marginBottom: 6 }}>
              CASH HELD AT BRANCH
            </div>
            <div style={{ display: "grid", gap: 3 }}>
              <Row label="Held at counter" value={cash_position.held_at_branch} />
            </div>

            <div style={{
              marginTop: 12,
              paddingTop: 8,
              borderTop: "1px dashed #ccc",
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#666",
                            letterSpacing: "0.06em", marginBottom: 6 }}>
                DELTAS
              </div>
              <div style={{ display: "grid", gap: 3 }}>
                <DeltaRow label="UPI side"  delta={tally.upi_delta}  ok={tally.upi_ok}  />
                <DeltaRow label="Cash side" delta={tally.cash_delta} ok={tally.cash_ok} />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value, bold, muted }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      borderTop: bold ? "1px solid #ddd" : undefined,
      paddingTop: bold ? 4 : 0,
      marginTop:  bold ? 4 : 0,
      fontWeight: bold ? 700 : 500,
      color: muted ? "#888" : "#333",
    }}>
      <span>{label}</span>
      <span style={{ fontVariantNumeric: "tabular-nums" }}>
        ₹{fmtAmount(value || 0)}
      </span>
    </div>
  );
}

function DeltaRow({ label, delta, ok }) {
  const sign = delta > 0 ? "+" : (delta < 0 ? "−" : "");
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      color: ok ? "#1b5b1b" : "#9a1f1f",
      fontWeight: 600,
    }}>
      <span>
        {ok ? "✓" : "⚠"} {label}
      </span>
      <span style={{ fontVariantNumeric: "tabular-nums" }}>
        {ok ? "—" : `${sign}₹${fmtAmount(Math.abs(delta))}`}
      </span>
    </div>
  );
}
