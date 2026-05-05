import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api.js";
import { buildQuery } from "./helpers.js";

import BootScreen from "./components/BootScreen.jsx";
import TopBar from "./components/TopBar.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Summary from "./components/Summary.jsx";
import Tabs from "./components/Tabs.jsx";
import Filters from "./components/Filters.jsx";
import Table from "./components/Table.jsx";
import LedgerPanel from "./components/LedgerPanel.jsx";
import HistoryView from "./components/HistoryView.jsx";
import SetupOverlay from "./components/SetupOverlay.jsx";
import AddBranchModal from "./components/AddBranchModal.jsx";
import AllDoneBanner from "./components/AllDoneBanner.jsx";
import TallyModal from "./components/TallyModal.jsx";
import Toast from "./components/Toast.jsx";
import KannabranView from "./components/KannabranView.jsx";
import NandhakumarView from "./components/NandhakumarView.jsx";
import CashView from "./components/CashView.jsx";
import PipelineSwitch from "./components/PipelineSwitch.jsx";
import CrossCheckModal from "./components/CrossCheckModal.jsx";

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
  bank: "",
};

function detectRoute() {
  const p = window.location.pathname;
  if (p.startsWith("/kannabran")) return "kannabran";
  if (p.startsWith("/nandhakumar")) return "nandhakumar";
  return "main";
}

export default function App() {
  const route = detectRoute();

  // Read-only routes bypass the full Priya flow entirely.
  if (route === "kannabran") return <KannabranView />;
  if (route === "nandhakumar") return <NandhakumarView />;

  return <MainApp />;
}

