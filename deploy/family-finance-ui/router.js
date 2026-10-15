// Home Assistant already owns /family-finance/overview. Keep only the page in
// the fragment so the dashboard slug is not repeated in bookmarked URLs.
const PREFIX = "#/";
const LEGACY_PREFIX = "#/family-finance/";
const PAGE_TO_TAB = { overview: "overview", operations: "review", transfers: "transfers", cash: "cash",
  settings: "inputs", review: "review", inputs: "inputs" };
const TAB_TO_PAGE = { overview: "overview", review: "operations", transfers: "transfers", cash: "cash", inputs: "settings" };
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const STATUSES = new Set(["all", "unclassified", "pending"]);

export function readRoute(hash, defaultMonth) {
  const prefix = hash.startsWith(LEGACY_PREFIX) ? LEGACY_PREFIX : PREFIX;
  if (!hash.startsWith(prefix)) return null;
  const [path, query = ""] = hash.slice(prefix.length).split("?", 2);
  const params = new URLSearchParams(query);
  const month = params.get("month");
  const page = Number(params.get("page"));
  return {
    tab: PAGE_TO_TAB[path] || "overview",
    month: month && MONTH.test(month) ? month : defaultMonth,
    reviewScope: params.get("scope") === "all" ? "all" : "month",
    filter: STATUSES.has(params.get("status")) ? params.get("status") : "all",
    search: (params.get("q") || "").slice(0, 120),
    categoryFilter: (params.get("category") || "").slice(0, 250),
    projectFilter: (params.get("project") || "").slice(0, 120),
    reviewView: params.get("view") === "cards" ? "cards" : "list",
    page: Number.isSafeInteger(page) && page >= 0 && page <= 333 ? page : 0,
    transactionId: (params.get("tx") || "").slice(0, 80),
  };
}

export function writeRoute(state) {
  const tab = TAB_TO_PAGE[state.tab] ? state.tab : "overview";
  const params = new URLSearchParams();
  if (MONTH.test(state.month || "")) params.set("month", state.month);
  if (tab === "review") {
    if (state.reviewScope === "all") params.set("scope", "all");
    if (state.filter && state.filter !== "all") params.set("status", state.filter);
    if (state.search) params.set("q", state.search);
    if (state.categoryFilter) params.set("category", state.categoryFilter);
    if (state.projectFilter) params.set("project", state.projectFilter);
    if (state.reviewView === "cards") params.set("view", "cards");
    if (state.page) params.set("page", String(state.page));
    if (state.transactionId) params.set("tx", state.transactionId);
  }
  const query = params.toString();
  return `${PREFIX}${TAB_TO_PAGE[tab]}${query ? `?${query}` : ""}`;
}
