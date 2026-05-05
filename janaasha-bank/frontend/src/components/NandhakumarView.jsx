import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

import TopBar from "./TopBar.jsx";
import Summary from "./Summary.jsx";
import TallyModal from "./TallyModal.jsx";

const EMPTY_SUMMARY = {
  total_excel: 0,
  matched: 0,
  mismatch: 0,
  missing: 0,
  unrecorded: 0,
  canara_pending: 0,
};

// "Flagged" lumps together everything that isn't a clean match.
const FLAGGED_STATUSES = new Set(["MISMATCH", "MISSING", "UNRECORDED"]);

export default function NandhakumarView() {
  const [config, setConfig] = useState(null);
  const [uploaded, setUploaded] = useState({ canaraLibrary: [], branches: {} });
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [tallyOpen, setTallyOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [c, s, d] = await Promise.all([
          api.getConfig(),
          api.getState(),
          api.getData("tab=active"),
        ]);
        setConfig(c);
        setUploaded({
          canaraLibrary: s.canaraLibrary || [],
          branches: Object.fromEntries(
            (s.branches || []).map((b) => [b.branch, b.filename])
          ),
        });
        setRows(d.rows);
        setSummary(d.summary);
      } catch (_e) {}
    })();
  }, []);

  // Aggregate active-tab rows by branch for the breakdown table.
  const breakdown = useMemo(() => {
    if (!config) return [];
    const uploadedSet = new Set(Object.keys(uploaded.branches));
    const byBranch = new Map();

    for (const r of rows) {
      const name = r.branch || "(Unassigned)";
      if (!byBranch.has(name)) {
        byBranch.set(name, { total: 0, matched: 0, flagged: 0 });
      }
      const entry = byBranch.get(name);
      entry.total += 1;
      if (r.status === "MATCHED") entry.matched += 1;
      else if (FLAGGED_STATUSES.has(r.status)) entry.flagged += 1;
    }

    return config.branches.map((b) => {
      const stats = byBranch.get(b.name) || {
        total: 0,
        matched: 0,
        flagged: 0,
      };
      return {
        code: b.code,
        name: b.name,
        uploaded: uploadedSet.has(b.name),
        total: stats.total,
        matched: stats.matched,
        flagged: stats.flagged,
      };
    });
  }, [rows, uploaded.branches, config]);

  if (!config) return <div className="app" />;

  return (
    <div className="app ready">
      <TopBar
        today={config.today}
        canaraLibrary={uploaded.canaraLibrary}
        readOnly
        roleLabel="READ-ONLY · NANDHAKUMAR"
        onTally={() => setTallyOpen(true)}
      />
      <main className="content nandha-content">
        <Summary
          summary={summary}
          activeStatus=""
          onCardClick={() => {}}
          runKey={0}
        />
        <section className="branch-breakdown">
          <div className="breakdown-head">BRANCH BREAKDOWN</div>
          <table className="breakdown-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Branch</th>
                <th className="num">Total UTRs</th>
                <th className="num">Matched</th>
                <th className="num">Flagged</th>
                <th>Upload</th>
              </tr>
            </thead>
            <tbody>
              {breakdown.map((b) => (
                <tr key={b.code}>
                  <td className="mono">{b.code}</td>
                  <td>{b.name}</td>
                  <td className="num">{b.total}</td>
                  <td className="num">{b.matched}</td>
                  <td className="num">{b.flagged}</td>
                  <td>
                    {b.uploaded ? (
                      <span className="upload-pill uploaded">Uploaded</span>
                    ) : (
                      <span className="upload-pill pending">Pending</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>

      {tallyOpen && <TallyModal onClose={() => setTallyOpen(false)} />}
    </div>
  );
}
