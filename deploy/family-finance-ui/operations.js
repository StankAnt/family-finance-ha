import { TYPE_INFO, categoryChoices, categoryLabel, money, monthTitle } from "./format.js";
import { renderReturnSelection } from "./purchase-returns.js";

export async function saveCorrection(tx, values, button, message) {
  button.disabled = true;
  let learned = 0;
  await this.busy(async () => {
    if (!values.economic_type) throw new Error("Выберите тип операции");
    const result = await this.api("correct", { transaction_id: tx.id,
      category: values.category || null, project: values.project || null,
      economic_type: values.economic_type });
    learned = result.learned || 0;
    await this.reloadPeriod();
  }, message);
  if (learned) this.status(`${message}. Ещё ${learned} похожих операций размечено.`, true);
  button.disabled = false;
}

export function renderReview(holder) {
  const head = this.heading(`Операции · ${this.reviewScope === "month" ? monthTitle(this.month) : "всё время"}`,
    "Найдите операцию по периоду, категории или проекту. Откройте строку, чтобы проверить и изменить разметку.");
  head.classList.add("review-head");
  const toolbar = this.el("div", undefined, "toolbar-actions");
  const filter = this.choice("Показать", "status", [["all","Все операции"],["unclassified","Требуют разметки"],["pending","Ожидают проведения"]], this.filter);
  filter.querySelector("select").onchange = async (event) => {
    this.filter = event.target.value; this.page = 0; this.transactionId = "";
    await this.busy(async () => { await this.loadReview(); this.render(); });
  };
  const search = this.el("form", undefined, "review-search");
  search.setAttribute("role", "search");
  const searchLabel = this.el("label", "Поиск по операциям");
  const searchControls = this.el("div", undefined, "review-search-controls");
  const searchInput = this.el("input"); searchInput.type = "search";
  searchInput.placeholder = "Описание, сумма или дата"; searchInput.maxLength = 120;
  searchInput.setAttribute("aria-label", "Поиск по операциям");
  searchInput.value = this.search;
  const submit = this.el("button", "Найти"); submit.type = "submit";
  searchControls.append(searchInput, submit);
  if (this.search) {
    const clear = this.el("button", "Сбросить"); clear.type = "button";
    clear.onclick = async () => {
      this.search = ""; this.page = 0; this.transactionId = "";
      await this.busy(async () => { await this.loadReview(); this.render(); });
    };
    searchControls.append(clear);
  }
  searchLabel.append(searchControls); search.append(searchLabel);
  search.onsubmit = async (event) => {
    event.preventDefault();
    this.search = searchInput.value.trim(); this.page = 0; this.transactionId = "";
    if (this.search) this.filter = "all";
    await this.busy(async () => { await this.loadReview(); this.render(); });
  };
  const scope = this.choice("Период", "scope", [["month", "Выбранный месяц"], ["all", "Всё время"]], this.reviewScope);
  const categoryOptions = [...this.options.categories];
  if (this.categoryFilter && !categoryOptions.includes(this.categoryFilter))
    categoryOptions.push(this.categoryFilter);
  const category = this.choice("Категория", "category_filter",
    [["", "Все категории"], ...categoryChoices(categoryOptions)], this.categoryFilter);
  const projectOptions = [...this.options.projects];
  if (this.projectFilter && !projectOptions.includes(this.projectFilter))
    projectOptions.push(this.projectFilter);
  const project = this.choice("Проект", "project_filter",
    [["", "Все проекты"], ...projectOptions.map(name => [name, name])], this.projectFilter);
  project.classList.add("review-project");
  const view = this.choice("Вид", "view", [["list", "Список"], ["cards", "Карточки"]], this.reviewView);
  for (const [field, key] of [[scope, "reviewScope"], [category, "categoryFilter"], [project, "projectFilter"]]) {
    field.querySelector("select").onchange = async event => {
      this[key] = event.target.value; this.page = 0; this.transactionId = "";
      if ((key === "reviewScope" && this.reviewScope === "all") ||
          (key !== "reviewScope" && event.target.value)) this.filter = "all";
      await this.busy(async () => { await this.loadReview(); this.render(); });
    };
  }
  view.querySelector("select").onchange = event => { this.reviewView = event.target.value; this.render(); };
  toolbar.append(search, filter, view, scope, category, project);
  const reset = this.el("button", "Сбросить все фильтры", "review-reset"); reset.type = "button";
  reset.disabled = this.filter === "all" && !this.search && this.reviewScope === "month" &&
    !this.categoryFilter && !this.projectFilter && this.reviewView === "list";
  reset.onclick = async () => {
    Object.assign(this, { filter: "all", search: "", reviewScope: "month",
      categoryFilter: "", projectFilter: "", reviewView: "list", page: 0, transactionId: "" });
    await this.busy(async () => { await this.loadReview(); this.render(); });
  };
  head.append(toolbar, reset); holder.append(head);
  if (this.projectFilter && this.review.project_total) {
    const summary = this.review.project_total;
    holder.append(this.metric(`Проект «${this.projectFilter}» · за всё время`, money(summary.amount_pln),
      `${summary.transactions} расходов${summary.missing_fx ? ` · ${summary.missing_fx} без курса валюты не включены` : ""}`, "soft"));
  }
  this.renderPairSelection(holder);
  renderReturnSelection.call(this, holder);
  if (!this.review.rows.length) holder.append(this.el("div",
    this.search ? "По запросу ничего не найдено." :
    this.filter === "unclassified" ? "Нет операций, требующих разметки, с такими фильтрами." : "Операций с такими фильтрами нет.",
    "surface empty"));
  const list = this.el("div", undefined, "tx-list");
  for (const tx of this.review.rows) this.renderTransaction(list, tx);
  holder.append(list);
  const pager = this.el("div", undefined, "pager");
  const prev = this.el("button", "← Назад"); prev.disabled = this.page === 0;
  prev.onclick = () => this.changePage(-1);
  const next = this.el("button", "Далее →"); next.disabled = (this.page + 1) * 30 >= this.review.total;
  next.onclick = () => this.changePage(1);
  const start = this.review.total ? this.review.offset + 1 : 0;
  pager.append(prev, this.el("span", `${start}–${this.review.offset + this.review.rows.length} из ${this.review.total}`, "muted"), next);
  holder.append(pager);
}

