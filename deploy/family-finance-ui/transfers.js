import { money } from "./format.js";

export function renderTransfers(holder) {
  holder.append(this.heading("Свои переводы", "Подтверждённый перевод между своими счетами не считается доходом или расходом."));
  const rows = this.transfers?.rows || [];
  if (!rows.length) holder.append(this.el("div", "Сейчас нет пар переводов для проверки.", "surface empty"));
  for (const pair of rows) {
    const card = this.el("article", undefined, "tx");
    for (const leg of [pair.debit, pair.credit]) {
      const title = this.el("div", undefined, "tx-head");
      title.append(this.el("span", leg.date, "tx-date"), this.el("strong", money(leg.amount, leg.currency)));
      card.append(title, this.el("div", leg.description || "Без описания", "memo"));
    }
    const actions = this.el("div", undefined, "actions");
    for (const [confirm, label] of [[true,"Подтвердить свой перевод"],[false,"Это не пара"]]) {
      const button = this.el("button", label, confirm ? "primary" : "");
      button.onclick = async () => {
        button.disabled = true;
        await this.busy(async () => {
          await this.api("decide_transfer", { pair_id:pair.id, confirm });
          [this.transfers, this.overview] = await Promise.all([
            this.api("transfers"), this.api("overview", { month:this.month })]);
          await this.loadReview(); this.render();
        }, "Решение сохранено");
        button.disabled = false;
      };
      actions.append(button);
    }
    card.append(actions); holder.append(card);
  }
}