function MainApp() {
  const [bootDone, setBootDone] = useState(false);
  const [config, setConfig] = useState(null);

  // Top-level toggle: "upi" = existing UTR pipeline, "cash" = new
  // amount+date pipeline (KVB/SBI/IOB + handwritten ledger CSV).
  const [pipeline, setPipeline] = useState("upi");
  const [crossCheckOpen, setCrossCheckOpen] = useState(false);

  const [tab, setTab] = useState("active");
  const [filters, setFilters] = useState(EMPTY_FILTERS);

  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [runKey, setRunKey] = useState(0);

  // Upload / setup state. canaraLibrary is a list of {date, filename,
  // credits, uploadedAt} sorted newest first.
  const [uploaded, setUploaded] = useState({
    canaraLibrary: [],
    branches: {},
  });
  const [setupDismissed, setSetupDismissed] = useState(false);
  const initialStateCheckedRef = useRef(false);

  const [addBranchOpen, setAddBranchOpen] = useState(false);
  const [tallyOpen, setTallyOpen] = useState(false);
  const [reconciling, setReconciling] = useState(false);

  // Historical flags summary — drives the tab badge and the HistoryView.
  const [historySummary, setHistorySummary] = useState({
    byDate: {},
    statementDates: [],
    totals: { open: 0, oldestDays: null, branches: 0, dates: 0 },
  });

  const refreshHistorySummary = useCallback(async () => {
    try {
      const d = await api.getFlagsSummary();
      setHistorySummary(d);
    } catch (_e) {
      /* swallow — history is non-critical */
    }
  }, []);

  // Ledger photos (browser memory, per branch)
  const [ledgerPhotos, setLedgerPhotos] = useState({});

  const [toast, setToast] = useState(null);

  // ----- toast auto-dismiss (4s per spec) -----
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const showToast = useCallback((msg, opts = {}) => {
    setToast({ msg, error: !!opts.error, tone: opts.tone || null });
  }, []);

  // ----- data fetcher -----
  const fetchData = useCallback(async () => {
    try {
      const d = await api.getData(buildQuery(tab, filters));
      setRows(d.rows);
      setSummary(d.summary);
    } catch (e) {
      showToast(e.message, { error: true });
    }
  }, [tab, filters, showToast]);

  // ----- state fetcher -----
  const refreshState = useCallback(async () => {
    try {
      const s = await api.getState();
      setUploaded({
        canaraLibrary: s.canaraLibrary || [],
        branches: Object.fromEntries(
          (s.branches || []).map((b) => [b.branch, b.filename])
        ),
      });
      return s;
    } catch (e) {
      showToast(e.message, { error: true });
      return { canaraLibrary: [], branches: [] };
    }
  }, [showToast]);

  // ----- boot: load config + initial state ----------
  useEffect(() => {
    if (!bootDone || initialStateCheckedRef.current) return;
    initialStateCheckedRef.current = true;

    (async () => {
      try {
        const c = await api.getConfig();
        setConfig(c);
      } catch (e) {
        showToast(`Config failed: ${e.message}`, { error: true });
        return;
      }
      const s = await refreshState();
      // If a Canara statement was already loaded before this session, skip
      // the setup overlay entirely — Priya doesn't need to see it on refresh.
      if (s && s.canaraLibrary && s.canaraLibrary.length > 0) {
        setSetupDismissed(true);
      }
      fetchData();
      refreshHistorySummary();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bootDone]);

  // Refetch whenever tab/filters change after initial load.
  useEffect(() => {
    if (!bootDone || !config) return;
    fetchData();
  }, [tab, filters, bootDone, config, fetchData]);

  // ----- filter helpers -----
  const setFilter = useCallback((key, value) => {
    setFilters((f) => ({ ...f, [key]: value }));
  }, []);

  const toggleStatusFilter = useCallback((status) => {
    setFilters((f) => ({ ...f, status: f.status === status ? "" : status }));
  }, []);

  const toggleBranchFilter = useCallback((branch) => {
    setFilters((f) => ({ ...f, branch: f.branch === branch ? "" : branch }));
  }, []);

  const toggleBankFilter = useCallback((bank) => {
    setFilters((f) => ({ ...f, bank: f.bank === bank ? "" : bank }));
  }, []);

  const handleClearDay = useCallback(async () => {
    const date = window.prompt(
      "Clear which day? Enter date as YYYY-MM-DD.\n\nThis removes ALL bank statements, history flags, and pending rows for that date — but keeps every other day intact."
    );
    if (!date) return;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date.trim())) {
      showToast("Date must be YYYY-MM-DD", { error: true });
      return;
    }
    if (
      !window.confirm(
        `Wipe everything for ${date.trim()}? Bank statements + history flags + pending rows.`
      )
    ) {
      return;
    }
    try {
      await api.resetDate(date.trim());
      // Re-run reconciliation so the current-run rows table regenerates
      // without this date's matched/mismatch/etc. rows (they'd otherwise
      // linger until the next manual reconcile).
      try {
        await api.reconcile();
      } catch {
        // Non-fatal — the delete succeeded, only the rebuild failed. User
        // can hit RECONCILE NOW manually.
      }
      showToast(`Cleared ${date.trim()} — reloading`);
      window.location.reload();
    } catch (e) {
      showToast(e.message, { error: true });
    }
  }, [showToast]);

  const handleDeleteStatement = useCallback(
    async (date, bankCode) => {
      try {
        await api.deleteBankStatement(date, bankCode);
        setUploaded((u) => {
          const nextBank = (u.bankLibrary || []).filter(
            (s) => !(s.date === date && (s.bankCode || "CANARA") === bankCode)
          );
          const nextCanara = nextBank.filter((s) => s.bankCode === "CANARA");
          return { ...u, bankLibrary: nextBank, canaraLibrary: nextCanara };
        });
        showToast(`Removed ${bankCode} statement for ${date}`);
      } catch (e) {
        showToast(e.message, { error: true });
      }
    },
    [showToast]
  );

  // ----- bank statement upload from setup overlay or sidebar library -----
  // `bankCode` defaults to CANARA so existing call sites keep working.
  const handleUploadCanara = useCallback(
    async (file, bankCode = "CANARA") => {
      try {
        const d = await api.uploadBankStatement(bankCode, file);
        const entry = {
          date: d.date,
          bankCode: d.bankCode || bankCode,
          filename: d.filename,
          credits: d.credits,
          uploadedAt: new Date().toISOString(),
        };
        setUploaded((u) => {
          // Unified library: one entry per (date, bankCode).
          const nextBank = (u.bankLibrary || []).filter(
            (s) => !(s.date === entry.date && s.bankCode === entry.bankCode)
          );
          nextBank.unshift(entry);
          nextBank.sort((a, b) => {
            const d = b.date.localeCompare(a.date);
            return d !== 0 ? d : a.bankCode.localeCompare(b.bankCode);
          });
          // Legacy shape the rest of the UI still reads.
          const nextCanara = nextBank.filter((s) => s.bankCode === "CANARA");
          return { ...u, bankLibrary: nextBank, canaraLibrary: nextCanara };
        });
        showToast(
          `${entry.bankCode} ${d.date} · ${d.credits || 0} UPI credits`
        );
        // Surface any integrity-check warnings (declared totals, balance
        // formula, empty file) so Priya can re-upload before reconciling.
        const warnings = d.integrity?.warnings;
        if (warnings && warnings.length) {
          showToast(`⚠ ${warnings[0]}`, { error: true });
        }
        return d;
      } catch (e) {
        showToast(e.message, { error: true });
        return null;
      }
    },
    [showToast]
  );

  // ----- branch upload (used by AddBranchModal step 2) -----
  const handleUploadBranch = useCallback(
    async (branch, file) => {
      if (!branch) {
        showToast("Select a branch first", { error: true });
        return null;
      }
      try {
        const d = await api.uploadBranch(branch, file);
        setUploaded((u) => ({
          ...u,
          branches: { ...u.branches, [branch]: d.filename },
        }));
        return d;
      } catch (e) {
        showToast(e.message, { error: true });
        return null;
      }
    },
    [showToast]
  );

  // ----- ledger photo upload (persistent, server-backed) -----
  const handleAddLedgerPhotos = useCallback(
    async (branch, files) => {
      const list = Array.isArray(files) ? files : [files];
      for (const f of list) {
        try {
          const data = await api.uploadLedgerPhoto(branch, f);
          setLedgerPhotos((prev) => ({
            ...prev,
            [branch]: [...(prev[branch] || []), data],
          }));
        } catch (e) {
          showToast(e.message, { error: true });
        }
      }
    },
    [showToast]
  );

  // Lazy-load a branch's ledger photos the first time Priya selects it. The
  // `undefined` sentinel in ledgerPhotos means "never fetched"; an empty
  // array means "fetched, no photos on disk".
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
        /* ledger is non-critical; swallow */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filters.branch, ledgerPhotos]);

  // ----- reconciliation run (from AddBranchModal step 3) -----
  const runReconciliation = useCallback(
    async (branchName) => {
      try {
        const d = await api.reconcile();
        if (!d.ok) throw new Error(d.error || "Reconciliation failed");

        setRunKey((k) => k + 1);

        // Fetch fresh rows + compute per-branch counts so the toast can say
        // "X matched, Y flagged" for the branch Priya just added.
        const all = await api.getData(buildQuery("active", { branch: branchName }));
        setRows(all.rows);
        setSummary(all.summary);

        const counts = all.rows.reduce(
          (acc, r) => {
            if (r.status === "MATCHED") acc.matched += 1;
            else if (r.status === "MISMATCH" || r.status === "MISSING") acc.flagged += 1;
            return acc;
          },
          { matched: 0, flagged: 0 }
        );

        showToast(
          `${branchName} reconciliation complete · ${counts.matched} matched, ${counts.flagged} flagged`,
          { tone: "success" }
        );

        setAddBranchOpen(false);
        // Jump the sidebar filter to this branch so Priya lands on her just-
        // finished work with the ledger panel open.
        setFilters((f) => ({ ...f, branch: branchName }));
        refreshHistorySummary();
      } catch (e) {
        showToast(e.message, { error: true });
      }
    },
    [showToast]
  );

  const handleResolve = useCallback(
    async (id) => {
      try {
        await api.resolve(id);
        showToast("Row marked resolved");
        await fetchData();
      } catch (e) {
        showToast(e.message, { error: true });
      }
    },
    [fetchData, showToast]
  );

  const handleUnresolve = useCallback(
    async (id) => {
      try {
        await api.unresolve(id);
        showToast("Row unresolved");
        await fetchData();
      } catch (e) {
        showToast(e.message, { error: true });
      }
    },
    [fetchData, showToast]
  );

  // Standalone rerun — used when Priya adds a historical Canara via the
  // sidebar, or when she wants to re-apply after editing resolve state.
  // Respects the current filter view so her on-screen context isn't reset.
  const handleRunReconciliationStandalone = useCallback(async () => {
    setReconciling(true);
    try {
      const d = await api.reconcile();
      if (!d.ok) throw new Error(d.error || "Reconciliation failed");

      // Refetch data using Priya's current tab + filters so her view
      // doesn't jump. The summary in the response is always branch-
      // agnostic (see _summary_counts in app.py), so the toast reports
      // across-all-branches counts even when she has a branch filter on.
      const data = await api.getData(buildQuery(tab, filters));
      setRows(data.rows);
      setSummary(data.summary);
      setRunKey((k) => k + 1);

      // "Flagged" = rows needing Priya's attention (mismatch + missing +
      // unrecorded). Canara Pending is a waiting state, not a flag, so
      // it's excluded — it'd muddy the signal when she's processing late
      // entries that legitimately have no matching statement yet.
      const matched = data.summary.matched || 0;
      const flagged =
        (data.summary.mismatch || 0) +
        (data.summary.missing || 0) +
        (data.summary.unrecorded || 0);

      showToast(
        `Reconciliation updated \u00B7 ${matched} matched, ${flagged} flagged across all branches`
      );
      refreshHistorySummary();
    } catch (e) {
      showToast(e.message, { error: true });
    } finally {
      setReconciling(false);
    }
  }, [tab, filters, showToast, refreshHistorySummary]);

  const handleExport = useCallback(() => {
    window.location = api.exportUrl(buildQuery(tab, filters));
  }, [tab, filters]);

  const handlePendingClick = useCallback(
    (pendingDate) => {
      if (pendingDate) {
        showToast(
          `Upload Canara statement for ${pendingDate} to reconcile this entry`
        );
      } else {
        showToast(
          "This row has no Amount Received Date — fix the branch Excel",
          { error: true }
        );
      }
    },
    [showToast]
  );

  const handleExportFull = useCallback(() => {
    window.location = api.exportFullUrl();
  }, []);

  const handleExportComprehensive = useCallback(() => {
    window.location = api.reportComprehensiveUrl();
  }, []);

  // ----- derived flags -----
  const uploadedBranchCount = Object.keys(uploaded.branches).length;
  const allBranchesUploaded =
    config && uploadedBranchCount >= config.branchCount;
  const libraryCount =
    (uploaded.bankLibrary || uploaded.canaraLibrary || []).length;
  // The overlay is onboarding — show it only when there is literally
  // nothing uploaded. Once the library has any statement, the top-bar
  // pills handle upload + filter, so the overlay would just be noise.
  const showSetup = !setupDismissed && libraryCount === 0;

  const currentBranchName = filters.branch;
  const branchPhotos = useMemo(
    () => (currentBranchName ? ledgerPhotos[currentBranchName] || [] : []),
    [currentBranchName, ledgerPhotos]
  );

  // ----- render -----
  if (!bootDone) return <BootScreen onDone={() => setBootDone(true)} />;
  if (!config) return <div className="app" />;

  return (
    <>
      <div className="app ready">
        <TopBar
          today={config.today}
          canaraLibrary={uploaded.canaraLibrary}
          bankLibrary={uploaded.bankLibrary || []}
          banks={config.banks || []}
          activeBank={filters.bank}
          onBankClick={toggleBankFilter}
          onBankUpload={handleUploadCanara}
          branchesUploaded={uploadedBranchCount}
          branchTotal={config.branchCount}
          allDone={allBranchesUploaded}
          onAddBranch={() => setAddBranchOpen(true)}
          onTally={() => setTallyOpen(true)}
          onReconcile={handleRunReconciliationStandalone}
          reconciling={reconciling}
          onClearDay={handleClearDay}
        />

        {allBranchesUploaded && (
          <AllDoneBanner
            total={config.branchCount}
            onExport={handleExportFull}
            onExportComprehensive={handleExportComprehensive}
          />
        )}

        <div className="shell">
          <Sidebar
            branches={config.branches}
            branchTotal={config.branchCount}
            uploadedBranches={uploaded.branches}
            activeBranch={filters.branch}
            onBranchClick={toggleBranchFilter}
            canaraLibrary={uploaded.canaraLibrary}
            bankLibrary={uploaded.bankLibrary}
            onDeleteStatement={handleDeleteStatement}
          />

          <main className="content">
            <div style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "8px 18px 0",
            }}>
              <PipelineSwitch value={pipeline} onChange={setPipeline} />
              {pipeline === "cash" && (
                <span style={{ fontSize: 11, color: "#888" }}>
                  Cash pipeline · KVB / SBI / IOB ↔ handwritten ledger
                </span>
              )}
              <div style={{ flex: 1 }} />
              <button
                onClick={() => setCrossCheckOpen(true)}
                title="Find payments booked twice (once as UPI, once as cash)"
                style={{
                  background: "#fff", border: "1px solid #c99",
                  color: "#9a1f1f", padding: "4px 12px", borderRadius: 4,
                  cursor: "pointer", fontSize: 12, fontWeight: 600,
                }}
              >
                Cross-check duplicates
              </button>
            </div>

            {pipeline === "cash" ? (
              <CashView banks={config.banks || []} showToast={showToast} />
            ) : (
              <UpiPipelineMain
                tab={tab}
                setTab={setTab}
                filters={filters}
                setFilter={setFilter}
                summary={summary}
                rows={rows}
                runKey={runKey}
                config={config}
                historySummary={historySummary}
                refreshHistorySummary={refreshHistorySummary}
                handleUploadCanara={handleUploadCanara}
                handleRunReconciliation={handleRunReconciliationStandalone}
                handleResolve={handleResolve}
                handleUnresolve={handleUnresolve}
                handleExport={handleExport}
                handlePendingClick={handlePendingClick}
                showToast={showToast}
                toggleStatusFilter={toggleStatusFilter}
                branchPhotos={branchPhotos}
                handleAddLedgerPhotos={handleAddLedgerPhotos}
              />
            )}
          </main>
        </div>
      </div>

      {showSetup && (
        <SetupOverlay
          today={config.today}
          uploaded={uploaded}
          banks={config.banks || []}
          onUpload={handleUploadCanara}
          onContinue={() => {
            setSetupDismissed(true);
            fetchData();
          }}
        />
      )}

      {addBranchOpen && !showSetup && (
        <AddBranchModal
          branches={config.branches}
          uploadedBranches={uploaded.branches}
          canaraFilename={uploaded.canara}
          onClose={() => setAddBranchOpen(false)}
          onUploadBranch={handleUploadBranch}
          onUploadLedger={(branch, file) =>
            handleAddLedgerPhotos(branch, [file])
          }
          onRun={runReconciliation}
        />
      )}

      {tallyOpen && (
        <TallyModal
          onClose={() => setTallyOpen(false)}
          onExportFull={handleExportFull}
        />
      )}

      {crossCheckOpen && (
        <CrossCheckModal
          onClose={() => setCrossCheckOpen(false)}
          showToast={showToast}
        />
      )}

      {toast && <Toast msg={toast.msg} error={toast.error} />}
    </>
  );
}

