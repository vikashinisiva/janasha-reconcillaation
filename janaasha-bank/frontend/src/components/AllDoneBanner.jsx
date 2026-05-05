export default function AllDoneBanner({ total, onExport, onExportComprehensive }) {
  return (
    <div className="all-done-banner">
      <div className="all-done-text">
        <span className="all-done-icon">&#10003;</span>
        Today&rsquo;s reconciliation is complete. {total} of {total} branches
        processed.
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn-gold" onClick={onExport}>
          Export Full Report
        </button>
        {onExportComprehensive && (
          <button
            className="btn-gold-outline"
            onClick={onExportComprehensive}
            title="Multi-sheet audit report: summary, per-bank, per-branch, daily, charges, and historical flags"
          >
            Comprehensive Report
          </button>
        )}
      </div>
    </div>
  );
}
