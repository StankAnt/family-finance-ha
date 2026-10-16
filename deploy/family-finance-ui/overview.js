import { renderCharts } from "./charts.js";
import { money, monthTitle } from "./format.js";

export function renderOverview(holder) {
  const month = this.overview.month, position = this.overview.position, a = month.amounts_pln;
  const hasMortgage = Boolean(this.options?.mortgages?.length);
  holder.append(this.heading(`Обзор · ${monthTitle(month.period)}`,
    "Реальные счета. Месячные суммы считаются по дате проведения банком; в списке операций показывается дата покупки, если банк её передал. Суммы в PLN."));
  if (this.source === "production" && !this.overview.source_status?.transactions) {
    holder.append(this.el("div", "Операции ещё не загружены из банка. Нажмите «Обновить реальные операции» ниже.", "banner"));
  }
  if (this.source === "production" && this.overview.source_status?.last_sync === "FAILED") {
    holder.append(this.el("div", "Последнее обновление банка не завершилось. Данные могут быть неполными; проверьте сообщение об ошибке перед повтором.", "banner"));
  }
  const complete = month.living_cost_complete;
  const banner = this.el("div", complete ? "Расходы за месяц размечены. Отчёт можно использовать для сравнения." :
    `Отчёт предварительный: ${month.counts.unclassified || 0} операций без типа${hasMortgage ? `, ${month.counts.mortgage_unallocated || 0} ипотечных платежей без разбивки` : ""} и ${month.counts.missing_fx || 0} без курса валюты.`,
    complete ? "banner good" : "banner");
  holder.append(banner);
  if (month.counts.unclassified) {
    const review = this.el("button", `Разметить операции (${month.counts.unclassified})`, "primary review-shortcut");
    review.type = "button";
    review.onclick = async () => {
      Object.assign(this, { tab: "review", filter: "unclassified", reviewScope: "month",
        search: "", categoryFilter: "", projectFilter: "", page: 0, transactionId: "" });
      await this.busy(async () => { await this.loadReview(); this.drawTabs(); this.render(); });
    };
    holder.append(review);
  }
  const bank = this.el("section", undefined, "surface");
    bank.append(this.el("h3", "Банковские счета"), this.el("p",
      "Проверить типы доступных счетов по вашему нажатию. Эта проверка не загружает операции.", "muted"));
  const check = this.el("button", "Проверить доступные счета", "primary");
  check.type = "button";
  check.onclick = async () => {
    check.disabled = true; check.textContent = "Проверяем…";
    await this.busy(async () => {
      this.bankAccounts = await this.api("bank_accounts");
      this.render();
    }, "Проверка счетов завершена");
    check.disabled = false; check.textContent = "Проверить доступные счета";
  };
  bank.append(check);
  const sync = this.el("button", "Обновить реальные операции", "primary");
  sync.type = "button";
  sync.onclick = async () => {
    sync.disabled = true; sync.textContent = "Загружаем операции…";
    await this.busy(async () => {
      const result = await this.api("bank_sync");
      await this.reloadPeriod();
      await this.refreshAiStatus();
      this.status(`Загружено счетов: ${result.accounts}, операций просмотрено: ${result.transactions_seen}. Классификация OpenAI ${result.ai_started ? "запущена" : "уже выполняется"}.${result.fx_rates_updated === false ? " Курсы валют не обновились; валютные суммы пока неполные." : ""}`, true);
    });
    sync.disabled = false; sync.textContent = "Обновить реальные операции";
  };
  bank.append(sync, this.el("p", "При первой загрузке запрашиваются последние 90 дней, затем только новые операции. Это может занять несколько минут. При лимите банка загрузка остановится.", "muted"));
  const ai = this.el("section", undefined, "surface");
  ai.append(this.el("h3", "Классификация OpenAI"));
  if (!this.setupStatus?.ai_enabled) {
    ai.append(this.el("p", "Классификация выключена. При желании включите её в разделе «Настройки и ввод».", "muted"));
  } else {
  const aiState = this.aiStatus?.state || "idle";
  const aiSummary = aiState === "running" ?
    `Обработка идёт: проверено ${this.aiStatus.sent}, предложено ${this.aiStatus.proposed}, применено автоматически ${this.aiStatus.applied}.` :
    aiState === "complete" ?
    `Обработка завершена: проверено ${this.aiStatus.sent}, предложено ${this.aiStatus.proposed}, применено автоматически ${this.aiStatus.applied}.` :
    aiState === "failed" ? `Обработка остановилась: ${this.aiStatus.error || "ошибка"}` :
    this.overview.source_status?.ai_checked ?
    `Ранее проверено ${this.overview.source_status.ai_checked} операций; ${this.overview.source_status.ai_applied} категорий применено автоматически. Можно проверить оставшиеся.` :
    "Реальные операции ещё не проверялись через OpenAI.";
  ai.append(this.el("p", aiSummary, "muted"));
  const learning = this.overview.source_status;
  ai.append(this.el("p", `Ручных исправлений: ${learning.manual_corrections || 0} · автоматически размечено по ним: ${learning.learned_matches || 0} · применено через OpenAI: ${learning.ai_applied || 0}. Проверяйте новые операции в разделе «Операции»: эти счётчики показывают охват, а не точность.`, "muted"));
  if (aiState !== "running") {
    const aiStart = this.el("button", "Обработать оставшиеся операции", "primary");
    aiStart.type = "button";
    aiStart.onclick = () => this.busy(async () => {
      await this.api("ai_start");
      await this.refreshAiStatus();
    });
    ai.append(aiStart);
  }
  ai.append(this.el("p", "В OpenAI уходят текст получателя и назначение; номера счетов, карт и email скрываются. Суммы и даты остаются здесь. Покупки и внешние доходы применяются автоматически при уверенности и вероятности от 75%.", "muted"));
  }
  if (this.bankAccounts) {
    const names = { CACC: "Текущие", CASH: "Наличные", CARD: "Карточные",
      LOAN: "Кредитные", SVGS: "Сберегательные", OTHR: "Другие", UNKNOWN: "Неизвестный тип" };
    const kinds = Object.entries(this.bankAccounts.types || {})
      .map(([kind, count]) => `${names[kind] || kind}: ${count}`).join(" · ");
    bank.append(this.el("p", `Доступно счетов: ${this.bankAccounts.account_count}. Кредитных: ${this.bankAccounts.types?.LOAN || 0}. ${kinds}`, "muted"));
  }
  const outgoing = this.el("section", undefined, "surface outgoing-summary");
  outgoing.append(this.el("h3", "Сколько денег ушло за месяц"));
  const outgoingMetrics = this.el("div", undefined, "metrics");
  outgoingMetrics.append(
    this.metric("Все исходящие платежи", money(a.outflows_total || 0),
      "Включая наличные покупки, ипотеку целиком и перечисления в инвестиции. Свои переводы и обмен валюты исключены"),
    this.metric(hasMortgage ? "Без ипотеки и инвестиций" : "Без инвестиций", money(a.outflows_without_mortgage_investments || 0),
      `${month.counts.unclassified_debits || 0} неразмеченных списаний включены предварительно; среди них ещё могут быть свои переводы`, "warm"));
  outgoing.append(outgoingMetrics);
  const mortgageCost = Number(a.mortgage_interest || 0) + Number(a.mortgage_fees || 0);
  outgoing.append(this.el("p",
    hasMortgage ?
      `Сверка: ${money(a.outflows_total || 0)} = ${money(a.outflows_without_mortgage_investments || 0)} без ипотеки и инвестиций + ${money(a.outflows_mortgage || 0)} вся ипотека + ${money(a.outflows_investments || 0)} инвестиции. Из ипотеки: ${money(a.mortgage_principal_confirmed || 0)} в тело и ${money(mortgageCost)} проценты и комиссии${month.counts.mortgage_unallocated ? `; ${month.counts.mortgage_unallocated} платежей ещё без разбивки` : ""}.` :
      `Сверка: ${money(a.outflows_total || 0)} = ${money(a.outflows_without_mortgage_investments || 0)} без инвестиций + ${money(a.outflows_investments || 0)} инвестиции.`,
    "muted outgoing-equation"));
  holder.append(outgoing);
  const metrics = this.el("div", undefined, "metrics");
  metrics.append(
    this.metric("Доходы извне", money(a.external_income || 0),
      month.counts.missing_fx ? "Учтённые доходы; есть операции без курса валюты" :
        month.counts.unclassified_credits ? `${month.counts.unclassified_credits} поступлений на ${money(a.unclassified_receipts || 0)} ещё требуют разметки` :
          "Поступления не со своих счетов"),
    this.metric("Разовые проекты", money(a.exceptional_projects || 0),
      hasMortgage ? "Уже входят в сумму без ипотеки и инвестиций" : "Уже входят в сумму без инвестиций", "warm"),
    this.metric("Перечислено в инвестиции", money(a.investment_contributions || 0),
      hasMortgage ? "Уже входит во все исходящие платежи; не входит в сумму без ипотеки и инвестиций" :
        "Уже входит во все исходящие платежи; не входит в сумму без инвестиций", "soft"),
    this.metric("Денежный поток", money(a.cashflow || 0),
      "Банковские движения плюс полученные и потраченные наличные; это не сумма расходов", "soft")
  );
  if (hasMortgage) metrics.insertBefore(this.metric("В тело ипотеки за месяц", money(a.mortgage_principal_confirmed || 0),
    `По разбивке ${month.counts.mortgage_allocated || 0} платежей${month.counts.mortgage_unallocated ? `; ещё ${month.counts.mortgage_unallocated} без разбивки` : ""}. Уже входит в «всю ипотеку» выше`, "soft"), metrics.children[2]);
  holder.append(metrics);
  renderCharts.call(this, holder, month);
  const capital = this.el("section", undefined, "surface");
  capital.append(this.el("h3", `Капитал на ${position.as_of}`));
  const current = this.el("div", undefined, "metrics");
  current.append(this.metric("Деньги на счетах", money(position.liquid_savings_pln),
    position.missing_components?.includes("account_balance_estimated") ?
      "Оценка на конец месяца: от более поздних остатков отняты последующие операции" :
      "По учётным остаткам; сумма в PLN требует курсы валют"));
  const cashMetric = this.metric("Наличные", position.cash_on_hand_pln == null ? "Нет курса" : money(position.cash_on_hand_pln),
    Object.entries(position.cash_on_hand_by_currency || {}).map(([code, value]) => money(value, code)).join(" · ") ||
      "Учтённый остаток семейного кошелька", "soft");
  cashMetric.classList.add("cash-link"); cashMetric.tabIndex = 0; cashMetric.setAttribute("role", "link");
  cashMetric.onclick = () => { this.tab = "cash"; this.drawTabs(); this.render(); };
  cashMetric.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); cashMetric.click(); } };
  current.append(cashMetric);
  if (hasMortgage) current.append(this.metric("Остаток ипотеки", position.mortgage_debts?.length === 1 ?
      money(position.mortgage_debts[0].amount, position.mortgage_debts[0].currency) :
      position.mortgage_debts?.length && !position.missing_components?.includes("valuation_fx") ?
        money(position.components_pln?.mortgage_debt) : "Нет данных",
      position.mortgage_debts?.length === 1 ? `По вашей записи от ${position.mortgage_debts[0].as_of}` :
        "Добавьте остаток долга в разделе «Настройки и ввод»", "warm"));
  current.append(this.metric("Капитал семьи", position.complete ? money(position.net_worth_pln) : "Нет полного отчёта",
    position.complete ? "Все компоненты учтены" : "Требуются оценки активов, долгов и подтверждение охвата", "soft"));
  capital.append(current);
  if (position.accounts?.length) {
    const accounts = this.el("div", undefined, "account-list");
    for (const account of position.accounts) {
      const item = this.el("div", undefined, "account-row");
      item.append(this.el("strong", account.name),
        this.el("span", account.booked == null ? "Учётный остаток не получен" : money(account.booked, account.currency)),
        this.el("small", account.as_of ?
          `${account.as_of}${account.balance_source === "manual" ? " · введено вручную" : account.balance_source === "calculated" ? ` · расчётная оценка по остатку от ${account.balance_basis_date}` : ""}${account.available == null ? "" : ` · доступно ${money(account.available, account.currency)}`}` :
          account.next_balance_date ? `Первый сохранённый остаток доступен с ${account.next_balance_date}; автоматически восстановить выбранную дату пока нельзя` :
            "Остаток на эту дату не указан"));
      accounts.append(item);
    }
    capital.append(this.el("h3", "Счета и остатки"), accounts);
  }
  if (position.missing_components?.includes("account_balance_estimated")) capital.append(this.el("p",
    "Остатки за прошлый месяц восстановлены из последующих банковских остатков и сохранённых операций. Это оценка: поздние проводки могут её изменить.", "banner"));
  if (position.missing_components?.includes("account_balance")) capital.append(this.el("p",
    "Для выбранной даты не хватает остатков по части счетов или история операций слишком старая для надёжного расчёта.", "banner"));
  const missing = (position.missing_components || []).filter(x => hasMortgage || x !== "mortgage_debt");
  if (missing.length) capital.append(this.el("p",
    `Для полного расчёта недостаёт: ${missing.map(x => ({account_fx:"курс валюты для счетов",cash_fx:"курс валюты для наличных",account_balance:"остаток счёта",account_balance_estimated:"подтверждённые остатки на эту дату",investment:"оценка инвестиций",property:"оценка недвижимости",mortgage_debt:"остаток ипотечного долга"}[x] || x)).join(", ")}.`, "muted"));
  if (hasMortgage) {
  const mortgage = this.el("div", undefined, "mortgage-guide");
  mortgage.append(this.el("h3", "Как учитывать ипотеку"),
    this.el("p", `Ипотек настроено: ${this.overview.source_status?.mortgages || 0}; платежей разбито: ${this.overview.source_status?.mortgage_allocations || 0}.`, "muted"),
    this.el("p", "1. В настройках добавьте ипотеку. 2. У платежа выберите тип «Ипотека — платёж или тело». 3. Для обычного платежа впишите тело, проценты и комиссию из банковской выписки или графика; сумма частей должна равняться списанию. Для досрочного платежа нажмите «Всё в тело». 4. Обновляйте остаток ипотечного долга в настройках: банк не передаёт разбивку этого списания.", "muted"));
  capital.append(mortgage);
  }
  if (position.goals?.length) {
    const goals = this.el("div", undefined, "list");
    for (const goal of position.goals) {
      const row = this.el("div", undefined, "list-row");
      row.append(this.el("span", goal.name), this.el("strong",
        `${goal.progress == null ? "—" : money(goal.progress, goal.currency)} / ${money(goal.target, goal.currency)}`));
      goals.append(row);
    }
    capital.append(this.el("h3", "Цели"), goals);
  }
  holder.append(capital);
  if (this.source === "production") holder.append(bank, ai);
}
