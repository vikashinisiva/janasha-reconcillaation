import { useMemo } from "react";
import { fmtDate } from "../helpers.js";

export default function Sidebar({
  branches,
  branchTotal,
  uploadedBranches,
  activeBranch,
  onBranchClick,
  canaraLibrary = [],
  bankLibrary = [],
  onDeleteStatement,
}) {
  const handleDelete = async (e, s) => {
    e.stopPropagation();
    if (!onDeleteStatement) return;
    const label = `${s.bankCode || "CANARA"} ${s.date}`;
    if (!window.confirm(`Remove ${label}? This deletes the uploaded file.`)) return;
    await onDeleteStatement(s.date, s.bankCode || "CANARA");
  };
  const library = bankLibrary.length ? bankLibrary : canaraLibrary;
  const { uploaded, pending } = useMemo(() => {
    const uploadedSet = new Set(Object.keys(uploadedBranches));
    const up = branches
      .filter((b) => uploadedSet.has(b.name))
      .sort((a, b) => a.name.localeCompare(b.name));
    const pend = branches
      .filter((b) => !uploadedSet.has(b.name))
      .sort((a, b) => a.code.localeCompare(b.code));
    return { uploaded: up, pending: pend };
  }, [branches, uploadedBranches]);

  const renderBranchRow = (b, isUploaded) => {
    const cls = [
      isUploaded ? "uploaded" : "",
      activeBranch === b.name ? "active" : "",
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <li key={b.code} className={cls} onClick={() => onBranchClick(b.name)}>
        <span className="b-code">{b.code}</span>
        <span className="b-name">{b.name}</span>
        <span className={`dot ${isUploaded ? "on" : ""}`} />
      </li>
    );
  };

  const uploadedCount = Object.keys(uploadedBranches).length;

  return (
    <aside className="sidebar">
      <div className="sidebar-section">
        <div className="sidebar-head">
          <span className="side-label">BRANCHES</span>
          <span className="side-count">
            {uploadedCount} / {branchTotal}
          </span>
        </div>
        <ul className="branch-list">
          {uploaded.map((b) => renderBranchRow(b, true))}
          {uploaded.length > 0 && pending.length > 0 && (
            <li className="branch-divider" aria-hidden="true" />
          )}
          {pending.map((b) => renderBranchRow(b, false))}
        </ul>
      </div>

      {library.length > 0 && (
        <div className="sidebar-section statement-section">
          <div className="sidebar-head">
            <span className="side-label">BANK STATEMENTS</span>
            <span className="side-count">{library.length}</span>
          </div>
          <ul className="statement-list">
            {library.map((s) => (
              <li
                key={`${s.date}-${s.bankCode || "CANARA"}`}
                className="statement-row"
              >
                <div className="statement-date">
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      background: "#f5e4b3",
                      color: "#5c4a00",
                      padding: "1px 5px",
                      borderRadius: 3,
                      marginRight: 6,
                    }}
                  >
                    {s.bankCode || "CANARA"}
                  </span>
                  {fmtDate(s.date)}
                </div>
                <div className="statement-file" title={s.filename}>
                  {s.filename}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 6,
                  }}
                >
                  {typeof s.credits === "number" ? (
                    <div className="statement-credits">
                      {s.credits} credits
                    </div>
                  ) : (
                    <span />
                  )}
                  {onDeleteStatement && (
                    <button
                      type="button"
                      onClick={(e) => handleDelete(e, s)}
                      title="Delete this statement"
                      style={{
                        background: "transparent",
                        border: "none",
                        color: "#a44",
                        cursor: "pointer",
                        padding: "2px 6px",
                        fontSize: 12,
                      }}
                    >
                      &#x2716;
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}
