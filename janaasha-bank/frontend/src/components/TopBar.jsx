import { useRef } from "react";

const DEFAULT_BANKS = [
  { code: "CANARA", name: "Canara" },
  { code: "SBI", name: "State Bank of India" },
  { code: "KVB", name: "Karur Vysya Bank" },
  { code: "IOB", name: "Indian Overseas Bank" },
  { code: "AXIS", name: "Axis Bank" },
];

function UploadIcon() {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
    >
      <path d="M12 16V4" />
      <path d="M6 10L12 4L18 10" />
      <path d="M4 20H20" />
    </svg>
  );
}

function BankPill({ code, count, active, onClick, onUpload, readOnly }) {
  const inputRef = useRef(null);
  const handleFile = (e) => {
    const f = e.target.files[0];
    if (f && onUpload) onUpload(f, code);
    e.target.value = "";
  };
  const baseBg = active ? "#8b6b1a" : count > 0 ? "#f5e4b3" : "#ededed";
  const baseColor = active ? "#fff" : count > 0 ? "#5c4a00" : "#666";
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 8px",
        borderRadius: 14,
        background: baseBg,
        color: baseColor,
        fontSize: 12,
        fontWeight: 600,
        cursor: "pointer",
        border: active ? "1px solid #5c4a00" : "1px solid transparent",
        transition: "background 120ms",
      }}
      onClick={() => onClick && onClick(code)}
      title={
        count > 0
          ? `${count} ${code} statement${count === 1 ? "" : "s"} — click to filter`
          : `No ${code} statements yet`
      }
    >
      <span>{code}</span>
      <span
        style={{
          minWidth: 18,
          height: 18,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 9,
          background: active ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.08)",
          fontSize: 10,
          padding: "0 5px",
        }}
      >
        {count}
      </span>
      {!readOnly && onUpload && (
        <label
          onClick={(e) => e.stopPropagation()}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 18,
            height: 18,
            borderRadius: 9,
            background: "rgba(0,0,0,0.12)",
            cursor: "pointer",
          }}
          title={`Upload ${code} statement`}
        >
          <input
            type="file"
            accept=".xls,.xlsx,.csv"
            hidden
            ref={inputRef}
            onChange={handleFile}
          />
          <UploadIcon />
        </label>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="btn-spinner"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" opacity="0.25" />
      <path d="M21 12A9 9 0 0 0 12 3" />
    </svg>
  );
}

export default function TopBar({
  today,
  canaraLibrary = [],
  bankLibrary = [],
  banks,
  activeBank,
  onBankClick,
  onBankUpload,
  branchesUploaded,
  branchTotal,
  allDone,
  readOnly,
  roleLabel,
  onAddBranch,
  onTally,
  onReconcile,
  reconciling,
  onClearDay,
}) {
  const library = bankLibrary.length ? bankLibrary : canaraLibrary;
  const bankOptions = banks && banks.length ? banks : DEFAULT_BANKS;
  const stmtCount = library.length;

  // Count statements per bank for the pill badges.
  const countsByBank = library.reduce((acc, s) => {
    const code = s.bankCode || "CANARA";
    acc[code] = (acc[code] || 0) + 1;
    return acc;
  }, {});

  const reconcileBtn =
    !readOnly && stmtCount > 0 && onReconcile ? (
      <button
        className="btn-gold-outline reconcile-btn"
        onClick={onReconcile}
        disabled={reconciling}
        title="Re-run reconciliation against the current library"
      >
        {reconciling && <Spinner />}
        <span>{reconciling ? "RECONCILING" : "RECONCILE NOW"}</span>
      </button>
    ) : null;

  const tallyBtn =
    stmtCount > 0 && onTally ? (
      <button className="btn-ghost tally-btn" onClick={onTally}>
        Tally
      </button>
    ) : null;

  const clearDayBtn =
    !readOnly && onClearDay ? (
      <button
        type="button"
        onClick={onClearDay}
        title="Wipe one specific date — keeps every other day intact"
        style={{
          background: "transparent",
          border: "1px solid #d9b56a",
          color: "#8b6b1a",
          padding: "4px 10px",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 1,
          borderRadius: 4,
          cursor: "pointer",
        }}
      >
        CLEAR DAY
      </button>
    ) : null;


  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="brand">
          <div className="logo">JN</div>
          <div className="brand-text">
            <div className="brand-name">Janaasha TN Nidhi</div>
            <div className="brand-sub">
              <span className="muted">Daily Reconciliation</span>
              <span className="sep">&middot;</span>
              <span className="date">{today}</span>
            </div>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginLeft: 16,
            flexWrap: "wrap",
          }}
        >
          {bankOptions.map((b) => (
            <BankPill
              key={b.code}
              code={b.code}
              count={countsByBank[b.code] || 0}
              active={activeBank === b.code}
              onClick={onBankClick}
              onUpload={onBankUpload}
              readOnly={readOnly}
            />
          ))}
        </div>
      </div>

      <div className="topbar-right">
        {readOnly ? (
          <div className="topbar-right-group">
            {tallyBtn}
            {roleLabel && <div className="role-label">{roleLabel}</div>}
          </div>
        ) : allDone ? (
          <div className="topbar-right-group">
            {clearDayBtn}
            {tallyBtn}
            {reconcileBtn}
            <button className="btn-gold" disabled>
              All Branches Uploaded
            </button>
          </div>
        ) : stmtCount > 0 ? (
          <div className="topbar-right-group">
            {typeof branchesUploaded === "number" &&
              typeof branchTotal === "number" && (
                <div className="branch-progress">
                  <span className="branch-progress-num">
                    {branchesUploaded}/{branchTotal}
                  </span>
                  <span className="branch-progress-label">branches</span>
                </div>
              )}
            {clearDayBtn}
            {tallyBtn}
            {reconcileBtn}
            <button className="btn-gold" onClick={onAddBranch}>
              Add Branch
            </button>
          </div>
        ) : (
          <div className="topbar-right-group">{clearDayBtn}</div>
        )}
      </div>
    </header>
  );
}
