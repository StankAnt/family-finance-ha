import { categoryChoices, money } from "./format.js";

const KIND = { opening: "Начальный остаток", reimbursement: "Вернули за покупку", expense: "Покупка наличными" };
const CURRENCIES = ["PLN", "EUR", "USD"];

export function renderCash(holder) {
  const data = this.cash;
  holder.append(this.heading("Наличные", "Храните суммы в PLN, EUR и USD. Покупки пересчитываются по дате покупки, остаток — по дате отчёта. Возврат за чужую покупку не считается доходом."));
  if (!data) return;
  const summary = this.el("div", undefined, "metrics cash-metrics");
  summary.append(this.metric("Остаток наличных", money(data.balance), "На конец выбранного месяца или сегодня", "soft"),
    this.metric("Вернули наличными", money(data.received), "За покупки других людей в выбранном месяце"),
    this.metric("Потрачено наличными", money(data.spent), "Входит в расходы семьи по категориям", "warm"));
  holder.append(summary);
  const balances = this.el("section", undefined, "surface cash-balances");
  balances.append(this.el("h3", `В кошельке на ${data.as_of}`));
  if (!data.balances.length) balances.append(this.el("p", "Пока нет записей. Добавьте начальный остаток или возврат за покупку.", "muted"));
  const balanceGrid = this.el("div", undefined, "cash-balance-grid");
  for (const item of data.balances) {
    const card = this.el("div", undefined, "cash-currency-card");
    card.append(this.el("strong", money(item.amount, item.currency)),
      this.el("span", item.currency === "PLN" ? "Без пересчёта" : item.amount_pln == null ?
        "Нет курса на дату отчёта" : `≈ ${money(item.amount_pln)} · курс ${item.rate} от ${item.rate_date}`));
    balanceGrid.append(card);
  }
  balances.append(balanceGrid); holder.append(balances);
  if (data.missing_fx?.length) {
    const missing = this.el("div", undefined, "banner");
    missing.append(this.el("span", "Для пересчёта не хватает курса NBP на одну или несколько дат. Исходные суммы в валютах сохранены."));
    const retry = this.el("button", "Обновить курсы"); retry.type = "button";
    retry.onclick = () => this.busy(async () => {
      for (const month of new Set(data.missing_fx.map(item => item.date.slice(0, 7))))
        await this.api("cash_fx_sync", { month });
      await this.reloadPeriod(); this.status("Курсы обновлены", true);
    });
    missing.append(retry); holder.append(missing);
  }

  const actions = this.el("section", undefined, "surface cash-actions");
  actions.append(this.el("h3", "Добавить движение"));
  const switcher = this.el("div", undefined, "cash-switcher");
  const selected = this.pendingCashPurchase ? "reimbursement" : (this.cashKind || "expense");
  const modes = [["expense", "Покупка наличными"], ["reimbursement", "Вернули наличными"],
    ...((data.opening_currencies || []).length < CURRENCIES.length ? [["opening", "Начальный остаток"]] : [])];
  for (const [kind, label] of modes) {
    const button = this.el("button", label, kind === selected ? "cash-switch active" : "cash-switch");
    button.type = "button"; button.setAttribute("aria-pressed", kind === selected ? "true" : "false");
    button.onclick = () => { this.cashKind = kind; if (kind !== "reimbursement") this.pendingCashPurchase = null; this.render(); };
    switcher.append(button);
  }
  actions.append(switcher);
  const current = selected === "opening" && (data.opening_currencies || []).length === CURRENCIES.length ? "expense" : selected;
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
  const amountField = this.field("Сумма", "amount", "number");
  const dateInput = dateField.querySelector("input"); dateInput.value = new Date().toLocaleDateString("sv-SE");
  const amountInput = amountField.querySelector("input"); amountInput.min = "0.01"; amountInput.step = "0.01";
  const shares = current === "reimbursement" ? (this.pendingCashPurchase.purchase?.shares || []) : [];
  const remaining = () => {
    const selected = shares.find(s => s.id === this.pendingCashShareId);
    return Number(selected ? selected.outstanding : this.pendingCashPurchase?.purchase?.remaining_refundable || 0);
  };
  if (current === "reimbursement") amountInput.value = remaining().toFixed(2);
  grid.append(dateField, amountField);
  const availableCurrencies = current === "opening" ?
    CURRENCIES.filter(code => !(data.opening_currencies || []).includes(code)) : CURRENCIES;
  const code = current === "reimbursement" ? this.pendingCashPurchase.currency :
    availableCurrencies.includes(this.cashCurrency) ? this.cashCurrency : availableCurrencies[0];
  const currencyField = this.choice("Валюта", "currency",
    availableCurrencies.map(value => [value,value]), code);
  grid.append(currencyField);
  if (current === "reimbursement") {
    if (shares.length) {
      const person = this.choice("Кто вернул", "share_id", [["", "Выберите участника"], ...shares.map(s => [s.id, `${s.person} · осталось ${money(s.outstanding, this.pendingCashPurchase.currency)}`])], this.pendingCashShareId || "");
      person.querySelector("select").required = true;
      person.querySelector("select").onchange = event => {
        this.pendingCashShareId = event.target.value;
        amountInput.value = currencyField.querySelector("select").value === this.pendingCashPurchase.currency ? remaining().toFixed(2) : "";
      };
      grid.append(person);
    }
    const wallet = this.checkbox("Добавить полученные деньги в наличный кошелёк", "affects_wallet");
    wallet.classList.add("cash-wallet-choice"); grid.append(wallet);
    grid.append(this.el("p", "Без этой отметки запишется только возврат: остаток кошелька не изменится. Удобно, если наличные уже учтены в нём.", "muted"));
    currencyField.querySelector("select").onchange = event => {
      amountInput.value = event.target.value === this.pendingCashPurchase.currency ? remaining().toFixed(2) : "";
    };
  }
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
    if (current === "reimbursement" && (values.get("currency") !== "PLN" || this.pendingCashPurchase.currency !== "PLN"))
      await this.api("cash_fx_sync", { month:String(values.get("date")).slice(0, 7) });
    await this.api("cash_add", { kind: current, date: values.get("date"), amount: values.get("amount"),
      currency: values.get("currency") || "PLN",
      note: values.get("note") || "", ...(current === "reimbursement" ?
        { transaction_id: this.pendingCashPurchase.id, affects_wallet: values.has("affects_wallet"),
          ...(values.get("share_id") ? {share_id:values.get("share_id")} : {}) } : {}),
      ...(current === "expense" ? { category: values.get("category") || "", project: values.get("project") || "" } : {}) });
    this.pendingCashPurchase = null; this.pendingCashShareId = null; this.cashKind = "expense";
    this.cashCurrency = values.get("currency") || "PLN";
    await this.reloadPeriod(); this.status(current === "reimbursement" ?
      values.has("affects_wallet") ? "Возврат учтён и добавлен в кошелёк" : "Возврат учтён. Кошелёк не изменён" : "Наличные учтены", true);
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
    if (row.kind === "reimbursement") main.append(this.el("small", `${row.person ? row.person + " · " : ""}${row.affects_wallet ? "Добавлено в кошелёк" : "Кошелёк не изменён"}`));
    if (row.note) main.append(this.el("span", row.note, "muted"));
    if (row.currency !== "PLN") main.append(this.el("small", row.amount_pln == null ?
      "Курс для этой даты пока не получен" : `≈ ${money(row.amount_pln)} по курсу от ${row.rate_date}`));
    const amount = this.el("strong", money(row.amount, row.currency), Number(row.amount) >= 0 ? "cash-in" : "");
    const remove = this.el("button", "Удалить", "cash-remove"); remove.type = "button";
    remove.setAttribute("aria-label", `Удалить запись ${row.date} ${KIND[row.kind] || row.kind}`);
    remove.onclick = () => this.busy(async () => {
      if (!window.confirm(`Удалить запись «${KIND[row.kind] || row.kind}» на ${money(row.amount, row.currency)}?`)) return;
      await this.api("cash_delete", { id: row.id }); await this.reloadPeriod();
      this.status("Запись удалена", true);
    });
    item.append(main, amount, remove); list.append(item);
  }
  section.append(list); holder.append(section);
}
