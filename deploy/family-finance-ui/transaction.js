import { TYPE_INFO, categoryChoices, categoryLabel, isMortgageType, isMortgageCategory, reviewEconomicType, money, percent } from "./format.js";
import { renderPurchaseExtras } from "./purchase-returns.js";

export function renderTransaction(list, tx) {
    const row = this.el("article", undefined, "tx");
    row.dataset.transactionId = tx.id;
    if (tx.id === this.transactionId) row.classList.add("is-target");
    const title = this.el("div", undefined, "tx-head");
    const menu = this.el("details", undefined, "tx-menu");
    const menuButton = this.el("summary", "⋯");
    menuButton.setAttribute("aria-label", "Действия с операцией");
    menu.append(menuButton);
    const left = this.el("div");
    left.append(this.el("div", tx.date, "tx-date"));
    if (tx.booking_date && tx.booking_date !== tx.date)
      left.append(this.el("div", `Проведено банком ${tx.booking_date}`, "muted"));
    left.append(
      this.el("div", tx.bank_status !== "BOOK" ? "Ожидает проведения" :
        TYPE_INFO[tx.economic_type]?.[0] || tx.economic_type, "muted"));
    if (tx.bank_status === "BOOK") title.append(menu);
    title.append(left, this.el("div", money(tx.amount, tx.currency),
      Number(tx.amount) >= 0 ? "tx-amount in" : "tx-amount"));
    row.append(title, this.el("div", tx.description || "Без описания", "memo"));
    if (tx.bank_status !== "BOOK") {
      row.append(this.el("div", "Ожидает проведения банком. Сумма пока заблокирована; операция не входит в расходы и доходы. После проведения она появится как завершённая.", "banner warm"));
      this.appendReviewRow(list, row, tx);
      return;
    }
    if (tx.pair_status === "CONFIRMED") {
      row.append(this.el("div", "Подтверждённый свой перевод. В доходах и расходах не учитывается.", "banner good"));
      this.appendReviewRow(list, row, tx);
      return;
    }
    const dropdown = this.el("div", undefined, "tx-menu-panel"); menu.append(dropdown);
    if (renderPurchaseExtras.call(this, row, tx, dropdown)) {
      this.appendReviewRow(list, row, tx); return;
    }
    if (!tx.pair_status && Number(tx.amount) !== 0) {
      const side = Number(tx.amount) < 0 ? "debit" : "credit";
      const selected = this.pairSelection[side]?.id === tx.id;
      const pick = this.el("button", selected ? "Убрать из пары" :
        side === "debit" ? "Выбрать списание для своего перевода" :
          "Выбрать зачисление для своего перевода");
      pick.type = "button";
      pick.onclick = () => {
        this.pairSelection[side] = selected ? null : {
          id:tx.id, date:tx.date, amount:tx.amount, currency:tx.currency,
          description:tx.description || "Без описания" };
        this.render();
      };
      if (!tx.purchase?.shares?.length && !tx.purchase?.receipts?.length) dropdown.append(pick);
      if (side === "debit" &&
          ["consumption", "project_expense", "unclassified"].includes(tx.economic_type) &&
          (Number(tx.purchase?.remaining_refundable || 0) > 0 || tx.purchase?.shares?.some(s => Number(s.outstanding) > 0))) {
        const reimbursement = this.el("button", "Вернули наличными");
        reimbursement.type = "button";
        reimbursement.onclick = () => {
          this.pendingCashPurchase = tx; this.pendingCashShareId = null; this.cashKind = "reimbursement";
          this.tab = "cash"; this.drawTabs(); this.render();
          this.shadowRoot.querySelector(".nav")?.scrollIntoView({ behavior:"smooth", block:"start" });
        };
        dropdown.append(reimbursement);
      }
    }
    if (tx.suggestion) {
      const suggestion = this.el("div", undefined, "suggestion");
      const detail = this.el("div");
      detail.append(this.el("strong", `Подсказка: ${categoryLabel(tx.suggestion.category)}`),
        this.el("div", `Уверенность ${percent(tx.suggestion.confidence)} · вероятность ${tx.suggestion.economic_type === "external_income" ? "дохода" : "покупки"} ${percent(tx.suggestion.purchase_probability)}`, "muted"));
      const apply = this.el("button", "Применить подсказку", "primary"); apply.type = "button";
      apply.onclick = () => this.saveCorrection(tx, {
        category: tx.suggestion.category, project: tx.project,
        economic_type: tx.suggestion.economic_type }, apply, "Подсказка применена и сохранена");
      suggestion.append(detail, apply); row.append(suggestion);
    }
    const form = this.el("form", undefined, "form-grid");
    const isCredit = Number(tx.amount) > 0;
    const hasMortgage = Boolean(this.options.mortgages.length);
    const categories = this.options.categories.filter(path =>
      isCredit ? path.startsWith("Income/") :
        (path !== "Income" && !path.startsWith("Income/") &&
         (hasMortgage || !isMortgageCategory(path))));
    const categoryField = this.choice(isCredit ? "Категория дохода" : "Категория расхода",
      "category", [["","Выберите категорию"], ...categoryChoices(categories)], tx.category || "");
    const projectField = this.choice("Проект (если это разовая трата)", "project",
      [["","Без проекта"], ...this.options.projects.map(x => [x,x])], tx.project || "");
    if (isCredit) { projectField.hidden = true; projectField.querySelector("select").disabled = true; }
    const advanced = this.el("details", undefined, "advanced-type");
    advanced.append(this.el("summary", "Особый случай: перевод, обмен, инвестиции"));
    const specialTypes = isCredit ?
      ["investment_transfer", "fx_conversion", "external_transfer", "external_income"] :
      ["investment_transfer", "fx_conversion", "external_transfer",
        ...(hasMortgage ? ["mortgage_principal", "mortgage_interest"] : []), "project_expense"];
    const initialSpecial = specialTypes.includes(tx.economic_type) &&
      !(tx.economic_type === "project_expense" && tx.project) &&
      !(tx.economic_type === "mortgage_principal" && isMortgageCategory(tx.category)) &&
      !(tx.economic_type === "external_income" && tx.category?.startsWith("Income/")) ?
      tx.economic_type : "";
    const specialField = this.choice("Как учесть вручную", "special_type",
      [["","Автоматически по категории и проекту"],
        ...specialTypes.filter(key => this.options.economic_types.includes(key))
          .map(key => [key, TYPE_INFO[key][0]])], initialSpecial);
    advanced.append(specialField);
    if (initialSpecial) advanced.open = true;
    const hiddenType = this.el("input"); hiddenType.type = "hidden"; hiddenType.name = "economic_type";
    form.append(categoryField, projectField, advanced, hiddenType);
    const help = this.el("p", "", "muted type-help");
    const category = form.querySelector('[name="category"]');
    const project = form.querySelector('[name="project"]');
    const special = form.querySelector('[name="special_type"]');
    let mortgagePanel = null;
    let save = null;
    const updateMortgage = () => {
      if (mortgagePanel) mortgagePanel.hidden = !isMortgageType(hiddenType.value);
    };
    const updateHelp = () => {
      hiddenType.value = reviewEconomicType(tx.amount, category.value, project.value, special.value);
      help.textContent = hiddenType.value === "unclassified" ?
        "Выберите категорию дохода или откройте «Особый случай»." :
        !isCredit && !category.value && !project.value && !special.value ?
        "Выберите категорию расхода. Для своего перевода используйте меню ⋯." :
        `Будет учтено как «${TYPE_INFO[hiddenType.value]?.[0] || hiddenType.value}». ${TYPE_INFO[hiddenType.value]?.[1] || ""}`;
      if (save) {
        save.hidden = isMortgageType(hiddenType.value);
        save.disabled = hiddenType.value === "unclassified" ||
          (!isCredit && !category.value && !project.value && !special.value);
      }
      updateMortgage();
    };
    category.onchange = () => {
      special.value = "";
      if (isMortgageCategory(category.value)) project.value = "";
      updateHelp();
    };
    project.onchange = () => { if (project.value) special.value = ""; updateHelp(); };
    special.onchange = () => {
      if (isMortgageType(special.value)) {
        category.value = "Housing/Mortgage payment";
        project.value = "";
      } else if (["investment_transfer", "fx_conversion", "external_transfer"].includes(special.value)) {
        category.value = "";
        project.value = "";
      }
      updateHelp();
    };
    updateHelp(); form.append(help);
    save = this.el("button", "Сохранить разметку", "primary"); save.type = "submit";
    updateHelp();
    form.append(save);
    form.onsubmit = (event) => { event.preventDefault();
      if (isMortgageType(hiddenType.value)) return;
      const values = new FormData(form);
      this.saveCorrection(tx, { category: values.get("category"), project: values.get("project"),
        economic_type: values.get("economic_type") }, save, "Разметка сохранена"); };
    row.append(form);
    if (Number(tx.amount) < 0 && hasMortgage) {
      mortgagePanel = this.el("div", undefined, "mortgage-panel");
      mortgagePanel.append(this.el("p", "Сохраните платёж вместе с разбивкой ниже. Для обычного платежа возьмите тело, проценты и комиссию из банка; для досрочного нажмите «Всё в тело». Сумма частей должна совпасть со списанием.", "muted"));
      if (!this.options.mortgages.length) {
        const setup = this.el("div", "Сначала добавьте ипотеку с названием и валютой в разделе «Настройки и ввод».", "banner");
        const go = this.el("button", "Перейти к настройкам", "primary"); go.type = "button";
        go.onclick = () => { this.tab = "inputs"; this.drawTabs(); this.render(); };
        setup.append(go); mortgagePanel.append(setup);
      } else {
        const split = this.form("Части платежа", [
        this.choice("Ипотека", "mortgage", this.options.mortgages.map(x => [x.name,x.name])),
        this.field("Тело", "principal", "number"), this.field("Проценты", "interest", "number", "0"),
        this.field("Комиссия", "fees", "number", "0"),
        this.checkbox("Исправить существующую разбивку", "replace_existing")
      ], async f => {
        const selection = new FormData(form);
        const principal = f.get("principal");
        const interest = f.get("interest") || "0";
        const fees = f.get("fees") || "0";
        if (!principal) throw new Error("Укажите сумму, ушедшую в тело кредита.");
        const cents = value => Math.round(Number(value) * 100);
        if (cents(principal) + cents(interest) + cents(fees) !== cents(Math.abs(Number(tx.amount))))
          throw new Error(`Сумма тела, процентов и комиссии должна быть ${money(Math.abs(Number(tx.amount)), tx.currency)}.`);
        return this.api("correct_mortgage", { transaction_id:tx.id,
          category:selection.get("category") || null, project:selection.get("project") || null,
          economic_type:selection.get("economic_type"), mortgage:f.get("mortgage"),
          principal, interest, fees,
          replace_existing:f.has("replace_existing") });
      });
        split.querySelector('button[type="submit"]').textContent = "Сохранить платёж и разбивку";
        const early = this.el("button", "Всё в тело — досрочное погашение"); early.type = "button";
        early.onclick = () => {
          const fields = split.querySelector("form").elements;
          fields.namedItem("principal").value = String(Math.abs(Number(tx.amount)).toFixed(2));
          fields.namedItem("interest").value = "0";
          fields.namedItem("fees").value = "0";
        };
        split.querySelector("form").prepend(early);
        mortgagePanel.append(split);
      }
      row.append(mortgagePanel);
      updateMortgage();
    }
    this.appendReviewRow(list, row, tx);
}
