async function json(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

export const api = {
  getConfig: () => fetch("/api/config").then(json),
  getState: () => fetch("/api/state").then(json),
  getLibrary: () => fetch("/api/canara/library").then(json),
  getData: (query) => fetch("/api/data?" + query).then(json),
  getTally: () => fetch("/api/tally").then(json),
  reconcile: () => fetch("/api/reconcile", { method: "POST" }).then(json),
  resolve: (id) => fetch(`/api/resolve/${id}`, { method: "POST" }).then(json),
  unresolve: (id) =>
    fetch(`/api/unresolve/${id}`, { method: "POST" }).then(json),
  uploadCanara: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/upload/canara", { method: "POST", body: fd }).then(json);
  },
  uploadBankStatement: (bankCode, file) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("bank_code", bankCode);
    return fetch("/api/upload/bank", { method: "POST", body: fd }).then(json);
  },
  getBankLibrary: () => fetch("/api/bank/library").then(json),
  deleteBankStatement: (date, bankCode) => {
    const qs = new URLSearchParams({ date, bank_code: bankCode }).toString();
    return fetch(`/api/bank/statement?${qs}`, { method: "DELETE" }).then(json);
  },
  resetDate: (date) =>
    fetch("/api/reset/date", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date, confirm: "RESET" }),
    }).then(json),
  uploadBranch: (branch, file) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("branch", branch);
    return fetch("/api/upload/branch", { method: "POST", body: fd }).then(json);
  },
  exportUrl: (query) => "/api/export?" + query,
  exportFullUrl: () => "/api/export/full",
  uploadLedgerPhoto: (branch, file) => {
    const fd = new FormData();
    fd.append("branch", branch);
    fd.append("file", file);
    return fetch("/api/ledger/upload", { method: "POST", body: fd }).then(json);
  },
  listLedger: (branch) =>
    fetch("/api/ledger/list?branch=" + encodeURIComponent(branch)).then(json),

  // ----- historical flags -----
  getFlagsSummary: () => fetch("/api/flags/summary").then(json),
  getFlagsHistory: (query = "") =>
    fetch("/api/flags/history" + (query ? "?" + query : "")).then(json),
  resolveFlag: (id, reason, attachment) => {
    const fd = new FormData();
    fd.append("reason", reason);
    if (attachment) fd.append("attachment", attachment);
    return fetch(`/api/flags/${id}/resolve`, {
      method: "POST",
      body: fd,
    }).then(json);
  },
  flagAttachmentUrl: (id) => `/api/flags/${id}/attachment`,
  reopenFlag: (id) =>
    fetch(`/api/flags/${id}/reopen`, { method: "POST" }).then(json),
  flagsExportUrl: (query = "") =>
    "/api/flags/export" + (query ? "?" + query : ""),

  // ----- bulk resolve -----
  resolveRowsBulk: (ids) =>
    fetch("/api/resolve/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    }).then(json),
  resolveFlagsBulk: (ids, reason, attachment) => {
    const fd = new FormData();
    fd.append("reason", reason);
    if (attachment) fd.append("attachment", attachment);
    for (const id of ids) fd.append("ids", String(id));
    return fetch("/api/flags/bulk-resolve", {
      method: "POST",
      body: fd,
    }).then(json);
  },

  // ----- comprehensive report -----
  reportComprehensiveUrl: () => "/api/report/comprehensive",

  // ----- cash pipeline (KVB / SBI / IOB ↔ digitized handwritten ledger) -----
  uploadLedgerCsv: (file, date) => {
    const fd = new FormData();
    fd.append("file", file);
    if (date) fd.append("date", date);
    return fetch("/api/cash/upload-ledger", { method: "POST", body: fd }).then(json);
  },
  reconcileCash: (date, dateWindowDays = 1) =>
    fetch("/api/cash/reconcile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date, date_window_days: dateWindowDays }),
    }).then(json),
  getCashData: (tab, { date, includeResolved = false } = {}) => {
    const qs = new URLSearchParams({ tab });
    if (date) qs.set("date", date);
    if (includeResolved) qs.set("include_resolved", "1");
    return fetch("/api/cash/data?" + qs.toString()).then(json);
  },
  resolveCash: (id) =>
    fetch(`/api/cash/resolve/${id}`, { method: "POST" }).then(json),
  unresolveCash: (id) =>
    fetch(`/api/cash/unresolve/${id}`, { method: "POST" }).then(json),

  // ----- cross-pipeline duplicate check ------------------------------
  // Catches the same payment booked once as UPI and once as cash.
  getCrossCheckDuplicates: () =>
    fetch("/api/cross-check/duplicates").then(json),

  // ----- combined summary across both pipelines ----------------------
  getCombinedSummary: (date) => {
    const qs = date ? "?date=" + encodeURIComponent(date) : "";
    return fetch("/api/combined/summary" + qs).then(json);
  },

  // ----- day tally — single ✓/⚠ verdict for the day -------------------
  getDayTally: (date) => {
    const qs = date ? "?date=" + encodeURIComponent(date) : "";
    return fetch("/api/day-tally" + qs).then(json);
  },

  // ----- preview the contents of uploaded cash bank statements ---------
  getCashStatementsSummary: () =>
    fetch("/api/cash/statements-summary").then(json),
  getCashBankDeposits: (bankCode, date) => {
    const qs = new URLSearchParams({ bank_code: bankCode, date }).toString();
    return fetch("/api/cash/bank-deposits?" + qs).then(json);
  },

  // ----- OCR (Claude Vision) ledger ingest ---------------------------
  // The probe returns {available, reason, model} so the UI can show
  // the button as live or as a disabled hint with the missing piece named.
  getOcrStatus: () =>
    fetch("/api/cash/ocr-status").then(json),
  ocrLedgerPhoto: (file, date) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("date", date);
    return fetch("/api/cash/ocr-ledger", { method: "POST", body: fd }).then(json);
  },
};
