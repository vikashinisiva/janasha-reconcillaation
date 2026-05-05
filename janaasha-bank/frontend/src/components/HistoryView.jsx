import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { fmtAmount, fmtDate, pillLabel } from "../helpers.js";

import CalendarHeatmap from "./CalendarHeatmap.jsx";

const EMPTY_FILTERS = {
  branch: "",
  date_from: "",
  date_to: "",
  status: "",
};

function buildFlagQuery(filters, resolvedMode) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v) p.set(k, v);
  }
  if (resolvedMode) p.set("resolved", resolvedMode);
  return p.toString();
}

function ResolveForm({ onSubmit, onCancel, busy }) {
  const [reason, setReason] = useState("");
  const [attachment, setAttachment] = useState(null);
  const inputRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!reason.trim()) return;
    onSubmit(reason.trim(), attachment);
  };

  const handleFile = (e) => {
    setAttachment(e.target.files[0] || null);
  };

  return (
    <form
      className="resolve-form"
      onSubmit={handleSubmit}
      style={{ flexWrap: "wrap", gap: 8 }}
    >
      <input
        ref={inputRef}
        type="text"
        placeholder="Reason (required)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        disabled={busy}
        style={{ flex: "1 1 260px", minWidth: 180 }}
      />
      <label
        title="Attach proof (screenshot, PDF, photo — optional)"
        style={{
          fontSize: 11,
          padding: "4px 8px",
          border: "1px solid var(--border, #ccc)",
          borderRadius: 4,
          cursor: busy ? "not-allowed" : "pointer",
          color: attachment ? "#5c4a00" : "#666",
          background: attachment ? "#f5e4b3" : "transparent",
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
        }}
      >
        <input
          ref={fileRef}
          type="file"
          hidden
          accept="image/*,.pdf"
          onChange={handleFile}
          disabled={busy}
        />
        {attachment ? `📎 ${attachment.name.slice(0, 18)}` : "📎 Attach proof"}
      </label>
      <button
        type="submit"
        className="btn-gold-outline"
        disabled={!reason.trim() || busy}
      >
        {busy ? "Saving..." : "Save"}
      </button>
      <button
        type="button"
        className="btn-ghost"
        onClick={onCancel}
        disabled={busy}
      >
        Cancel
      </button>
    </form>
  );
}

function FlagRow({
  flag,
  resolving,
  onStartResolve,
  onSubmitResolve,
  onCancelResolve,
  onUploadStatement,
  savingResolve,
  selected,
  onToggleSelect,
}) {
  const pillClass = `pill pill-${flag.status}`;
  const isPending = flag.status === "CANARA_PENDING";

  return (
    <>
      <tr className={`row-${flag.status}`}>
        <td style={{ width: 28, textAlign: "center" }}>
          {!isPending && (
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect(flag.id)}
              aria-label="Select for bulk resolve"
            />
          )}
        </td>
        <td className="mono">{fmtDate(flag.date) || flag.date || ""}</td>
        <td>
          {flag.bank_code ? (
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                background: "#f5e4b3",
                color: "#5c4a00",
                padding: "2px 6px",
                borderRadius: 3,
              }}
            >
              {flag.bank_code}
            </span>
          ) : (
            <span style={{ color: "#999", fontSize: 11 }}>—</span>
          )}
        </td>
        <td>{flag.branch || ""}</td>
        <td>{flag.customer_name || ""}</td>
        <td className="mono">{flag.agent_id || ""}</td>
        <td className="mono">{flag.utr || ""}</td>
        <td className="num">{fmtAmount(flag.excel_amount)}</td>
        <td className="num">{fmtAmount(flag.bank_amount)}</td>
        <td>
          <span className={pillClass}>{pillLabel(flag.status)}</span>
        </td>
        <td className="num">
          {isPending ? (
            <button
              type="button"
              className="resolve-btn"
              onClick={() => onUploadStatement(flag)}
              title={`Upload Canara statement for ${flag.date}`}
            >
              Upload Statement
            </button>
          ) : (
            <button
              type="button"
              className="resolve-btn"
              onClick={() => onStartResolve(flag.id)}
            >
              Resolve Manually
            </button>
          )}
        </td>
      </tr>
      {resolving && (
        <tr className="resolve-row">
          <td colSpan={11}>
            <ResolveForm
              onSubmit={(reason, attachment) =>
                onSubmitResolve(flag.id, reason, attachment)
              }
              onCancel={onCancelResolve}
              busy={savingResolve}
            />
          </td>
        </tr>
      )}
    </>
  );
}