export function appendReviewRow(list, row, tx) {
  if (this.reviewView === "cards") { list.append(row); return; }
  const item = this.el("details", undefined, "transaction-list-item");
  if (tx.id === this.transactionId) { item.open = true; item.classList.add("is-target"); }
  item.addEventListener("toggle", () => {
    if (item.open && this.transactionId !== tx.id) {
      this.transactionId = tx.id;
      this.syncRoute();
    } else if (!item.open && this.transactionId === tx.id) {
      this.transactionId = "";
      this.syncRoute();
    }
  });
  const summary = this.el("summary", undefined, "transaction-list-summary");
  const date = this.el("span", tx.date, "transaction-list-date");
  const details = this.el("span", undefined, "transaction-list-main");
  details.append(this.el("strong", tx.description || "Без описания"),
    this.el("small", [tx.bank_status !== "BOOK" ? "Ожидает проведения" :
      categoryLabel(tx.category) || TYPE_INFO[tx.economic_type]?.[0] || "Без категории",
      tx.project ? `Проект: ${tx.project}` : "",
      tx.return_candidates?.length ? "Возможный возврат — проверьте связь" : "",
      tx.linked_return ? "Связан с покупкой" : "",
      tx.purchase?.shares?.length ? "Есть доли других участников" : ""].filter(Boolean).join(" · ")));
  const amount = this.el("strong", money(tx.amount, tx.currency),
    Number(tx.amount) >= 0 ? "transaction-list-amount in" : "transaction-list-amount");
  summary.append(date, details, amount);
  item.append(summary, row); list.append(item);
}

export function renderPairSelection(holder) {
  const { debit, credit } = this.pairSelection;
  if (!debit && !credit) return;
  const panel = this.el("section", undefined, "surface pair-picker");
  panel.append(this.el("h3", "Подтвердить перевод между своими счетами"),
    this.el("p", "Выберите списание и зачисление. Чтобы найти вторую сторону, можно переключить «Все операции», страницу или месяц. После подтверждения обе операции исключаются из доходов и расходов.", "muted"));
  for (const [label, tx] of [["Списание", debit], ["Зачисление", credit]]) {
    const line = this.el("div", undefined, "list-row");
    line.append(this.el("span", tx ? `${label}: ${tx.date} · ${tx.description}` : `${label}: выберите операцию в списке`));
    if (tx) line.append(this.el("strong", money(tx.amount, tx.currency)));
    panel.append(line);
  }
  if (debit && credit) {
    if (debit.currency !== credit.currency || Number(debit.amount) + Number(credit.amount) !== 0) {
      panel.append(this.el("p", "Суммы или валюты не совпадают. Выберите другую операцию.", "banner"));
    } else {
      const confirm = this.el("button", "Подтвердить как свой перевод", "primary");
      confirm.type = "button";
      confirm.onclick = async () => {
        confirm.disabled = true;
        await this.busy(async () => {
          await this.api("manual_pair", { debit_id:debit.id, credit_id:credit.id });
          this.pairSelection = { debit:null, credit:null };
          [this.overview, this.transfers] = await Promise.all([
            this.api("overview", {month:this.month}), this.api("transfers")]);
          await this.loadReview(); this.render();
        }, "Свой перевод подтверждён. Обе операции исключены из доходов и расходов.");
        confirm.disabled = false;
      };
      panel.append(confirm);
    }
  }
  const clear = this.el("button", "Сбросить выбор"); clear.type = "button";
  clear.onclick = () => { this.pairSelection = { debit:null, credit:null }; this.render(); };
  panel.append(clear); holder.append(panel);
}

export async function changePage(delta) {
  const previous = this.page;
  this.page += delta; this.transactionId = "";
  await this.busy(async () => { await this.loadReview(); this.render(); });
  if (!this.review || this.review.offset !== this.page * 30) this.page = previous;
}
