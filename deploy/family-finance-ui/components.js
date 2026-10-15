export function heading(title, description) {
  const wrap = this.el("div", undefined, "section-head");
  const left = this.el("div"); left.append(this.el("h2", title));
  if (description) left.append(this.el("p", description, "muted"));
  wrap.append(left); return wrap;
}

export function metric(title, value, note, tone = "") {
  const card = this.el("article", undefined, `metric ${tone}`);
  card.append(this.el("div", title, "metric-title"),
    this.el("div", value, "metric-value"), this.el("div", note, "metric-note"));
  return card;
}

export function field(label, name, type="text", value="") {
  const wrap = this.el("label"); wrap.append(this.el("span", label));
  const input = this.el("input"); input.name = name; input.type = type;
  if (type === "number") { input.step = "0.01"; input.min = "0"; }
  if (value !== "") input.value = value;
  wrap.append(input); return wrap;
}

export function choice(label, name, choices, value="") {
  const wrap = this.el("label"); wrap.append(this.el("span", label));
  const select = this.el("select"); select.name = name;
  for (const [key, title] of choices) {
    const option = this.el("option", title); option.value = key;
    if (key === value) option.selected = true;
    select.append(option);
  }
  wrap.append(select); return wrap;
}

export function checkbox(label, name) {
  const wrap = this.el("label", undefined, "check");
  const input = this.el("input"); input.type = "checkbox"; input.name = name;
  wrap.append(input, this.el("span", label)); return wrap;
}

export function form(title, fields, onsubmit) {
  const section = this.el("section", undefined, "section");
  section.append(this.el("h3", title));
  const form = this.el("form", undefined, "grid");
  fields.forEach(field => form.append(field));
  const save = this.el("button", "Сохранить", "primary"); save.type = "submit";
  form.append(save);
  form.onsubmit = async (event) => {
    event.preventDefault(); save.disabled = true;
    await this.busy(async () => {
      await onsubmit(new FormData(form), form);
      [this.options, this.overview] = await Promise.all([
        this.api("options"), this.api("overview", { month: this.month })]);
      await this.loadReview(); this.render();
    }, "Сохранено");
    save.disabled = false;
  };
  section.append(form); return section;
}
