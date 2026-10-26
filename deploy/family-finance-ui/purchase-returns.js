import { money } from "./format.js";

export function selectReturn(side, tx) {
  this.returnSelection ||= {};
  this.returnSelection[side] = tx;
  this.render();
  this.shadowRoot.querySelector(".return-selection")?.scrollIntoView({ behavior:"smooth", block:"center" });
}

export function renderReturnSelection(holder) {
  const selection = this.returnSelection;
  if (!selection?.purchase && !selection?.credit) return;
  const panel = this.el("section", undefined, "surface return-selection");
  panel.append(this.el("h3", "Связать возврат с покупкой"),
    this.el("p", "Выберите покупку и поступление через меню ⋯. Можно менять месяц, поиск и фильтры — выбранные операции сохранятся до подтверждения.", "muted"));
  for (const [key, label] of [["purchase", "Покупка"], ["credit", "Поступление"]]) {
    const tx = selection[key];
    panel.append(this.el("p", tx ? `${label}: ${tx.date} · ${money(tx.amount, tx.currency)} · ${tx.description}` : `${label}: выберите операцию`));
  }
  const kind = this.choice("Что вернули", "return_kind", [["store_refund", "Возврат из магазина"], ["reimbursement", "Вернули за другого человека"]], selection.kind || "store_refund");
  kind.querySelector("select").onchange = event => { selection.kind = event.target.value; this.render(); };
  panel.append(kind);
  const shares = selection.purchase?.purchase?.shares || [];
  let participant;
  if ((selection.kind || "store_refund") === "reimbursement" && shares.length) {
    participant = this.choice("Кто вернул", "return_person", [["", "Выберите участника"], ...shares.map(s => [s.id, `${s.person} · осталось ${money(s.outstanding, selection.purchase.currency)}`])]);
    panel.append(participant);
  }
  panel.append(this.el("p", "Возврат магазина уменьшит расходы месяца исходной покупки, включая её категорию и проект. В денежном потоке поступление останется на фактической дате. Возврат участника погасит его долг.", "muted"));
  const actions = this.el("div", undefined, "onboarding-actions");
  const confirm = this.el("button", "Подтвердить связь", "primary"); confirm.type = "button";
  confirm.disabled = !selection.purchase || !selection.credit;
  confirm.onclick = () => this.busy(async () => {
    const shareId = participant?.querySelector("select").value;
    if (participant && !shareId) throw new Error("Выберите участника");
    await this.api("return_link", { purchase_id:selection.purchase.id, credit_id:selection.credit.id,
      kind:selection.kind || "store_refund", ...(shareId ? {share_id:shareId} : {}) });
    this.returnSelection = null; await this.reloadPeriod(); this.status("Возврат связан с покупкой", true);
  });
  const cancel = this.el("button", "Отменить выбор"); cancel.type = "button";
  cancel.onclick = () => { this.returnSelection = null; this.render(); };
  actions.append(confirm, cancel); panel.append(actions); holder.append(panel);
}

export function renderPurchaseExtras(row, tx, dropdown) {
  if (tx.linked_return) {
    const link = tx.linked_return;
    const box = this.el("section", undefined, "purchase-summary");
    box.append(this.el("strong", link.kind === "store_refund" ? "Возврат покупки — доходом не считается" : "Возврат за другого человека — доходом не считается"),
      this.el("p", `Покупка от ${link.date}: ${link.description}`));
    const unlink = this.el("button", "Отменить связь"); unlink.type = "button";
    unlink.onclick = () => this.busy(async () => {
      if (!window.confirm("Отменить связь? Исходная разметка поступления восстановится.")) return;
      await this.api("return_unlink", {id:link.id}); await this.reloadPeriod();
    });
    box.append(unlink); row.append(box); return true;
  }
  const eligibleCredit = Number(tx.amount) > 0 && ["unclassified", "external_income", "external_transfer"].includes(tx.economic_type);
  if (!tx.pair_status && (tx.purchase || eligibleCredit)) {
    const pick = this.el("button", tx.purchase ? "Выбрать покупку для возврата" : "Это возврат по покупке…"); pick.type = "button";
    pick.onclick = () => selectReturn.call(this, tx.purchase ? "purchase" : "credit", tx);
    dropdown.append(pick);
  }
  if (tx.purchase && !tx.pair_status) {
    const split = this.el("button", tx.purchase.shares.length ? "Изменить доли участников" : "Оплатил за других…"); split.type = "button";
    split.onclick = () => { this.editSharedPurchase = this.editSharedPurchase === tx.id ? null : tx.id; this.render(); };
    dropdown.append(split);
    const details = tx.purchase;
    if (details.shares.length || details.receipts.length) {
      const box = this.el("section", undefined, "purchase-summary");
      box.append(this.el("strong", `Покупка: ${money(Math.abs(Number(tx.amount)), tx.currency)} · итоговый личный расход: ${money(details.remaining_refundable, tx.currency)}`));
      for (const share of details.shares) {
        const line = this.el("div", undefined, "purchase-person");
        line.append(this.el("strong", share.person), this.el("span", `${money(share.amount, tx.currency)} · вернул ${money(share.paid, tx.currency)} · осталось ${money(share.outstanding, tx.currency)}`));
        if (Number(share.outstanding) > 0) {
          const cash = this.el("button", "Вернул наличными"); cash.type = "button";
          cash.onclick = () => { this.pendingCashPurchase = tx; this.pendingCashShareId = share.id;
            this.cashKind = "reimbursement"; this.tab = "cash"; this.drawTabs(); this.render(); };
          line.append(cash);
        }
        box.append(line);
      }
      for (const receipt of details.receipts) {
        const line = this.el("div", undefined, "purchase-receipt");
        line.append(this.el("span", `${receipt.date} · ${money(receipt.amount, receipt.currency)} · ${receipt.person || (receipt.kind === "store_refund" ? "возврат магазина" : "возврат за покупку")} · ${receipt.method === "bank" ? "на счёт" : receipt.affects_wallet ? "в наличные" : "без изменения кошелька"}`));
        if (receipt.method === "bank") {
          const undo = this.el("button", "Отменить связь"); undo.type = "button";
          undo.onclick = () => this.busy(async () => {
            if (!window.confirm("Отменить связь этого возврата?")) return;
            await this.api("return_unlink", {id:receipt.id}); await this.reloadPeriod();
          });
          line.append(undo);
        }
        box.append(line);
      }
      row.append(box);
    }
    if (this.editSharedPurchase === tx.id) renderSharesEditor.call(this, row, tx);
  }
  if (tx.return_candidates?.length && !tx.pair_status) {
    const suggestions = this.el("section", undefined, "purchase-summary return-suggestions");
    suggestions.append(this.el("strong", "Возможно, это возврат по покупке"),
      this.el("p", "Похожий магазин, подходящие сумма, валюта и дата. Проверьте покупку перед подтверждением.", "muted"));
    for (const candidate of tx.return_candidates) {
      const button = this.el("button", `${candidate.date} · ${money(candidate.amount, candidate.currency)} · ${candidate.description}`); button.type = "button";
      button.onclick = () => { this.returnSelection = {purchase:candidate, credit:tx, kind:"store_refund"}; this.render();
        this.shadowRoot.querySelector(".return-selection")?.scrollIntoView({behavior:"smooth",block:"center"}); };
      suggestions.append(button);
    }
    row.append(suggestions);
  }
  return false;
}

