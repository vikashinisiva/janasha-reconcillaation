import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtAmount } from "../helpers.js";

const TOLERANCE = 0.01;

function money(v) {
  if (v === null || v === undefined) return "\u2014";
  const sign = v < 0 ? "\u2212\u2009" : "";
  return `${sign}\u20B9${fmtAmount(Math.abs(v))}`;
}

export default function TallyModal({ onClose, onExportFull }) {
  const [tally, setTally] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.getTally();
        if (!cancelled) setTally(d);
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const balanced = tally && Math.abs(tally.difference) <= TOLERANCE;
  const status = !tally
    ? "loading"
    : balanced
    ? "balanced"
    : tally.difference > 0
    ? "excess"
    : "deficit";

  const statusCopy = {
    balanced: {
      title: "BALANCED",
      note: "Money received in Canara matches what the branches recorded.",
    },
    excess: {
      title: "UNRECORDED EXCESS",
      note: "Canara received more than the branches have recorded. Check the UNRECORDED category.",
    },
    deficit: {
      title: "RECORDED DEFICIT",
      note: "Branches recorded more than arrived in Canara. Check the MISSING FROM BANK category.",
    },
  };

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal tally-modal">
        <div className="modal-top-border" />

        <div className="modal-head">
          <h2>End of Day Tally</h2>
          <button className="close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        {error && <div className="tally-error">{error}</div>}

        {!tally && !error && (
          <div className="tally-loading">Calculating&hellip;</div>
        )}

        {tally && (
          <>
            <div className="tally-totals">
              <div className="tally-side">
                <div className="tally-side-label">Canara Bank Deposits</div>
                <div className="tally-side-value">
                  {money(tally.canaraTotal)}
                </div>
                <div className="tally-side-sub">
                  {tally.matchedCount +
                    tally.mismatch.count +
                    tally.unrecorded.count}{" "}
                  UPI credits
                </div>
              </div>

              <div className="tally-vs">vs</div>

              <div className="tally-side">
                <div className="tally-side-label">Branch Records</div>
                <div className="tally-side-value">
                  {money(tally.branchesTotal)}
                </div>
                <div className="tally-side-sub">
                  {tally.matchedCount +
                    tally.mismatch.count +
                    tally.missing.count}{" "}
                  entries
                </div>
              </div>
            </div>

            <div className={`tally-diff tally-${status}`}>
              <div className="tally-diff-head">
                <span className="tally-diff-dot" />
                <span>{statusCopy[status].title}</span>
              </div>
              <div className="tally-diff-value">{money(tally.difference)}</div>
              <div className="tally-diff-note">{statusCopy[status].note}</div>
            </div>

            <div className="tally-breakdown">
              <div className="tally-bd-head">Breakdown</div>

              <div className="tally-bd-row">
                <span className="tally-bd-pip bd-green">&#10003;</span>
                <span className="tally-bd-label">Matched cleanly</span>
                <span className="tally-bd-count">{tally.matchedCount}</span>
                <span className="tally-bd-amount">
                  {money(tally.matchedTotal)}
                </span>
              </div>

              <div className="tally-bd-row">
                <span className="tally-bd-pip bd-amber">&ne;</span>
                <span className="tally-bd-label">Amount mismatch</span>
                <span className="tally-bd-count">{tally.mismatch.count}</span>
                <span className="tally-bd-amount">
                  {money(tally.mismatch.excelTotal)}
                  <span className="tally-bd-sep">vs</span>
                  {money(tally.mismatch.bankTotal)}
                </span>
              </div>

              <div className="tally-bd-row">
                <span className="tally-bd-pip bd-red">&minus;</span>
                <span className="tally-bd-label">Missing from bank</span>
                <span className="tally-bd-count">{tally.missing.count}</span>
                <span className="tally-bd-amount">
                  {money(tally.missing.total)}
                </span>
              </div>

              <div className="tally-bd-row">
                <span className="tally-bd-pip bd-orange">+</span>
                <span className="tally-bd-label">Unrecorded in bank</span>
                <span className="tally-bd-count">{tally.unrecorded.count}</span>
                <span className="tally-bd-amount">
                  {money(tally.unrecorded.total)}
                </span>
              </div>
            </div>

            {tally.canaraPending && tally.canaraPending.count > 0 && (
              <div className="tally-pending-note">
                <span className="tally-pending-icon">&#8635;</span>
                <span>
                  {tally.canaraPending.count}{" "}
                  {tally.canaraPending.count === 1 ? "entry" : "entries"}{" "}
                  awaiting historical Canara statement upload ({money(tally.canaraPending.total)}).
                  Not included in the totals above.
                </span>
              </div>
            )}

            {onExportFull && (
              <div className="modal-actions tally-actions">
                <button className="btn-ghost" onClick={onClose}>
                  Close
                </button>
                <div className="spacer" />
                <button className="btn-gold" onClick={onExportFull}>
                  Export Full Report
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
