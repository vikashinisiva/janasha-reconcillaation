import { useMemo, useState } from "react";

const WEEKDAY_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTH_LABELS = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December",
];

function dateKey(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function colorFor(key, byDate, statementSet) {
  const stats = byDate[key];
  if (stats && stats.open > 0) return "red";
  if (stats && stats.resolved > 0) return "amber";
  if (statementSet.has(key)) return "green";
  return "gray";
}

export default function CalendarHeatmap({
  byDate = {},
  statementDates = [],
  selectedDate,
  onSelect,
}) {
  const statementSet = useMemo(
    () => new Set(statementDates),
    [statementDates]
  );

  const today = useMemo(() => {
    const t = new Date();
    t.setHours(0, 0, 0, 0);
    return t;
  }, []);
  const todayKey = dateKey(today);

  // Default to the month that contains the currently selected date;
  // otherwise the current month.
  const initial = useMemo(() => {
    if (selectedDate) {
      const [y, m] = selectedDate.split("-").map(Number);
      if (y && m) return { year: y, month: m - 1 };
    }
    return { year: today.getFullYear(), month: today.getMonth() };
  }, [selectedDate, today]);

  const [view, setView] = useState(initial);

  const shift = (n) => {
    setView((v) => {
      let m = v.month + n;
      let y = v.year;
      if (m > 11) { m = 0; y += 1; }
      if (m < 0)  { m = 11; y -= 1; }
      return { year: y, month: m };
    });
  };

  const jumpToday = () =>
    setView({ year: today.getFullYear(), month: today.getMonth() });

  // Build the grid for the current view month.
  const cells = useMemo(() => {
    const first = new Date(view.year, view.month, 1);
    const daysInMonth = new Date(view.year, view.month + 1, 0).getDate();
    const startDow = first.getDay();
    const out = [];
    for (let i = 0; i < startDow; i++) out.push(null);
    for (let day = 1; day <= daysInMonth; day++) {
      out.push(new Date(view.year, view.month, day));
    }
    // Pad tail so the grid always ends on Saturday for clean 7-wide rows.
    while (out.length % 7 !== 0) out.push(null);
    return out;
  }, [view]);

  const monthTitle = `${MONTH_LABELS[view.month]} ${view.year}`;

  return (
    <div className="heatmap month-cal">
      <div className="month-cal-head">
        <button
          type="button"
          className="month-nav-btn"
          onClick={() => shift(-1)}
          aria-label="Previous month"
          title="Previous month"
        >
          &lsaquo;
        </button>
        <span className="month-cal-title">{monthTitle}</span>
        <button
          type="button"
          className="month-nav-btn"
          onClick={() => shift(1)}
          aria-label="Next month"
          title="Next month"
        >
          &rsaquo;
        </button>
        <button
          type="button"
          className="month-today-btn"
          onClick={jumpToday}
          title="Jump to current month"
        >
          Today
        </button>
      </div>

      <div className="month-cal-dow">
        {WEEKDAY_LABELS.map((d) => (
          <div key={d} className="month-cal-dow-label">{d}</div>
        ))}
      </div>

      <div className="month-cal-grid">
        {cells.map((d, i) => {
          if (!d) return <div key={i} className="month-cal-cell empty" />;
          const key = dateKey(d);
          const isFuture = d > today;
          const color = isFuture ? "gray" : colorFor(key, byDate, statementSet);
          const isToday = key === todayKey;
          const isSelected = key === selectedDate;
          const stats = byDate[key] || { open: 0, resolved: 0 };
          const title = isFuture
            ? `${key} (future)`
            : `${key} \u00B7 ${stats.open} open / ${stats.resolved} resolved`;
          const cls = [
            "month-cal-cell",
            color,
            isToday ? "today" : "",
            isSelected ? "selected" : "",
            isFuture ? "future" : "",
          ].filter(Boolean).join(" ");
          return (
            <button
              key={i}
              type="button"
              className={cls}
              disabled={isFuture}
              title={title}
              onClick={() => !isFuture && onSelect && onSelect(key)}
            >
              <span className="month-cal-daynum">{d.getDate()}</span>
            </button>
          );
        })}
      </div>

      <div className="heatmap-legend">
        <span className="heatmap-legend-item">
          <span className="heatmap-cell gray legend-dot" /> none
        </span>
        <span className="heatmap-legend-item">
          <span className="heatmap-cell green legend-dot" /> clean
        </span>
        <span className="heatmap-legend-item">
          <span className="heatmap-cell amber legend-dot" /> resolved
        </span>
        <span className="heatmap-legend-item">
          <span className="heatmap-cell red legend-dot" /> open
        </span>
      </div>
    </div>
  );
}
