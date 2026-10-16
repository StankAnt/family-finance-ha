import { TYPE_CHOICES, categoryChoices } from "./format.js";
import { renderOnboarding } from "./onboarding.js";

export function renderInputs(holder) {
    const today = new Date().toLocaleDateString("sv-SE");
    const [year, periodMonth] = this.month.split("-").map(Number);
    const monthEnd = new Date(Date.UTC(year, periodMonth, 0)).toISOString().slice(0, 10);
    const balanceDate = monthEnd < today ? monthEnd : today;
    holder.append(this.heading("Настройки и ввод", "Категории, проекты, правила, оценки и цели семьи."));
    renderOnboarding.call(this, holder);
    holder.append(this.el("p", "Все изменения сохраняются локально. Для исправления записи за ту же дату отметьте соответствующий флажок; старое значение останется в журнале.", "muted"));
    const notifications = this.el("section", undefined, "surface");
    notifications.append(this.el("h3", "Уведомления"),
      this.el("p", "Проверьте доставку на iPhone без обращения к банку. Сигнал пройдёт через MQTT и правило Home Assistant.", "muted"));
    const testPush = this.el("button", "Отправить тестовый пуш", "primary");
    testPush.type = "button";
    const testResult = this.el("p", "", "muted");
    testPush.onclick = async () => {
      testPush.disabled = true;
      testResult.textContent = "Отправляем тестовый сигнал…";
      try {
        await this.api("test_notification");
        testResult.textContent = "Тестовый сигнал передан в Home Assistant. Проверьте уведомление на iPhone.";
      } catch (error) {
        testResult.textContent = error.message || "Не удалось отправить тестовый сигнал.";
      } finally { testPush.disabled = false; }
    };
    notifications.append(testPush, testResult); holder.append(notifications);
    holder.append(this.form("Новая категория", [this.field("Название", "name"),
      this.choice("Родитель", "parent", [["","Корневая категория"], ...categoryChoices(this.options.categories)])],
      async f => this.api("category", {name:f.get("name"), parent:f.get("parent") || null})));
    holder.append(this.form("Новый проект", [this.field("Название", "name")],
      async f => this.api("project", {name:f.get("name")})));
    holder.append(this.form("Правило классификации", [this.field("Шаблон (регулярное выражение)", "pattern"),
      this.choice("Категория", "category", [["","Без категории"], ...categoryChoices(this.options.categories)]),
      this.choice("Проект", "project", [["","Без проекта"], ...this.options.projects.map(x => [x,x])]),
      this.field("Приоритет", "priority", "number", "100"),
      this.choice("Направление", "direction", [["debit","Расход"],["credit","Приход"],["any","Любое"]]),
      this.choice("Тип", "economic_type", TYPE_CHOICES.filter(([key]) => this.options.economic_types.includes(key) &&
        (this.options.mortgages.length || !["mortgage_principal", "mortgage_interest"].includes(key))), "consumption")],
      async f => this.api("rule", {pattern:f.get("pattern"), category:f.get("category") || null,
        project:f.get("project") || null, priority:f.get("priority"), direction:f.get("direction"),
        economic_type:f.get("economic_type") })));
    if (this.options.accounts?.length) {
      holder.append(this.el("p", "Для прошлых месяцев банк не передаёт исторические остатки. Впишите точный учётный остаток по каждому счёту на конец месяца; текущий остаток нельзя переносить назад. Последний доступный остаток помогает отличить счета с одинаковым именем.", "muted"));
      const balanceAmount = this.field("Учётный остаток", "amount", "number");
      balanceAmount.querySelector("input").removeAttribute("min");
      holder.append(this.form("Остаток счёта на выбранную дату", [
        this.choice("Счёт", "account_id", this.options.accounts.map(x => [x.id, x.label])),
        this.field("Дата остатка", "as_of", "date", balanceDate),
        balanceAmount,
        this.checkbox("Исправить ручную запись за эту дату", "replace_existing")],
        async f => this.api("manual", {account_balances:[{account_id:f.get("account_id"),
          as_of:f.get("as_of"), amount:f.get("amount")}],
          replace_existing:f.has("replace_existing")})));
    }
    const mortgageSetup = this.el("details", undefined, "surface");
    mortgageSetup.append(this.el("summary", this.options.mortgages.length ? "Добавить ещё ипотеку" : "Есть ипотека? Добавить её"));
    mortgageSetup.append(this.form("Ипотека", [this.field("Название", "name"),
      this.choice("Валюта", "currency", [["PLN","PLN"],["EUR","EUR"],["USD","USD"]])],
      async f => this.api("manual", {mortgages:[{name:f.get("name"), currency:f.get("currency") }]})));
    holder.append(mortgageSetup);
    if (this.options.mortgages.length) {
      holder.append(this.el("p", "Введите подтверждённый банком остаток на дату после всех платежей этого дня. После этой даты система будет вычитать из него размеченное погашение тела. Новая запись остатка станет новой точкой отсчёта и не учтёт те же платежи повторно.", "muted"));
      holder.append(this.form("Остаток ипотеки по данным банка", [
      this.choice("Ипотека", "name", this.options.mortgages.map(x => [x.name, x.name])),
      this.field("Дата остатка", "as_of", "date", today),
      this.field("Остаток долга", "amount", "number"),
      this.checkbox("Оценка приблизительная", "estimated"),
      this.checkbox("Исправить запись за эту дату", "replace_existing")],
      async f => {
        const mortgage = this.options.mortgages.find(x => x.name === f.get("name"));
        return this.api("manual", {valuations:[{kind:"mortgage_debt", name:mortgage.name,
          as_of:f.get("as_of"), amount:f.get("amount"), currency:mortgage.currency,
          estimated:f.has("estimated")}], replace_existing:f.has("replace_existing")});
      }));
    }
    holder.append(this.form("Другие активы и долги", [
      this.choice("Тип", "kind", [["property","Недвижимость"],["investment","Инвестиции"],["other_asset","Другой актив"],["other_debt","Другой долг"]]),
      this.field("Название", "name"), this.field("Дата", "as_of", "date", today),
      this.field("Сумма", "amount", "number"),
      this.choice("Валюта", "currency", [["PLN","PLN"],["EUR","EUR"],["USD","USD"]]),
      this.checkbox("Оценка приблизительная", "estimated"),
      this.checkbox("Исправить запись за эту дату", "replace_existing")],
      async f => this.api("manual", {valuations:[{kind:f.get("kind"), name:f.get("name"), as_of:f.get("as_of"),
        amount:f.get("amount"), currency:f.get("currency"), estimated:f.has("estimated") }],
        replace_existing:f.has("replace_existing")})));
    holder.append(this.form("Новая цель", [this.field("Название", "name"),
      this.field("Целевая сумма", "target_amount", "number"),
      this.choice("Валюта", "currency", [["PLN","PLN"],["EUR","EUR"],["USD","USD"]]),
      this.field("Срок (необязательно)", "target_date", "date"),
      this.checkbox("Исправить существующую цель", "replace_existing")],
      async f => this.api("manual", {goals:[{name:f.get("name"), target_amount:f.get("target_amount"),
        currency:f.get("currency"), target_date:f.get("target_date") || null }],
        replace_existing:f.has("replace_existing")})));
    if (this.options.goals.length) holder.append(this.form("Прогресс цели", [
      this.choice("Цель", "goal", this.options.goals.map(x => [x.name,x.name])),
      this.field("Дата", "as_of", "date", today), this.field("Сумма", "amount", "number"),
      this.checkbox("Оценка приблизительная", "estimated"),
      this.checkbox("Исправить запись за эту дату", "replace_existing")],
      async f => this.api("manual", {goal_progress:[{goal:f.get("goal"), as_of:f.get("as_of"),
        amount:f.get("amount"), estimated:f.has("estimated") }],
        replace_existing:f.has("replace_existing")})));
    holder.append(this.form("Полнота семейных данных", [this.field("Дата", "as_of", "date", today),
      this.checkbox("Все счета семьи учтены", "accounts_complete"),
      this.checkbox("Все активы учтены", "assets_complete"),
      this.checkbox("Все долги учтены", "liabilities_complete"),
      this.checkbox("Исправить отметки за эту дату", "replace_existing")],
      async (f, form) => {
        if (f.has("accounts_complete") && f.has("assets_complete") && f.has("liabilities_complete") &&
            !window.confirm("Подтвердить, что все счета, активы и долги всей семьи учтены?")) throw new Error("Подтверждение отменено");
        return this.api("manual", {coverage:[{as_of:f.get("as_of"), accounts_complete:f.has("accounts_complete"),
          assets_complete:f.has("assets_complete"), liabilities_complete:f.has("liabilities_complete") }],
          replace_existing:f.has("replace_existing")});
      }));
}