/**
 * The original UPI dashboard body, factored out so the App.jsx render
 * tree can switch cleanly between pipelines without nesting another
 * level of conditional. Behaviour is unchanged from the inline version.
 */
function UpiPipelineMain({
  tab,
  setTab,
  filters,
  setFilter,
  summary,
  rows,
  runKey,
  config,
  historySummary,
  refreshHistorySummary,
  handleUploadCanara,
  handleRunReconciliation,
  handleResolve,
  handleUnresolve,
  handleExport,
  handlePendingClick,
  showToast,
  toggleStatusFilter,
  branchPhotos,
  handleAddLedgerPhotos,
}) {
  return (
    <>
      {tab !== "history" && (
        <Summary
          summary={summary}
          activeStatus={filters.status}
          onCardClick={toggleStatusFilter}
          runKey={runKey}
        />
      )}
      <Tabs
        current={tab}
        onChange={setTab}
        historyBadge={historySummary?.totals?.open || 0}
        pendingBadge={
          (summary?.canara_pending || 0) + (summary?.unrecorded || 0)
        }
      />
      {tab === "history" ? (
        <HistoryView
          branches={config.branches}
          summary={historySummary}
          onRefreshSummary={refreshHistorySummary}
          onUploadCanara={handleUploadCanara}
          onRunReconciliation={handleRunReconciliation}
          showToast={showToast}
        />
      ) : (
        <>
          <Filters
            filters={filters}
            setFilter={setFilter}
            onExport={handleExport}
            branches={config.branches}
          />
          {filters.branch ? (
            <div className="table-with-ledger">
              <Table
                rows={rows}
                runKey={runKey}
                onResolve={handleResolve}
                onUnresolve={handleUnresolve}
                onPendingClick={handlePendingClick}
              />
              <LedgerPanel
                key={filters.branch}
                branch={filters.branch}
                photos={branchPhotos}
                onUpload={(files) =>
                  handleAddLedgerPhotos(filters.branch, files)
                }
              />
            </div>
          ) : (
            <Table
              rows={rows}
              runKey={runKey}
              onResolve={handleResolve}
              onUnresolve={handleUnresolve}
              onPendingClick={handlePendingClick}
            />
          )}
        </>
      )}
    </>
  );
}