export default function HistoryView({
  branches,
  summary,
  onRefreshSummary,
  onUploadCanara,
  onRunReconciliation,
  showToast,
}) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [openFlags, setOpenFlags] = useState([]);
  const [manualFlags, setManualFlags] = useState([]);
  const [manualExpanded, setManualExpanded] = useState(false);
  const [resolvingId, setResolvingId] = useState(null);
  const [savingResolve, setSavingResolve] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const uploadInputRef = useRef(null);
  const pendingUploadTargetRef = useRef(null);

  // Drop selections that no longer match the current open-flag set so we
  // never bulk-resolve a flag that has scrolled off via filters.
  useEffect(() => {
    setSelectedIds((prev) => {
      const live = new Set(openFlags.map((f) => f.id));
      const next = new Set();
      for (const id of prev) if (live.has(id)) next.add(id);
      return next;
    });
  }, [openFlags]);

  const selectableFlags = useMemo(
    () => openFlags.filter((f) => f.status !== "CANARA_PENDING"),
    [openFlags]
  );
  const allSelected =
    selectableFlags.length > 0 &&
    selectableFlags.every((f) => selectedIds.has(f.id));
  const anySelected = selectedIds.size > 0;

  const toggleSelect = useCallback((id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (selectableFlags.every((f) => prev.has(f.id))) {
        return new Set();
      }
      return new Set(selectableFlags.map((f) => f.id));
    });
  }, [selectableFlags]);

  const selectedSingleDate =
    filters.date_from &&
    filters.date_from === filters.date_to &&
    filters.date_from;

  // Fetch open + manually-resolved flags based on current filters
  const refetchFlags = useCallback(async () => {
    setLoading(true);
    try {
      const openQ = buildFlagQuery(filters, "open");
      const manualQ = buildFlagQuery(filters, "manual");
      const [openRes, manualRes] = await Promise.all([
        api.getFlagsHistory(openQ),
        api.getFlagsHistory(manualQ),
      ]);
      setOpenFlags(openRes.flags || []);
      setManualFlags(manualRes.flags || []);
    } catch (e) {
      showToast(e.message, { error: true });
    } finally {
      setLoading(false);
    }
  }, [filters, showToast]);

  useEffect(() => {
    refetchFlags();
  }, [refetchFlags]);

  // ----- handlers -----
  const setFilter = (key, value) =>
    setFilters((f) => ({ ...f, [key]: value }));

  const handleCalendarSelect = (dateKey) => {
    setFilters((f) => ({ ...f, date_from: dateKey, date_to: dateKey }));
  };

  const clearDateRange = () => {
    setFilters((f) => ({ ...f, date_from: "", date_to: "" }));
  };

  const handleStartResolve = (id) => setResolvingId(id);
  const handleCancelResolve = () => setResolvingId(null);

  const handleSubmitResolve = async (id, reason, attachment) => {
    setSavingResolve(true);
    try {
      await api.resolveFlag(id, reason, attachment);
      showToast(
        attachment ? "Flag resolved with proof attached" : "Flag resolved"
      );
      setResolvingId(null);
      await refetchFlags();
      if (onRefreshSummary) onRefreshSummary();
    } catch (e) {
      showToast(e.message, { error: true });
    } finally {
      setSavingResolve(false);
    }
  };

  const handleReopenFlag = async (id) => {
    if (
      !window.confirm(
        "Undo this resolution? The flag goes back to open and the attached proof file is deleted."
      )
    ) {
      return;
    }
    try {
      await api.reopenFlag(id);
      showToast("Flag reopened");
      await refetchFlags();
      if (onRefreshSummary) onRefreshSummary();
    } catch (e) {
      showToast(e.message, { error: true });
    }
  };

  const handleUploadStatement = (flag) => {
    pendingUploadTargetRef.current = flag;
    uploadInputRef.current?.click();
  };

  const handleStatementFilePick = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const target = pendingUploadTargetRef.current;
    pendingUploadTargetRef.current = null;
    e.target.value = "";
    try {
      const up = await onUploadCanara(f);
      // If the upload's parsed date doesn't match the flag's pending date,
      // warn Priya (the flag will stay pending until she uploads the
      // correct file).
      if (up && target && up.date !== target.date) {
        showToast(
          `Uploaded statement is for ${up.date}, but this flag needs ${target.date}`,
          { error: true }
        );
      }
      // Re-run reconciliation so the auto-resolve path picks up the change.
      if (onRunReconciliation) await onRunReconciliation();
      await refetchFlags();
      if (onRefreshSummary) onRefreshSummary();
    } catch (err) {
      showToast(err.message, { error: true });
    }
  };

  const handleExport = () => {
    window.location = api.flagsExportUrl(buildFlagQuery(filters, "open"));
  };

  const handleBulkResolve = async (reason, attachment) => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    setBulkBusy(true);
    try {
      const res = await api.resolveFlagsBulk(ids, reason, attachment);
      showToast(`Resolved ${res.resolved} flag${res.resolved === 1 ? "" : "s"}`);
      setBulkOpen(false);
      setSelectedIds(new Set());
      await refetchFlags();
      if (onRefreshSummary) onRefreshSummary();
    } catch (e) {
      showToast(e.message, { error: true });
    } finally {
      setBulkBusy(false);
    }
  };

  // ----- stat cards -----
  const totals = summary?.totals || {
    open: 0,
    oldestDays: null,
    branches: 0,
    dates: 0,
  };

  const rightHeader = selectedSingleDate ? (
    <>
      <div className="history-selected-date">{fmtDate(selectedSingleDate)}</div>
      <div className="history-selected-count">
        {openFlags.length} open flag{openFlags.length === 1 ? "" : "s"}
      </div>
    </>
  ) : filters.date_from || filters.date_to ? (
    <>
      <div className="history-selected-date">
        {filters.date_from ? fmtDate(filters.date_from) : "—"}
        {"  →  "}
        {filters.date_to ? fmtDate(filters.date_to) : "—"}
      </div>
      <div className="history-selected-count">
        {openFlags.length} open flag{openFlags.length === 1 ? "" : "s"}
      </div>
    </>
  ) : (
    <>
      <div className="history-selected-date">ALL DATES</div>
      <div className="history-selected-count">
        {openFlags.length} open flag{openFlags.length === 1 ? "" : "s"} across
        all history
      </div>
    </>
  );

  const recurring = summary?.recurring || [];

  return (
    <div className="history-view">
      {recurring.length > 0 && (
        <div
          style={{
            background: "#fdf5dd",
            border: "1px solid #e5c675",
            borderRadius: 6,
            padding: "10px 14px",
            marginBottom: 14,
            fontSize: 13,
            color: "#5c4a00",
          }}
          title="Branches with the same kind of open problem on 3 or more distinct days"
        >
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            ⚠ Recurring issues detected
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, listStyle: "disc" }}>
            {recurring.slice(0, 5).map((r, i) => (
              <li key={i}>
                <b>{r.branch}</b> has <b>{r.status}</b> flags on{" "}
                <b>{r.days}</b> distinct day{r.days === 1 ? "" : "s"}
                {r.firstDate && r.lastDate
                  ? ` (from ${r.firstDate} to ${r.lastDate})`
                  : ""}
                .
              </li>
            ))}
            {recurring.length > 5 && (
              <li style={{ color: "#7a6200" }}>
                …and {recurring.length - 5} more.
              </li>
            )}
          </ul>
        </div>
      )}
      <section className="history-summary">
        <div className="history-stat history-stat-red">
          <div className="history-stat-label">Total Open Flags</div>
          <div className="history-stat-value">{totals.open}</div>
        </div>
        <div className="history-stat history-stat-amber">
          <div className="history-stat-label">Oldest Unresolved</div>
          <div className="history-stat-value">
            {totals.oldestDays === null || totals.oldestDays === undefined
              ? "—"
              : `${totals.oldestDays}d`}
          </div>
        </div>
        <div className="history-stat history-stat-blue">
          <div className="history-stat-label">Branches w/ Issues</div>
          <div className="history-stat-value">{totals.branches}</div>
        </div>
        <div className="history-stat history-stat-muted">
          <div className="history-stat-label">Dates Affected</div>
          <div className="history-stat-value">{totals.dates}</div>
        </div>
      </section>

      <div className="history-panels">
        <aside className="history-left">
          <div className="history-section-head">FLAG CALENDAR</div>
          <CalendarHeatmap
            byDate={summary?.byDate || {}}
            statementDates={summary?.statementDates || []}
            selectedDate={selectedSingleDate || ""}
            onSelect={handleCalendarSelect}
          />
        </aside>

        <section className="history-right">
          <div className="history-right-head">{rightHeader}</div>

          <div className="history-filter-bar">
            <div className="filter-date-group">
              <label className="filter-date-label">From</label>
              <input
                type="date"
                value={filters.date_from}
                onChange={(e) => setFilter("date_from", e.target.value)}
              />
              <label className="filter-date-label">To</label>
              <input
                type="date"
                value={filters.date_to}
                onChange={(e) => setFilter("date_to", e.target.value)}
              />
              {(filters.date_from || filters.date_to) && (
                <button
                  type="button"
                  className="filter-clear"
                  onClick={clearDateRange}
                  title="Clear date range"
                >
                  ×
                </button>
              )}
            </div>
            <select
              value={filters.branch}
              onChange={(e) => setFilter("branch", e.target.value)}
            >
              <option value="">ALL BRANCHES</option>
              {branches.map((b) => (
                <option key={b.code} value={b.name}>
                  {b.name}
                </option>
              ))}
            </select>
            <select
              value={filters.status}
              onChange={(e) => setFilter("status", e.target.value)}
            >
              <option value="">ALL STATUSES</option>
              <option value="UNRECORDED">Unrecorded</option>
              <option value="MISSING">Missing from bank</option>
              <option value="MISMATCH">Amount mismatch</option>
              <option value="CANARA_PENDING">Canara pending</option>
            </select>
            <button
              type="button"
              className="btn-ghost"
              onClick={handleExport}
              disabled={openFlags.length === 0}
            >
              Export Open Flags
            </button>
          </div>

          {anySelected && !bulkOpen && (
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "#fdf5dd",
                border: "1px solid #e5c675",
                padding: "8px 12px",
                borderRadius: 4,
                marginBottom: 8,
                fontSize: 13,
              }}
            >
              <span>
                <b>{selectedIds.size}</b> flag
                {selectedIds.size === 1 ? "" : "s"} selected
              </span>
              <span style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn-gold-outline"
                  onClick={() => setBulkOpen(true)}
                >
                  Resolve selected
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => setSelectedIds(new Set())}
                >
                  Clear
                </button>
              </span>
            </div>
          )}
          {bulkOpen && (
            <div
              style={{
                background: "#fdf5dd",
                border: "1px solid #e5c675",
                padding: "10px 12px",
                borderRadius: 4,
                marginBottom: 8,
              }}
            >
              <div style={{ fontSize: 12, marginBottom: 6, color: "#5c4a00" }}>
                Resolving <b>{selectedIds.size}</b> flag
                {selectedIds.size === 1 ? "" : "s"} with one shared reason.
              </div>
              <ResolveForm
                onSubmit={handleBulkResolve}
                onCancel={() => setBulkOpen(false)}
                busy={bulkBusy}
              />
            </div>
          )}
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th style={{ width: 28, textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleSelectAll}
                      disabled={selectableFlags.length === 0}
                      aria-label="Select all"
                    />
                  </th>
                  <th>Date</th>
                  <th>Bank</th>
                  <th>Branch</th>
                  <th>Customer Name</th>
                  <th>Agent ID</th>
                  <th>UTR</th>
                  <th className="num">Excel Amount</th>
                  <th className="num">Bank Amount</th>
                  <th>Status</th>
                  <th className="num">Action</th>
                </tr>
              </thead>
              <tbody>
                {loading && openFlags.length === 0 ? (
                  <tr className="empty">
                    <td colSpan={11}>LOADING...</td>
                  </tr>
                ) : openFlags.length === 0 ? (
                  <tr className="empty">
                    <td colSpan={11}>NO OPEN FLAGS FOR THIS VIEW</td>
                  </tr>
                ) : (
                  openFlags.map((flag) => (
                    <FlagRow
                      key={flag.id}
                      flag={flag}
                      resolving={resolvingId === flag.id}
                      savingResolve={savingResolve}
                      onStartResolve={handleStartResolve}
                      onCancelResolve={handleCancelResolve}
                      onSubmitResolve={handleSubmitResolve}
                      onUploadStatement={handleUploadStatement}
                      selected={selectedIds.has(flag.id)}
                      onToggleSelect={toggleSelect}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>

          {manualFlags.length > 0 && (
            <div className="manual-resolved-section">
              <button
                type="button"
                className="manual-resolved-toggle"
                onClick={() => setManualExpanded((v) => !v)}
              >
                <span className="manual-chev">{manualExpanded ? "−" : "+"}</span>
                MANUALLY RESOLVED ({manualFlags.length})
              </button>
              {manualExpanded && (
                <table className="history-table manual-resolved-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Bank</th>
                      <th>Branch</th>
                      <th>Customer</th>
                      <th>UTR</th>
                      <th>Status</th>
                      <th>Reason</th>
                      <th>Proof</th>
                      <th>Resolved At</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {manualFlags.map((f) => (
                      <tr key={f.id} className="resolved">
                        <td className="mono">{f.date}</td>
                        <td>
                          {f.bank_code ? (
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 700,
                                background: "#f5e4b3",
                                color: "#5c4a00",
                                padding: "2px 6px",
                                borderRadius: 3,
                              }}
                            >
                              {f.bank_code}
                            </span>
                          ) : (
                            <span style={{ color: "#999", fontSize: 11 }}>—</span>
                          )}
                        </td>
                        <td>{f.branch}</td>
                        <td>{f.customer_name}</td>
                        <td className="mono">{f.utr}</td>
                        <td>
                          <span className={`pill pill-${f.status}`}>
                            {pillLabel(f.status)}
                          </span>
                        </td>
                        <td className="resolve-reason">{f.resolved_reason}</td>
                        <td>
                          {f.resolved_attachment ? (
                            <a
                              href={api.flagAttachmentUrl(f.id)}
                              target="_blank"
                              rel="noreferrer"
                              style={{ fontSize: 12, color: "#5c4a00" }}
                              title="Open attached proof"
                            >
                              View
                            </a>
                          ) : (
                            <span style={{ color: "#bbb", fontSize: 11 }}>—</span>
                          )}
                        </td>
                        <td className="mono resolve-timestamp">
                          {f.resolved_at ? f.resolved_at.slice(0, 16).replace("T", " ") : ""}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="resolve-btn"
                            onClick={() => handleReopenFlag(f.id)}
                            title="Undo this resolution — flag goes back to open"
                            style={{
                              background: "transparent",
                              border: "1px solid #c99",
                              color: "#a44",
                              fontSize: 11,
                            }}
                          >
                            Reopen
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </section>
      </div>

      <input
        type="file"
        hidden
        accept=".xls,.xlsx,.csv"
        ref={uploadInputRef}
        onChange={handleStatementFilePick}
      />
    </div>
  );
}
