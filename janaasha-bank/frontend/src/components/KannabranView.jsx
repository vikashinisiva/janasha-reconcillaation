import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { buildQuery } from "../helpers.js";

import TopBar from "./TopBar.jsx";
import Sidebar from "./Sidebar.jsx";
import Summary from "./Summary.jsx";
import Tabs from "./Tabs.jsx";
import Filters from "./Filters.jsx";
import Table from "./Table.jsx";
import LedgerPanel from "./LedgerPanel.jsx";
import TallyModal from "./TallyModal.jsx";

const EMPTY_SUMMARY = {
  total_excel: 0,
  matched: 0,
  mismatch: 0,
  missing: 0,
  unrecorded: 0,
  canara_pending: 0,
};

const EMPTY_FILTERS = {
  branch: "",
  policy_type: "",
  status: "",
  search: "",
};

export default function KannabranView() {
  const [config, setConfig] = useState(null);
  const [uploaded, setUploaded] = useState({ canaraLibrary: [], branches: {} });
  const [tab, setTab] = useState("active");
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [ledgerPhotos, setLedgerPhotos] = useState({});
  const [tallyOpen, setTallyOpen] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const d = await api.getData(buildQuery(tab, filters));
      setRows(d.rows);
      setSummary(d.summary);
    } catch (_e) {
      // read-only view: swallow, show empty state
    }
  }, [tab, filters]);

  useEffect(() => {
    (async () => {
      try {
        const [c, s] = await Promise.all([api.getConfig(), api.getState()]);
        setConfig(c);
        setUploaded({
          canaraLibrary: s.canaraLibrary || [],
          branches: Object.fromEntries(
            (s.branches || []).map((b) => [b.branch, b.filename])
          ),
        });
      } catch (_e) {}
    })();
  }, []);

  useEffect(() => {
    if (config) fetchData();
  }, [config, fetchData]);

  // Lazy-fetch a branch's ledger photos when it's selected in the sidebar.
  useEffect(() => {
    const branch = filters.branch;
    if (!branch) return;
    if (ledgerPhotos[branch] !== undefined) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api.listLedger(branch);
        if (cancelled) return;
        setLedgerPhotos((prev) => ({ ...prev, [branch]: data.photos || [] }));
      } catch (_e) {
        /* swallow */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filters.branch, ledgerPhotos]);

  const setFilter = useCallback((key, value) => {
    setFilters((f) => ({ ...f, [key]: value }));
  }, []);

  const toggleStatusFilter = useCallback((status) => {
    setFilters((f) => ({ ...f, status: f.status === status ? "" : status }));
  }, []);

  const toggleBranchFilter = useCallback((branch) => {
    setFilters((f) => ({ ...f, branch: f.branch === branch ? "" : branch }));
  }, []);

  if (!config) return <div className="app" />;

  return (
    <div className="app ready">
      <TopBar
        today={config.today}
        canaraLibrary={uploaded.canaraLibrary}
        readOnly
        roleLabel="READ-ONLY · KANNABRAN"
        onTally={() => setTallyOpen(true)}
      />
      <div className="shell">
        <Sidebar
          branches={config.branches}
          branchTotal={config.branchCount}
          uploadedBranches={uploaded.branches}
          activeBranch={filters.branch}
          onBranchClick={toggleBranchFilter}
          canaraLibrary={uploaded.canaraLibrary}
        />
        <main className="content">
          <Summary
            summary={summary}
            activeStatus={filters.status}
            onCardClick={toggleStatusFilter}
            runKey={0}
          />
          <Tabs current={tab} onChange={setTab} />
          <Filters
            filters={filters}
            setFilter={setFilter}
            onExport={() => {
              window.location = api.exportUrl(buildQuery(tab, filters));
            }}
            branches={config.branches}
          />
          {filters.branch ? (
            <div className="table-with-ledger">
              <Table rows={rows} runKey={0} readOnly />
              <LedgerPanel
                key={filters.branch}
                branch={filters.branch}
                photos={ledgerPhotos[filters.branch] || []}
                onUpload={() => {}}
                readOnly
              />
            </div>
          ) : (
            <Table rows={rows} runKey={0} readOnly />
          )}
        </main>
      </div>

      {tallyOpen && <TallyModal onClose={() => setTallyOpen(false)} />}
    </div>
  );
}
