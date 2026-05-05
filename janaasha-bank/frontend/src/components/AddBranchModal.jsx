import { useEffect, useRef, useState } from "react";

const STEPS = [
  { id: 1, label: "Select Branch" },
  { id: 2, label: "Upload Files" },
  { id: 3, label: "Review & Run" },
];

function useDropZone(zoneRef, inputRef) {
  useEffect(() => {
    const el = zoneRef.current;
    const input = inputRef.current;
    if (!el || !input) return;
    const onOver = (e) => {
      e.preventDefault();
      el.classList.add("dragover");
    };
    const onLeave = () => el.classList.remove("dragover");
    const onDrop = (e) => {
      e.preventDefault();
      el.classList.remove("dragover");
      const f = e.dataTransfer.files[0];
      if (!f) return;
      const dt = new DataTransfer();
      dt.items.add(f);
      input.files = dt.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
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
  }, [zoneRef, inputRef]);
}

export default function AddBranchModal({
  branches,
  uploadedBranches,
  canaraFilename,
  onClose,
  onUploadBranch,
  onUploadLedger,
  onRun,
}) {
  const [step, setStep] = useState(1);
  const [selectedBranch, setSelectedBranch] = useState("");
  const [branchFileInfo, setBranchFileInfo] = useState(null); // { filename, rowCount }
  const [ledgerFileInfo, setLedgerFileInfo] = useState(null); // { filename }
  const [busy, setBusy] = useState(false);

  const branchInputRef = useRef(null);
  const ledgerInputRef = useRef(null);
  const branchZoneRef = useRef(null);
  const ledgerZoneRef = useRef(null);

  useDropZone(branchZoneRef, branchInputRef);
  useDropZone(ledgerZoneRef, ledgerInputRef);

  const uploadedSet = new Set(Object.keys(uploadedBranches));

  const goNext = () => setStep((s) => Math.min(3, s + 1));
  const goBack = () => setStep((s) => Math.max(1, s - 1));

  const nextDisabled =
    (step === 1 && !selectedBranch) || (step === 2 && !branchFileInfo);

  const handleBranchFile = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    setBusy(true);
    try {
      const result = await onUploadBranch(selectedBranch, f);
      if (result) {
        setBranchFileInfo({
          filename: result.filename,
          rowCount: result.rowCount,
        });
      }
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  const handleLedgerFile = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    // Ledger photos are in-browser-memory only — no API call, just remember
    // the File so we can display the filename in the review step. We also
    // forward it to the parent so the LedgerPanel state is updated.
    setLedgerFileInfo({ filename: f.name });
    if (onUploadLedger) onUploadLedger(selectedBranch, f);
    e.target.value = "";
  };

  const skipLedger = () => setLedgerFileInfo({ filename: "" });

  const handleRun = async () => {
    setBusy(true);
    try {
      await onRun(selectedBranch);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal add-branch-modal">
        <div className="modal-top-border" />

        <div className="modal-head">
          <h2>Add Branch</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        <div className="step-indicator">
          {STEPS.map((s, i) => (
            <div
              key={s.id}
              className={`step-pip ${
                step === s.id
                  ? "active"
                  : step > s.id
                  ? "done"
                  : ""
              }`}
            >
              <span className="step-pip-num">STEP {s.id}</span>
              <span className="step-pip-label">{s.label}</span>
              {i < STEPS.length - 1 && <span className="step-pip-sep" />}
            </div>
          ))}
        </div>

        {step === 1 && (
          <div className="step-body">
            <div className="step-title">Which branch are you adding?</div>
            <div className="step-sub">
              Pick a new branch, or re-select an already-uploaded one to
              replace its file (for late corrections).
            </div>
            <select
              className="big-select"
              value={selectedBranch}
              onChange={(e) => setSelectedBranch(e.target.value)}
            >
              <option value="">Select branch</option>
              {branches.map((b) => {
                const done = uploadedSet.has(b.name);
                return (
                  <option key={b.code} value={b.name}>
                    {b.code} &middot; {b.name}
                    {done ? "   \u2014  Previously uploaded \u2014 will replace" : ""}
                  </option>
                );
              })}
            </select>
            {selectedBranch && uploadedSet.has(selectedBranch) && (
              <div className="step-replace-note">
                <span className="step-replace-icon">&#8635;</span>
                This will replace the existing file for{" "}
                <strong>{selectedBranch}</strong>. Previous ledger photos are
                preserved.
              </div>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="step-body">
            <div className="step-title">
              Upload files for <strong>{selectedBranch}</strong>
            </div>
            <div className="step-sub">
              Excel is required. Ledger photo is optional.
            </div>

            <div className="add-branch-zones">
              <div className="zone-col">
                <div className="zone-col-label">
                  <span>Branch Excel (.xls)</span>
                  <span className="muted-chip">required</span>
                </div>
                <label
                  className={`drop-zone ${branchFileInfo ? "done" : ""}`}
                  ref={branchZoneRef}
                >
                  <input
                    type="file"
                    accept=".xls,.xlsx"
                    hidden
                    ref={branchInputRef}
                    onChange={handleBranchFile}
                    disabled={busy}
                  />
                  <div className="drop-inner">
                    <div className="drop-text">
                      {branchFileInfo
                        ? branchFileInfo.filename
                        : "CHOOSE FILE OR DROP HERE"}
                    </div>
                    {branchFileInfo
                      ? branchFileInfo.rowCount !== null &&
                        branchFileInfo.rowCount !== undefined && (
                          <div className="drop-meta">
                            {branchFileInfo.rowCount} rows detected
                          </div>
                        )
                      : <div className="drop-meta">.xls / .xlsx</div>}
                  </div>
                </label>
              </div>

              <div className="zone-col">
                <div className="zone-col-label">
                  <span>Ledger Photo (jpg/png)</span>
                  <span className="muted-chip">optional</span>
                </div>
                <label
                  className={`drop-zone ${ledgerFileInfo?.filename ? "done" : ""}`}
                  ref={ledgerZoneRef}
                >
                  <input
                    type="file"
                    accept="image/jpeg,image/png"
                    hidden
                    ref={ledgerInputRef}
                    onChange={handleLedgerFile}
                  />
                  <div className="drop-inner">
                    <div className="drop-text">
                      {ledgerFileInfo?.filename ||
                        "CHOOSE FILE OR DROP HERE"}
                    </div>
                    <div className="drop-meta">jpg &middot; png</div>
                  </div>
                </label>
                {!ledgerFileInfo && (
                  <button
                    type="button"
                    className="link-btn"
                    onClick={skipLedger}
                  >
                    Skip for now
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="step-body">
            <div className="step-title">Review</div>
            <div className="step-sub">
              Confirm before running reconciliation for this branch.
            </div>
            <dl className="review-list">
              <div className="review-row">
                <dt>Branch</dt>
                <dd>{selectedBranch}</dd>
              </div>
              <div className="review-row">
                <dt>Branch Excel</dt>
                <dd>
                  {branchFileInfo?.filename}
                  {typeof branchFileInfo?.rowCount === "number" && (
                    <span className="review-meta">
                      {" "}
                      &middot; {branchFileInfo.rowCount} rows detected
                    </span>
                  )}
                </dd>
              </div>
              <div className="review-row">
                <dt>Ledger photo</dt>
                <dd>
                  {ledgerFileInfo?.filename ? (
                    ledgerFileInfo.filename
                  ) : (
                    <span className="muted">Not uploaded</span>
                  )}
                </dd>
              </div>
              <div className="review-row">
                <dt>Canara statement</dt>
                <dd>
                  {canaraFilename}
                  <span className="review-meta"> &middot; already loaded</span>
                </dd>
              </div>
            </dl>
          </div>
        )}

        <div className="modal-actions add-branch-actions">
          {step > 1 && (
            <button
              type="button"
              className="btn-ghost"
              onClick={goBack}
              disabled={busy}
            >
              Back
            </button>
          )}
          <div className="spacer" />
          {step < 3 && (
            <button
              type="button"
              className="btn-gold"
              onClick={goNext}
              disabled={nextDisabled || busy}
            >
              Next
            </button>
          )}
          {step === 3 && (
            <button
              type="button"
              className="btn-gold full"
              onClick={handleRun}
              disabled={busy}
            >
              {busy
                ? "RUNNING..."
                : `RUN RECONCILIATION FOR ${selectedBranch.toUpperCase()}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
