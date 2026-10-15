import { styles } from "./family-finance-ui/styles.js";
import { renderInputs } from "./family-finance-ui/inputs.js";
import { heading, metric, field, choice, checkbox, form } from "./family-finance-ui/components.js";
import { renderOverview } from "./family-finance-ui/overview.js";
import { saveCorrection, renderReview, appendReviewRow, renderPairSelection, changePage } from "./family-finance-ui/operations.js";
import { renderTransfers } from "./family-finance-ui/transfers.js";
import { renderCash } from "./family-finance-ui/cash.js";
import { renderTransaction } from "./family-finance-ui/transaction.js";
import { readRoute, writeRoute } from "./family-finance-ui/router.js";

class FamilyFinanceCard extends HTMLElement {
  setConfig(config) { this.config = config; }
  set hass(hass) {
    this._hass = hass;
    if (this.isConnected && !this._loaded) this.load();
  }
  connectedCallback() {
    this.captureAuthorizationRedirect();
    if (this.shadowRoot) {
      if (!this._routeListener) {
        this._routeListener = () => this.applyRouteFromLocation();
        window.addEventListener("hashchange", this._routeListener);
        window.addEventListener("popstate", this._routeListener);
      }
      this.applyRouteFromLocation();
      return;
    }
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style"); style.textContent = styles;
    this.shadowRoot.append(style);
    const app = this.el("div", undefined, "app");
    const mast = this.el("header", undefined, "mast");
    const top = this.el("div", undefined, "mast-top");
    const intro = this.el("div");
    intro.append(this.el("div", "Личный финансовый кабинет", "eyebrow"),
      this.el("h1", "Семейные финансы"),
      this.el("p", "Доходы, расходы и решения по операциям в одном месте."));
    this.source = "production";
    const period = this.el("div", undefined, "period-control");
    period.append(this.el("label", "Месяц", "month-label"));
    const input = this.el("input"); input.type = "month"; input.setAttribute("aria-label", "Месяц отчёта");
    const now = new Date();
    this.month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    input.value = this.month;
    input.onchange = () => this.changeMonth(input.value);
    this.monthInput = input;
    const previous = this.el("button", "←"); previous.type = "button";
    previous.setAttribute("aria-label", "Предыдущий месяц");
    previous.onclick = () => this.shiftMonth(-1);
    const next = this.el("button", "→"); next.type = "button";
    next.setAttribute("aria-label", "Следующий месяц");
    next.onclick = () => this.shiftMonth(1);
    period.append(previous, input, next);
    top.append(intro, period); mast.append(top); app.append(mast);
    app.append(this.el("nav", undefined, "nav"));
    const message = this.el("div", undefined, "message"); message.hidden = true;
    message.setAttribute("role", "status"); message.setAttribute("aria-live", "polite");
    app.append(message, this.el("main", undefined, "content"));
    this.shadowRoot.append(app);
    this.tab = "overview"; this.page = 0; this.filter = "all"; this.search = "";
    this.reviewScope = "month"; this.categoryFilter = ""; this.projectFilter = "";
    this.reviewView = "list"; this.transactionId = "";
    this.pairSelection = { debit: null, credit: null };
    const initialRoute = readRoute(window.location.hash, this.month);
    if (initialRoute) {
      Object.assign(this, initialRoute);
      this._scrollToTarget = !!initialRoute.transactionId;
    }
    this.monthInput.value = this.month;
    this._routeListener = () => this.applyRouteFromLocation();
    window.addEventListener("hashchange", this._routeListener);
    window.addEventListener("popstate", this._routeListener);
    this.drawTabs();
    if (this._hass && !this._loaded) this.load();
  }
  disconnectedCallback() {
    if (this._routeListener) {
      window.removeEventListener("hashchange", this._routeListener);
      window.removeEventListener("popstate", this._routeListener);
      this._routeListener = null;
    }
    if (this.aiPollTimer) { clearTimeout(this.aiPollTimer); this.aiPollTimer = null; }
  }
  captureAuthorizationRedirect() {
    const params = new URLSearchParams(window.location.search);
    if (!["code", "state", "error", "error_description"].some(key => params.has(key))) return;
    if (params.getAll("code").length === 1 && params.getAll("state").length === 1 && !params.has("error"))
      this.pendingRedirectUrl = window.location.href;
    else this.authorizationError = "Банк не завершил авторизацию. Получите новую ссылку и повторите вход.";
    for (const key of ["code", "state", "error", "error_description"]) params.delete(key);
    const query = params.toString();
    window.history.replaceState(window.history.state, "",
      `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
  }
  syncRoute() {
    if (this._applyingRoute) return;
    const hash = writeRoute(this);
    if (window.location.hash !== hash)
      window.history.pushState(null, "", `${window.location.pathname}${window.location.search}${hash}`);
  }
  async applyRouteFromLocation() {
    const route = readRoute(window.location.hash, this.month);
    if (!route) return;
    const monthChanged = route.month !== this.month;
    const reviewChanged = ["reviewScope", "filter", "search", "categoryFilter", "projectFilter", "page"]
      .some(key => route[key] !== this[key]);
    const generation = (this._routeGeneration || 0) + 1;
    this._routeGeneration = generation;
    Object.assign(this, route);
    this._scrollToTarget = !!route.transactionId;
    this.monthInput.value = this.month;
    this.drawTabs();
    if (!this._loaded) return;
    this._applyingRoute = true;
    try {
      if (monthChanged) {
        const [overview, review, cash] = await Promise.all([
          this.api("overview", { month: this.month }), this.api("review", this.reviewPayload()),
          this.api("cash", { month: this.month })]);
        if (generation !== this._routeGeneration) return;
        this.overview = overview; this.review = review; this.cash = cash;
      } else if (reviewChanged) {
        const review = await this.api("review", this.reviewPayload());
        if (generation !== this._routeGeneration) return;
        this.review = review;
      }
      this.render();
    } catch (error) {
      this.status(error.message || "Не удалось открыть страницу");
    } finally {
      if (generation === this._routeGeneration) this._applyingRoute = false;
    }
  }
  el(tag, value, className) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = value;
    if (className) node.className = className;
    return node;
  }
  async api(operation, payload = {}) {
    const message = { type: "family_finance/request", operation, payload, source: this.source };
    if (operation === "bank_accounts" || operation === "bank_sync") message.user_agent = navigator.userAgent;
    return this._hass.callWS(message);
  }
  status(message, ok = false) {
    const node = this.shadowRoot.querySelector(".message");
    node.textContent = message || "";
    node.className = ok ? "message success" : "message";
    node.hidden = !message;
  }
  async busy(action, success) {
    this.status("");
    try {
      await action();
      if (success) this.status(success, true);
    } catch (error) {
      this.status(error.message || "Действие не выполнено. Попробуйте ещё раз.");
    }
  }
  async load() {
    this._loaded = true;
    await this.busy(async () => {
      [this.options, this.transfers, this.setupStatus] = await Promise.all([
        this.api("options"), this.api("transfers"), this.api("setup_status")]);
      await this.reloadPeriod();
      if (this.source === "production") await this.refreshAiStatus();
    });
  }
  async reloadPeriod() {
    [this.overview, this.review, this.cash] = await Promise.all([
      this.api("overview", { month: this.month }),
      this.api("review", this.reviewPayload()),
      this.api("cash", { month: this.month }),
    ]);
    this.render();
  }
  async refreshAiStatus() {
    if (this.source !== "production") return;
    const previous = this.aiStatus?.state;
    this.aiStatus = await this.api("ai_status");
    if (previous === "running" && this.aiStatus.state !== "running") await this.reloadPeriod();
    else this.render();
    if (this.aiStatus.state === "running" && !this.aiPollTimer) {
      this.aiPollTimer = setTimeout(async () => {
        this.aiPollTimer = null;
        try { await this.refreshAiStatus(); }
        catch (error) { this.status(error.message || "Не удалось получить статус OpenAI"); }
      }, 5000);
    }
  }
  async loadReview() {
    this.review = await this.api("review", this.reviewPayload());
  }
  reviewPayload() {
    return { ...(this.reviewScope === "month" ? { month: this.month } : {}),
      status: this.filter, search: this.search, category: this.categoryFilter,
      project: this.projectFilter, offset: this.page * 30, limit: 30 };
  }
  async openReviewFilter({ category = "", project = "" }) {
    const previous = { categoryFilter: this.categoryFilter, projectFilter: this.projectFilter,
      reviewScope: this.reviewScope, filter: this.filter, search: this.search, page: this.page };
    Object.assign(this, { categoryFilter: category, projectFilter: project,
      reviewScope: "month", filter: "all", search: "", page: 0, transactionId: "" });
    this.status("");
    try {
      await this.loadReview();
      this.tab = "review";
      this.drawTabs(); this.render();
      this.shadowRoot.querySelector(".nav").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      Object.assign(this, previous);
      this.status(error.message || "Не удалось открыть операции для категории.");
    }
  }
  async changeMonth(value) {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return;
    const previous = this.month;
    this.month = value; this.page = 0;
    try {
      await this.reloadPeriod(); this.status("");
    } catch (error) {
      this.month = previous; this.monthInput.value = previous;
      this.status(error.message || "Не удалось загрузить месяц");
    }
  }
  shiftMonth(delta) {
    const [year, month] = this.month.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1 + delta, 1));
    const value = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
    this.monthInput.value = value; this.changeMonth(value);
  }
  drawTabs() {
    const holder = this.shadowRoot.querySelector(".nav"); holder.replaceChildren();
    for (const [id, title] of [["overview","Обзор"],["review","Операции"],
                                ["transfers","Свои переводы"],["cash","Наличные"],["inputs","Настройки и ввод"]]) {
      const link = this.el("a", title, id === this.tab ? "active" : "");
      link.href = writeRoute({ ...this, tab: id });
      if (id === this.tab) link.setAttribute("aria-current", "page");
      link.onclick = event => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        this.tab = id; this.drawTabs(); this.render();
      };
      holder.append(link);
    }
  }
  render() {
    const holder = this.shadowRoot.querySelector(".content"); holder.replaceChildren();
    if (!this.overview || !this.review) return;
    if (this.tab === "overview") this.renderOverview(holder);
    else if (this.tab === "review") this.renderReview(holder);
    else if (this.tab === "transfers") this.renderTransfers(holder);
    else if (this.tab === "cash") renderCash.call(this, holder);
    else this.renderInputs(holder);
    this.syncRoute();
    if (this._scrollToTarget) {
      this._scrollToTarget = false;
      requestAnimationFrame(() => this.shadowRoot.querySelector(".is-target")?.scrollIntoView({ block: "center" }));
    }
  }
  renderInputs(holder) { renderInputs.call(this, holder); }
  getCardSize() { return 8; }
}
Object.assign(FamilyFinanceCard.prototype, { heading, metric, field, choice, checkbox, form,
  renderOverview, saveCorrection, renderReview, renderTransaction, appendReviewRow, renderPairSelection, changePage, renderTransfers });
customElements.define("family-finance-card", FamilyFinanceCard);
