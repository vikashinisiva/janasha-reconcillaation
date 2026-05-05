import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { fmtAmount } from "../helpers.js";

const CASH_TABS = [
  { id: "matched",              label: "Matched" },
  { id: "missing_from_bank",    label: "Missing from Bank" },
  { id: "unrecorded_in_ledger", label: "Unrecorded in Ledger" },
  { id: "cash_in_hand",         label: "Cash in Hand" },
];

const STATUS_COLOR = {
  MATCHED:              { bg: "#d8f0d8", fg: "#1b5b1b" },
  MISSING_FROM_BANK:    { bg: "#fbdcdc", fg: "#9a1f1f" },
  UNRECORDED_IN_LEDGER: { bg: "#ffeacf", fg: "#8b5a14" },
  CASH_IN_HAND:         { bg: "#e3e3f4", fg: "#3a3a8c" },
};

function StatusPill({ status }) {
  const c = STATUS_COLOR[status] || { bg: "#eee", fg: "#444" };
  return (
    <span
      style={{
        background: c.bg,
        color: c.fg,
        padding: "3px 8px",
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {(status || "").replace(/_/g, " ")}
    </span>
  );
}

function CashRow({ row, onResolve, onUnresolve }) {
  return (
    <tr className={row.resolved ? "resolved" : ""}>
      <td className="num">{row.sl ?? ""}</td>
      <td>{row.name || ""}</td>
      <td className="mono">{row.policy_no || ""}</td>
      <td className="num">{fmtAmount(row.ledger_amount)}</td>
      <td>{row.ledger_date || ""}</td>
      <td>{row.bank_code || ""}</td>
      <td className="num">{fmtAmount(row.bank_amount)}</td>
      <td>{row.bank_date || ""}</td>
      <td className="mono" title={row.machine || ""}>{row.machine || ""}</td>
      <td className="mono">{row.ref || ""}</td>
      <td><StatusPill status={row.status} /></td>
      <td className="num">
        {row.resolved ? (
          <button
            className="resolve-btn"
            onClick={() => onUnresolve(row.id)}
            style={{ background: "transparent", border: "1px solid #c99", color: "#a44" }}
          >
            Unresolve
          </button>
        ) : row.status === "MATCHED" || row.status === "CASH_IN_HAND" ? (
          <span className="resolved-label">&mdash;</span>
        ) : (
          <button className="resolve-btn" onClick={() => onResolve(row.id)}>
            Resolve
          </button>
        )}
      </td>
    </tr>
  );
}

function todayIso() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export default function CashView({ banks = [], showToast }) {
  const [date, setDate] = useState(todayIso());
  const [tab, setTab] = useState("missing_from_bank");
  const [rows, setRows] = useState([]);
  const [counts, setCounts] = useState(null);
  const [dailySummary, setDailySummary] = useState([]);
  const [banksUsed, setBanksUsed] = useState([]);
  const [includeResolved, setIncludeResolved] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const [ledgerInfo, setLedgerInfo] = useState(null);
  const ledgerInputRef = useRef(null);
  const bankInputRefs = useRef({});
  const ocrInputRef = useRef(null);
  // OCR availability is probed once on mount. {available, reason, model}.
  // Reason is non-null when the button should be shown disabled, with the
  // tooltip explaining what to do (set ANTHROPIC_API_KEY etc).
  const [ocrStatus, setOcrStatus] = useState({ available: false, reason: "checking…" });
  const [ocrBusy, setOcrBusy] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const d = await api.getCashData(tab, { date, includeResolved });
      setRows(d.rows || []);
    } catch (e) {
      showToast(e.message, { error: true });
    }
  }, [tab, date, includeResolved, showToast]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // One-shot OCR availability probe. Runs once per mount.
  useEffect(() => {
    let cancelled = false;
    api.getOcrStatus()
      .then((s) => { if (!cancelled) setOcrStatus(s); })
      .catch(() => { if (!cancelled) setOcrStatus({ available: false, reason: "probe failed" }); });
    return () => { cancelled = true; };
  }, []);

  const handleOcrPhoto = async (file) => {
    if (!file) return;
    if (!ocrStatus.available) {
      showToast(`OCR unavailable: ${ocrStatus.reason}`, { error: true });
      return;
    }
    setOcrBusy(true);
    try {
      const d = await api.ocrLedgerPhoto(file, date);
      showToast(`OCR'd ${d.rows} rows for ${d.date} via ${d.model || "Claude"}`);
      setLedgerInfo(d);
    } catch (e) {
      showToast(e.message, { error: true });
    } finally {
      setOcrBusy(false);
    }
  };

  const handleUploadLedger = async (file) => {
    if (!file) return;
    try {
      const d = await api.uploadLedgerCsv(file, date);
      setLedgerInfo(d);
      showToast(`Ledger ${d.date} · ${d.rows} rows uploaded`);
    } catch (e) {
      showToast(e.message, { error: true });
    }
  };

  const handleUploadBank = async (bankCode, file) => {
    if (!file) return;
    try {
      const d = await api.uploadBankStatement(bankCode, file);
      showToast(`${bankCode} ${d.date} · ${d.credits || 0} cash deposits`);
    } catch (e) {
      showToast(e.message, { error: true });
    }
  };

  const handleReconcile = async () => {
    setReconciling(true);
    try {
      const d = await api.reconcileCash(date, 1);
      setCounts(d.counts || null);
      setDailySummary(d.daily_summary || []);
      setBanksUsed(d.banks_used || []);
      const c = d.counts || {};
      const flagged = (c.missing_from_bank || 0) + (c.unrecorded_in_ledger || 0);
      showToast(
        `Cash reconciled · ${c.matched || 0} matched, ${flagged} flagged, ${c.cash_in_hand || 0} in hand`
      );
      await fetchData();
    } catch (e) {
      showToast(e.message, { error: true });
    } finally {
      setReconciling(false);
    }
  };

  const handleResolve = async (id) => {
    try { await api.resolveCash(id); showToast("Row resolved"); await fetchData(); }
    catch (e) { showToast(e.message, { error: true }); }
  };
  const handleUnresolve = async (id) => {
    try { await api.unresolveCash(id); showToast("Row unresolved"); await fetchData(); }
    catch (e) { showToast(e.message, { error: true }); }
  };

  // Banks that may carry cash deposits. Axis included as an optional
  // source — its parser returns an empty frame for a UPI-only Axis
  // account, so showing the button costs nothing.
  const cashBanks = ["KVB", "SBI", "IOB", "AXIS"];

  return (
    <div className="cash-view" style={{ padding: "12px 18px" }}>
      {/* ── Action bar: date + uploads + reconcile ─────────────────── */}
      <div style={{
        display: "flex", flexWrap: "wrap", alignItems: "center",
        gap: 12, padding: "10px 14px", background: "#fafafa",
        border: "1px solid #e6e6e6", borderRadius: 8, marginBottom: 12,
      }}>
        <label style={{ fontSize: 13, fontWeight: 600 }}>
          Date:&nbsp;
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            style={{ padding: "4px 6px", border: "1px solid #ccc", borderRadius: 4 }}
          />
        </label>

        <button
          className="resolve-btn"
          onClick={() => ledgerInputRef.current?.click()}
          title="Upload digitized handwritten ledger CSV"
        >
          + Ledger CSV
        </button>
        <input
          ref={ledgerInputRef}
          type="file"
          accept=".csv"
          style={{ display: "none" }}
          onChange={(e) => { handleUploadLedger(e.target.files[0]); e.target.value = ""; }}
        />

        <button
          className="resolve-btn"
          onClick={() => ocrInputRef.current?.click()}
          disabled={!ocrStatus.available || ocrBusy}
          title={
            ocrStatus.available
              ? `OCR a ledger photo via Claude Vision (${ocrStatus.model})`
              : `OCR unavailable: ${ocrStatus.reason}. Set ANTHROPIC_API_KEY to enable.`
          }
          style={{
            opacity: ocrStatus.available ? 1 : 0.55,
            cursor: ocrStatus.available && !ocrBusy ? "pointer" : "not-allowed",
            background: ocrStatus.available ? "#e8f0fb" : "#ededed",
            color: ocrStatus.available ? "#1a4b8b" : "#888",
            border: ocrStatus.available ? "1px solid #b8c9e0" : "1px solid #ccc",
          }}
        >
          {ocrBusy ? "OCR'ing…" : "+ Ledger Photo (OCR)"}
        </button>
        <input
          ref={ocrInputRef}
          type="file"
          accept="image/*"
          style={{ display: "none" }}
          onChange={(e) => { handleOcrPhoto(e.target.files[0]); e.target.value = ""; }}
        />

        {cashBanks.map((code) => (
          <span key={code}>
            <button
              className="resolve-btn"
              onClick={() => bankInputRefs.current[code]?.click()}
              title={`Upload ${code} cash-deposit statement`}
            >
              + {code}
            </button>
            <input
              ref={(el) => (bankInputRefs.current[code] = el)}
              type="file"
              accept=".xls,.xlsx,.csv"
              style={{ display: "none" }}
              onChange={(e) => { handleUploadBank(code, e.target.files[0]); e.target.value = ""; }}
            />
          </span>
        ))}

        <div style={{ flex: 1 }} />

        <button
          className="resolve-btn"
          onClick={handleReconcile}
          disabled={reconciling}
          style={{
            background: reconciling ? "#ccc" : "#1b5b1b",
            color: "#fff", border: 0, padding: "6px 14px",
            fontWeight: 700, letterSpacing: "0.04em",
          }}
        >
          {reconciling ? "RECONCILING…" : "RECONCILE CASH"}
        </button>
      </div>

      {/* ── Summary cards (post-reconcile) ─────────────────────────── */}
      {counts && (
        <div style={{
          display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12,
        }}>
          {CASH_TABS.map((t) => {
            const n = counts[t.id] || 0;
            return (
              <div
                key={t.id}
                onClick={() => setTab(t.id)}
                style={{
                  background: tab === t.id ? "#5c4a00" : "#fff",
                  color: tab === t.id ? "#fff" : "#444",
                  border: "1px solid #d0d0d0",
                  padding: "6px 12px", borderRadius: 6,
                  cursor: "pointer", fontSize: 12, fontWeight: 600,
                  minWidth: 130,
                }}
              >
                <div style={{ fontSize: 11, opacity: 0.85 }}>{t.label}</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{n}</div>
              </div>
            );
          })}
          {banksUsed.length > 0 && (
            <div style={{
              alignSelf: "center", marginLeft: "auto",
              fontSize: 11, color: "#666",
            }}>
              banks used: {banksUsed.join(" · ")}
            </div>
          )}
        </div>
      )}

      {/* ── Daily summary (one row per date with activity) ─────────── */}
      {dailySummary.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <table style={{
            fontSize: 12, borderCollapse: "collapse",
            background: "#fff", border: "1px solid #e6e6e6",
          }}>
            <thead style={{ background: "#f0f0f0" }}>
              <tr>
                <th style={{ padding: "4px 10px", textAlign: "left" }}>Date</th>
                <th style={{ padding: "4px 10px", textAlign: "right" }}>Ledger Bank-side</th>
                <th style={{ padding: "4px 10px", textAlign: "right" }}>Bank Deposits</th>
                <th style={{ padding: "4px 10px", textAlign: "right" }}>Delta</th>
              </tr>
            </thead>
            <tbody>
              {dailySummary.map((d) => (
                <tr key={d.date}>
                  <td style={{ padding: "3px 10px" }}>{d.date}</td>
                  <td style={{ padding: "3px 10px", textAlign: "right" }}>
                    {fmtAmount(d.ledger_bank_total)}
                  </td>
                  <td style={{ padding: "3px 10px", textAlign: "right" }}>
                    {fmtAmount(d.bank_deposit_total)}
                  </td>
                  <td style={{
                    padding: "3px 10px", textAlign: "right",
                    color: d.delta === 0 ? "#1b5b1b" : (d.delta > 0 ? "#8b5a14" : "#9a1f1f"),
                    fontWeight: 600,
                  }}>
                    {d.delta > 0 ? "+" : ""}{fmtAmount(d.delta)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Tabs ──────────────────────────────────────────────────── */}
      <nav className="tabs" style={{ marginBottom: 8 }}>
        {CASH_TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {counts && counts[t.id] > 0 && (
              <span className="tab-badge">{counts[t.id]}</span>
            )}
          </button>
        ))}
        <label style={{
          marginLeft: "auto", fontSize: 12, color: "#666",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <input
            type="checkbox"
            checked={includeResolved}
            onChange={(e) => setIncludeResolved(e.target.checked)}
          />
          show resolved
        </label>
      </nav>

      {/* ── Table ─────────────────────────────────────────────────── */}
      <section className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="num">Sl</th>
              <th>Name</th>
              <th>Policy No</th>
              <th className="num">Ledger Amt</th>
              <th>Ledger Date</th>
              <th>Bank</th>
              <th className="num">Bank Amt</th>
              <th>Bank Date</th>
              <th>Machine</th>
              <th>Ref</th>
              <th>Status</th>
              <th className="num">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr className="empty">
                <td colSpan={12}>
                  {counts === null
                    ? "UPLOAD LEDGER + BANK STATEMENTS, THEN CLICK RECONCILE CASH"
                    : "NO ROWS IN THIS BUCKET"}
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <CashRow
                  key={r.id}
                  row={r}
                  onResolve={handleResolve}
                  onUnresolve={handleUnresolve}
                />
              ))
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
