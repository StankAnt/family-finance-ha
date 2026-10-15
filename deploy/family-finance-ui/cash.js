import { categoryChoices, money } from "./format.js";

const KIND = { opening: "Начальный остаток", reimbursement: "Вернули за покупку", expense: "Покупка наличными" };

export function renderCash(holder) {
  const data = this.cash;
  holder.append(this.heading("Наличные", "Полученные купюры и покупки наличными хранятся здесь. Возврат за чужую покупку уменьшает её расход в отчёте; доходом семьи он не считается."));
  if (!data) return;
  const summary = this.el("div", undefined, "metrics cash-metrics");
  summary.append(this.metric("Остаток наличных", money(data.balance), "На конец выбранного месяца или сегодня", "soft"),
    this.metric("Вернули наличными", money(data.received), "За покупки других людей в выбранном месяце"),
    this.metric("Потрачено наличными", money(data.spent), "Входит в расходы семьи по категориям", "warm"));
  holder.append(summary);

  const actions = this.el("section", undefined, "surface cash-actions");
  actions.append(this.el("h3", "Добавить движение"));
  const switcher = this.el("div", undefined, "cash-switcher");
  const selected = this.pendingCashPurchase ? "reimbursement" : (this.cashKind || "expense");
  const modes = [["expense", "Покупка наличными"], ["reimbursement", "Вернули наличными"],
    ...(!data.has_opening ? [["opening", "Начальный остаток"]] : [])];
  for (const [kind, label] of modes) {
    const button = this.el("button", label, kind === selected ? "cash-switch active" : "cash-switch");
    button.type = "button"; button.setAttribute("aria-pressed", kind === selected ? "true" : "false");
    button.onclick = () => { this.cashKind = kind; if (kind !== "reimbursement") this.pendingCashPurchase = null; this.render(); };
    switcher.append(button);
  }
  actions.append(switcher);
  const current = selected === "opening" && data.has_opening ? "expense" : selected;
  const form = this.el("form", undefined, "cash-form");
  if (current === "reimbursement") {
    if (!this.pendingCashPurchase) {
      const hint = this.el("div", "Откройте «Операции», найдите оплаченную за другого человека покупку и выберите в её меню ⋯ действие «Вернули наличными».", "banner");
      const go = this.el("button", "Найти покупку"); go.type = "button";
      go.onclick = () => { this.tab = "review"; this.filter = "all"; this.drawTabs(); this.render(); };
      actions.append(hint, go); holder.append(actions);
      renderCashHistory.call(this, holder, data); return;
    }
    const tx = this.pendingCashPurchase;
    const purchase = this.el("div", undefined, "cash-purchase");
    purchase.append(this.el("span", "Возврат за покупку"), this.el("strong", tx.description || "Банковская покупка"),
      this.el("small", `${tx.date} · ${money(Math.abs(Number(tx.amount)), tx.currency)} · уже возвращено ${money(tx.cash_reimbursed || 0)}`));
    form.append(purchase);
  }
  const grid = this.el("div", undefined, "cash-form-grid");
  const dateField = this.field(current === "reimbursement" ? "Когда получили деньги" : "Дата", "date", "date");
  const amountField = this.field("Сумма, PLN", "amount", "number");
  const dateInput = dateField.querySelector("input"); dateInput.value = new Date().toLocaleDateString("sv-SE");
  const amountInput = amountField.querySelector("input"); amountInput.min = "0.01"; amountInput.step = "0.01";
  if (current === "reimbursement") amountInput.value = String(Math.max(0,
    Math.abs(Number(this.pendingCashPurchase.amount)) - Number(this.pendingCashPurchase.cash_reimbursed || 0)).toFixed(2));
  grid.append(dateField, amountField);
  if (current === "expense") {
    const categories = this.options.categories.filter(path => path !== "Income" && !path.startsWith("Income/"));
    grid.append(this.choice("Категория расхода", "category", [["", "Без категории"], ...categoryChoices(categories)]),
      this.choice("Проект", "project", [["", "Без проекта"], ...this.options.projects.map(name => [name, name])]));
  }
  grid.append(this.field(current === "opening" ? "Откуда начальная сумма (необязательно)" : "Заметка (необязательно)", "note", "text"));
  form.append(grid);
  const save = this.el("button", current === "opening" ? "Сохранить остаток" :
    current === "reimbursement" ? "Учесть возврат" : "Добавить покупку", "primary");
  save.type = "submit"; form.append(save);
  form.onsubmit = event => { event.preventDefault(); this.busy(async () => {
    save.disabled = true;
    const values = new FormData(form);
    await this.api("cash_add", { kind: current, date: values.get("date"), amount: values.get("amount"),
      note: values.get("note") || "", ...(current === "reimbursement" ?
        { transaction_id: this.pendingCashPurchase.id } : {}),
      ...(current === "expense" ? { category: values.get("category") || "", project: values.get("project") || "" } : {}) });
    this.pendingCashPurchase = null; this.cashKind = "expense";
    await this.reloadPeriod(); this.status("Наличные учтены", true);
  }).finally(() => { save.disabled = false; }); };
  actions.append(form);
  if (current === "opening") actions.append(this.el("p", "Начальный остаток — деньги, которые уже были у вас в кошельке на указанную дату. Это не доход и не расход.", "muted"));
  holder.append(actions);
  renderCashHistory.call(this, holder, data);
}

function renderCashHistory(holder, data) {
  const section = this.el("section", undefined, "surface");
  section.append(this.el("h3", `История · ${data.period}`));
  if (!data.rows.length) section.append(this.el("p", "В этом месяце движений наличных пока нет.", "muted"));
  const list = this.el("div", undefined, "cash-history");
  for (const row of data.rows) {
    const item = this.el("div", undefined, "cash-entry");
    const main = this.el("div", undefined, "cash-entry-main");
    main.append(this.el("strong", KIND[row.kind] || row.kind),
      this.el("small", `${row.date}${row.category ? ` · ${row.category}` : ""}${row.project ? ` · ${row.project}` : ""}`));
    if (row.purchase) main.append(this.el("span", row.purchase, "cash-linked-purchase"));
    if (row.note) main.append(this.el("span", row.note, "muted"));
    const amount = this.el("strong", money(row.amount), Number(row.amount) >= 0 ? "cash-in" : "");
    const remove = this.el("button", "Удалить", "cash-remove"); remove.type = "button";
    remove.setAttribute("aria-label", `Удалить запись ${row.date} ${KIND[row.kind] || row.kind}`);
    remove.onclick = () => this.busy(async () => {
      if (!window.confirm(`Удалить запись «${KIND[row.kind] || row.kind}» на ${money(row.amount)}?`)) return;
      await this.api("cash_delete", { id: row.id }); await this.reloadPeriod();
      this.status("Запись удалена", true);
    });
    item.append(main, amount, remove); list.append(item);
  }
  section.append(list); holder.append(section);
}
