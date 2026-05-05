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
};
