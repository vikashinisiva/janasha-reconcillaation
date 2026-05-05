import { useEffect, useRef, useState } from "react";
import { fmtDate } from "../helpers.js";

function greeting(now = new Date()) {
  const h = now.getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function BankIcon() {
  return (
    <svg
      width="32"
      height="32"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
    >
      <path d="M3 10L12 4L21 10" />
      <path d="M5 10V19M9 10V19M15 10V19M19 10V19" />
      <path d="M3 19H21" />
      <path d="M3 22H21" />
    </svg>
  );
}

function useDropZone(zoneRef, onFile) {
  useEffect(() => {
    const el = zoneRef.current;
    if (!el) return;
    const onOver = (e) => {
      e.preventDefault();
      el.classList.add("dragover");
    };
    const onLeave = () => el.classList.remove("dragover");
    const onDrop = (e) => {
      e.preventDefault();
      el.classList.remove("dragover");
      const f = e.dataTransfer.files[0];
      if (f) onFile(f);
    };
    el.addEventListener("dragover", onOver);
    el.addEventListener("dragenter", onOver);
    el.addEventListener("dragleave", onLeave);
    el.addEventListener("drop", onDrop);
    return () => {
      el.removeEventListener("dragover", onOver);
      el.removeEventListener("dragenter", onOver);
      el.removeEventListener("dragleave", onLeave);
      el.removeEventListener("drop", onDrop);
    };
  }, [zoneRef, onFile]);
}

function Zone({ label, hint, onFile, busy, variant }) {
  const zoneRef = useRef(null);
  const inputRef = useRef(null);

  const handle = (file) => {
    if (!file) return;
    onFile(file);
  };

  useDropZone(zoneRef, handle);

  const handlePick = (e) => {
    const f = e.target.files[0];
    if (f) handle(f);
    e.target.value = "";
  };

  return (
    <label className={`setup-zone setup-zone-${variant}`} ref={zoneRef}>
      <input
        type="file"
        accept=".xls,.xlsx,.csv"
        hidden
        ref={inputRef}
        onChange={handlePick}
        disabled={busy}
      />
      <div className="setup-zone-icon">
        <BankIcon />
      </div>
      <div className="setup-zone-title">{label}</div>
      <div className="setup-zone-hint">{hint}</div>
    </label>
  );
}

const DEFAULT_BANKS = [
  { code: "CANARA", name: "Canara" },
  { code: "SBI", name: "State Bank of India" },
  { code: "KVB", name: "Karur Vysya Bank" },
  { code: "IOB", name: "Indian Overseas Bank" },
  { code: "AXIS", name: "Axis Bank" },
];

export default function SetupOverlay({ today, uploaded, banks, onUpload, onContinue }) {
  const [busy, setBusy] = useState(false);
  const [bankCode, setBankCode] = useState("CANARA");
  const bankOptions = banks && banks.length ? banks : DEFAULT_BANKS;
  const library = uploaded.bankLibrary || uploaded.canaraLibrary || [];
  const hasAny = library.length > 0;

  const handleUpload = async (file) => {
    setBusy(true);
    try {
      await onUpload(file, bankCode);
    } finally {
      setBusy(false);
    }
  };

  const activeBankName =
    (bankOptions.find((b) => b.code === bankCode) || {}).name || bankCode;

  return (
    <div className="setup-overlay">
      <div className="setup-panel">
        <div className="setup-top-border" />
        <button
          type="button"
          className="setup-close"
          onClick={onContinue}
          aria-label="Close"
          title="Close"
          style={{
            position: "absolute",
            top: 12,
            right: 12,
            width: 32,
            height: 32,
            borderRadius: 16,
            border: "none",
            background: "transparent",
            cursor: "pointer",
            fontSize: 22,
            lineHeight: 1,
            color: "#5c4a00",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          ×
        </button>
        <div className="setup-inner">
          <div className="setup-header">
            <div className="setup-greeting">{greeting()}</div>
            <div className="setup-date">{today}</div>
            <div className="setup-sub">
              Upload a bank statement to begin today&rsquo;s reconciliation.
            </div>
          </div>

          <div
            className="setup-bank-picker"
            style={{
              margin: "14px 0 10px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 6,
            }}
          >
            <div style={{ fontSize: 12, color: "#666", letterSpacing: 1 }}>
              CHOOSE BANK
            </div>
            <div
              style={{
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                justifyContent: "center",
              }}
            >
              {bankOptions.map((b) => {
                const active = bankCode === b.code;
                return (
                  <button
                    key={b.code}
                    type="button"
                    onClick={() => setBankCode(b.code)}
                    disabled={busy}
                    style={{
                      padding: "6px 12px",
                      borderRadius: 16,
                      fontSize: 12,
                      fontWeight: 700,
                      cursor: busy ? "not-allowed" : "pointer",
                      background: active ? "#8b6b1a" : "#f5e4b3",
                      color: active ? "#fff" : "#5c4a00",
                      border: active
                        ? "1px solid #5c4a00"
                        : "1px solid #d9c580",
                      transition: "background 120ms",
                    }}
                    title={b.name}
                  >
                    {b.code}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="setup-zones">
            <Zone
              variant="primary"
              label={`Today's ${activeBankName} Statement`}
              hint="Drag &amp; drop or click &middot; .xls / .xlsx / .csv"
              onFile={handleUpload}
              busy={busy}
            />
            <Zone
              variant="secondary"
              label="Historical Statement"
              hint="Upload if reconciling late entries"
              onFile={handleUpload}
              busy={busy}
            />
          </div>

          {hasAny && (
            <ul className="setup-library">
              {library.map((s) => (
                <li key={`${s.date}-${s.bankCode || "CANARA"}`}>
                  <span className="setup-lib-check">&#10003;</span>
                  <span
                    className="setup-lib-bank"
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      background: "#f5e4b3",
                      padding: "2px 6px",
                      borderRadius: 4,
                      marginRight: 8,
                    }}
                  >
                    {s.bankCode || "CANARA"}
                  </span>
                  <span className="setup-lib-date">{fmtDate(s.date)}</span>
                  <span className="setup-lib-file">{s.filename}</span>
                  {typeof s.credits === "number" && (
                    <span className="setup-lib-credits">
                      {s.credits} credits
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}

          {hasAny && (
            <button
              type="button"
              className="btn-gold full setup-continue"
              onClick={onContinue}
            >
              START RECONCILIATION DAY
            </button>
          )}

          <div className="setup-footer">
            These statements will remain active for today&rsquo;s session.
            You can upload additional historical statements any time from the
            sidebar.
          </div>
        </div>
      </div>
    </div>
  );
}
