const TABS = [
  { id: "active",          label: "Active Issues" },
  { id: "pending",         label: "Pending / Excess" },
  { id: "resolved",        label: "Resolved" },
  { id: "branch_mismatch", label: "Branch Mismatches" },
  { id: "history",         label: "History" },
];

export default function Tabs({
  current,
  onChange,
  historyBadge = 0,
  pendingBadge = 0,
}) {
  return (
    <nav className="tabs">
      {TABS.map((t) => (
        <button
          key={t.id}
          className={`tab ${current === t.id ? "active" : ""}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
          {t.id === "history" && historyBadge > 0 && (
            <span className="tab-badge">{historyBadge}</span>
          )}
          {t.id === "pending" && pendingBadge > 0 && (
            <span className="tab-badge">{pendingBadge}</span>
          )}
        </button>
      ))}
    </nav>
  );
}
