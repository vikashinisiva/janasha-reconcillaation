export function fmtAmount(v) {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function pillLabel(status) {
  switch (status) {
    case "MATCHED": return "Matched";
    case "MISMATCH": return "Mismatch";
    case "MISSING": return "Missing";
    case "UNRECORDED": return "Unrecorded";
    case "CANARA_PENDING": return "Canara Pending";
    case "BRANCH_MISMATCH": return "Branch Mismatch";
    case "DUPLICATE": return "Duplicate UTR";
    default: return status || "";
  }
}

export function buildQuery(tab, filters) {
  const p = new URLSearchParams();
  p.set("tab", tab);
  for (const [k, v] of Object.entries(filters)) {
    if (v) p.set(k, v);
  }
  return p.toString();
}

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export function fmtDate(iso) {
  // YYYY-MM-DD → "01 Apr 2026"
  if (!iso || typeof iso !== "string") return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${m[3]} ${MONTHS[parseInt(m[2], 10) - 1] || m[2]} ${m[1]}`;
}
