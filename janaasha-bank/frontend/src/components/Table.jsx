import { useEffect, useRef } from "react";
import { fmtAmount, pillLabel } from "../helpers.js";

function Row({ row, onResolve, onUnresolve, onPendingClick, readOnly }) {
  const trCls = [row.resolved ? "resolved" : "", `row-${row.status}`]
    .filter(Boolean)
    .join(" ");
  const isPending = row.status === "CANARA_PENDING";
  const pillClass = `pill pill-${row.status}${isPending ? " pill-clickable" : ""}`;
  const handlePillClick = () => {
    if (isPending && onPendingClick) onPendingClick(row.pending_date);
  };
  return (
    <tr className={trCls}>
      <td>{row.branch || ""}</td>
      <td>{row.customer_name || ""}</td>
      <td className="mono">{row.agent_id || ""}</td>
      <td className="mono">{row.policy_no || ""}</td>
      <td>{row.policy_type || ""}</td>
      <td className="mono">{row.utr || ""}</td>
      <td className="num">{fmtAmount(row.excel_amount)}</td>
      <td className="num">{fmtAmount(row.bank_amount)}</td>
      <td>
        <span
          className={pillClass}
          onClick={handlePillClick}
          title={isPending && row.pending_date ? `Upload Canara for ${row.pending_date}` : undefined}
        >
          {pillLabel(row.status)}
        </span>
      </td>
      {!readOnly && (
        <td className="num">
          {row.resolved ? (
            onUnresolve ? (
              <button
                className="resolve-btn"
                onClick={() => onUnresolve(row.id)}
                title="Move back to Active Issues"
                style={{
                  background: "transparent",
                  border: "1px solid #c99",
                  color: "#a44",
                }}
              >
                Unresolve
              </button>
            ) : (
              <span className="resolved-label">Resolved</span>
            )
          ) : isPending || row.status === "MATCHED" ? (
            <span className="resolved-label">&mdash;</span>
          ) : (
            <button className="resolve-btn" onClick={() => onResolve(row.id)}>
              Resolve
            </button>
          )}
        </td>
      )}
    </tr>
  );
}

export default function Table({
  rows,
  runKey,
  onResolve,
  onUnresolve,
  onPendingClick,
  readOnly = false,
}) {
  const tbodyRef = useRef(null);
  const lastKeyRef = useRef(runKey);
  const colCount = readOnly ? 9 : 10;

  // Stagger row fade-in + pill scale-in whenever runKey bumps.
  useEffect(() => {
    if (runKey === lastKeyRef.current || runKey === 0) {
      lastKeyRef.current = runKey;
      return;
    }
    lastKeyRef.current = runKey;
    const tbody = tbodyRef.current;
    if (!tbody) return;

    tbody.classList.add("animate");
    const trs = tbody.querySelectorAll("tr");
    trs.forEach((tr, i) => {
      tr.style.animationDelay = `${i * 20}ms`;
      const pill = tr.querySelector(".pill");
      if (pill) pill.style.animationDelay = `${120 + i * 20}ms`;
    });

    const tid = setTimeout(() => {
      tbody.classList.remove("animate");
      trs.forEach((tr) => {
        tr.style.animationDelay = "";
        const pill = tr.querySelector(".pill");
        if (pill) pill.style.animationDelay = "";
      });
    }, 1500);
    return () => clearTimeout(tid);
  }, [runKey, rows]);

  return (
    <section className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Branch</th>
            <th>Customer Name</th>
            <th>Agent ID</th>
            <th>Policy No</th>
            <th>Type</th>
            <th>UTR</th>
            <th className="num">Excel Amount</th>
            <th className="num">Bank Amount</th>
            <th>Status</th>
            {!readOnly && <th className="num">Action</th>}
          </tr>
        </thead>
        <tbody ref={tbodyRef}>
          {rows.length === 0 ? (
            <tr className="empty">
              <td colSpan={colCount}>
                {runKey === 0
                  ? "UPLOAD FILES AND RUN RECONCILIATION TO BEGIN"
                  : "NO ROWS TO SHOW"}
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <Row
                key={r.id}
                row={r}
                onResolve={onResolve}
                onUnresolve={onUnresolve}
                onPendingClick={onPendingClick}
                readOnly={readOnly}
              />
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
