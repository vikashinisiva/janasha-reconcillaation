import { useEffect, useState } from "react";

export default function Filters({ filters, setFilter, onExport, branches }) {
  const [searchInput, setSearchInput] = useState(filters.search);

  // Debounce search typing before pushing into filter state.
  useEffect(() => {
    const t = setTimeout(() => {
      if (searchInput.trim() !== filters.search) {
        setFilter("search", searchInput.trim());
      }
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  // If the filter is cleared externally, mirror that in the input.
  useEffect(() => {
    if (filters.search === "" && searchInput !== "") setSearchInput("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search]);

  return (
    <section className="filters">
      <input
        type="search"
        id="search"
        placeholder="SEARCH NAME / UTR / BRANCH"
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
      />
      <select
        value={filters.branch}
        onChange={(e) => setFilter("branch", e.target.value)}
      >
        <option value="">ALL BRANCHES</option>
        {branches.map((b) => (
          <option key={b.code} value={b.name}>
            {b.name}
          </option>
        ))}
      </select>
      <select
        value={filters.policy_type}
        onChange={(e) => setFilter("policy_type", e.target.value)}
      >
        <option value="">ALL TYPES</option>
        <option value="RD">RD</option>
        <option value="FD">FD</option>
        <option value="MIS">MIS</option>
        <option value="DRD">DRD</option>
      </select>
      <select
        value={filters.status}
        onChange={(e) => setFilter("status", e.target.value)}
      >
        <option value="">ALL STATUSES</option>
        <option value="MATCHED">Matched</option>
        <option value="MISMATCH">Amount Mismatch</option>
        <option value="MISSING">Missing from Bank</option>
        <option value="UNRECORDED">Unrecorded in Bank</option>
      </select>
      <button className="btn-ghost" onClick={onExport}>
        Export
      </button>
    </section>
  );
}