function renderSharesEditor(row, tx) {
  const form = this.el("form", undefined, "purchase-summary");
  form.append(this.el("h3", "Часть покупки оплачена за других"),
    this.el("p", `Укажите только чужие доли в ${tx.currency}. Остальное — ваша часть. Долги входят в активы семьи и уменьшаются по мере возврата.`, "muted"));
  const entries = this.el("div", undefined, "purchase-share-editor");
  const own = this.el("p", "", "muted");
  const legacy = tx.purchase.receipts.filter(r => !r.person && (r.method === "cash" || r.kind === "reimbursement"));
  const assignments = this.el("div", undefined, "purchase-assignments");
  const update = () => {
    const total = [...entries.querySelectorAll('[name="share_amount"]')].reduce((sum, input) => sum + Number(input.value || 0), 0);
    own.textContent = `Ваша часть до возвратов магазина: ${money(Math.abs(Number(tx.amount)) - total, tx.currency)}`;
    const names = [...entries.querySelectorAll('[name="person"]')].map(input => input.value.trim()).filter(Boolean);
    for (const select of assignments.querySelectorAll("select")) {
      const selected = select.value;
      select.replaceChildren();
      for (const name of ["", ...new Set(names)]) {
        const option = this.el("option", name || "Выберите участника"); option.value = name;
        select.append(option);
      }
      select.value = names.includes(selected) ? selected : "";
    }
  };
  const add = (person = "", amount = "") => {
    const line = this.el("div", undefined, "purchase-share-inputs");
    const name = this.field("Кто должен вернуть", "person"); name.querySelector("input").value = person;
    const sum = this.field(`Сумма, ${tx.currency}`, "share_amount", "number");
    const input = sum.querySelector("input"); input.min = "0.01"; input.step = "0.01"; input.value = amount;
    const remove = this.el("button", "Убрать"); remove.type = "button"; remove.onclick = () => { line.remove(); update(); };
    line.append(name, sum, remove); entries.append(line); input.oninput = update; name.querySelector("input").oninput = update; update();
  };
  form.append(entries, own);
  for (const share of tx.purchase.shares) add(share.person, share.amount);
  if (!tx.purchase.shares.length) add();
  if (legacy.length) {
    assignments.append(this.el("p", "По этой покупке уже были возвраты. Укажите, кто их сделал, чтобы не уменьшить расход дважды.", "muted"));
    for (const receipt of legacy) {
      const choice = this.choice(`${receipt.date} · ${money(receipt.amount, receipt.currency)} · ${receipt.method === "cash" ? "наличными" : "на счёт"}`, "previous_person", []);
      choice.querySelector("select").required = true;
      assignments.append(choice);
    }
    form.append(assignments); update();
  }
  const actions = this.el("div", undefined, "onboarding-actions");
  const another = this.el("button", "+ Участник"); another.type = "button"; another.onclick = () => add();
  const save = this.el("button", "Сохранить доли", "primary"); save.type = "submit";
  const cancel = this.el("button", "Закрыть"); cancel.type = "button"; cancel.onclick = () => { this.editSharedPurchase = null; this.render(); };
  actions.append(another, save, cancel); form.append(actions);
  form.onsubmit = event => { event.preventDefault(); this.busy(async () => {
    const shares = [...entries.children].map(line => ({person:line.querySelector('[name="person"]').value.trim(), amount:line.querySelector('[name="share_amount"]').value}));
    const previous = [...assignments.querySelectorAll("select")].map((select, index) => ({id:legacy[index].id, method:legacy[index].method, person:select.value}));
    await this.api("purchase_shares", {purchase_id:tx.id, shares, assignments:previous}); this.editSharedPurchase = null;
    await this.reloadPeriod(); this.status("Доли сохранены", true);
  }); };
  row.append(form);
}
