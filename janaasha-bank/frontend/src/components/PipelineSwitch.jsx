/**
 * Top-level toggle that picks which reconciliation pipeline the user
 * is looking at: UPI (existing UTR-based, Canara + branch Excel) or
 * Cash (new amount+date-based, KVB/SBI/IOB + handwritten ledger CSV).
 *
 * Visually a 2-segment switch — keeps the rest of the dashboard layout
 * untouched, just swaps the main content area.
 */
export default function PipelineSwitch({ value, onChange }) {
  const options = [
    { id: "upi",  label: "UPI",  hint: "Canara + branch Excel · match by UTR" },
    { id: "cash", label: "Cash", hint: "KVB / SBI / IOB + ledger CSV · match by amount + date" },
  ];

  return (
    <div
      style={{
        display: "inline-flex",
        background: "#ededed",
        borderRadius: 16,
        padding: 3,
        gap: 2,
        fontSize: 12,
        fontWeight: 600,
      }}
      role="tablist"
      aria-label="Pipeline"
    >
      {options.map((o) => {
        const active = value === o.id;
        return (
          <button
            key={o.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.id)}
            title={o.hint}
            style={{
              padding: "5px 14px",
              borderRadius: 13,
              border: 0,
              background: active ? "#5c4a00" : "transparent",
              color: active ? "#fff" : "#666",
              cursor: "pointer",
              transition: "background 120ms",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
