import { useEffect, useRef, useState } from "react";

const CARDS = [
  { key: "total_excel",    label: "Total UTRs in Excel", color: "blue",   status: "" },
  { key: "matched",        label: "Matched",             color: "green",  status: "MATCHED" },
  { key: "mismatch",       label: "Amount Mismatch",     color: "amber",  status: "MISMATCH" },
  { key: "missing",        label: "Missing from Bank",   color: "red",    status: "MISSING" },
  { key: "unrecorded",     label: "Unrecorded in Bank",  color: "orange", status: "UNRECORDED" },
  { key: "canara_pending", label: "Canara Pending",      color: "slate",  status: "CANARA_PENDING" },
];

const EASE = (t) => 1 - Math.pow(1 - t, 3);
const DURATION = 550;

export default function Summary({ summary, activeStatus, onCardClick, runKey }) {
  const [displayed, setDisplayed] = useState(summary);
  const prevRef = useRef(summary);
  const lastKeyRef = useRef(runKey);

  useEffect(() => {
    const shouldAnimate = runKey !== lastKeyRef.current && runKey > 0;
    lastKeyRef.current = runKey;

    if (!shouldAnimate) {
      setDisplayed(summary);
      prevRef.current = summary;
      return;
    }

    const from = prevRef.current;
    const to = summary;
    const start = performance.now();
    let raf;

    const tick = (now) => {
      const t = Math.min(1, (now - start) / DURATION);
      const e = EASE(t);
      const lerp = (a, b) => Math.round(a + (b - a) * e);
      setDisplayed({
        total_excel:    lerp(from.total_excel    || 0, to.total_excel    || 0),
        matched:        lerp(from.matched        || 0, to.matched        || 0),
        mismatch:       lerp(from.mismatch       || 0, to.mismatch       || 0),
        missing:        lerp(from.missing        || 0, to.missing        || 0),
        unrecorded:     lerp(from.unrecorded     || 0, to.unrecorded     || 0),
        canara_pending: lerp(from.canara_pending || 0, to.canara_pending || 0),
      });
      if (t < 1) raf = requestAnimationFrame(tick);
      else prevRef.current = to;
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [summary, runKey]);

  return (
    <section className="summary">
      {CARDS.map((c) => (
        <div
          key={c.key}
          className={`metric metric-${c.color} ${activeStatus === c.status ? "active" : ""}`}
          data-status={c.status}
          onClick={() => onCardClick(c.status)}
        >
          <div className="metric-accent" />
          <div className="metric-body">
            <div className="metric-label">{c.label}</div>
            <div className="metric-value">{displayed[c.key]}</div>
          </div>
        </div>
      ))}
    </section>
  );
}
