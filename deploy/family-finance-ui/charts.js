import { categoryLabel, money, monthTitle } from "./format.js";

const COLORS = ["#087e8b", "#df9b4b", "#7d69b5", "#55a978", "#d26b76", "#7196bd", "#9ca4b5"];
const CATEGORY_FILTERS = [
  ["all", "Без ипотеки и инвестиций", ["consumption", "project_expense", "unclassified", "other_external_outflow"]],
  ["consumption", "Повседневные", ["consumption"]],
  ["project_expense", "Разовые проекты", ["project_expense"]],
  ["mortgage", "Проценты и комиссии", ["mortgage_interest", "mortgage_fees"]],
  ["unclassified", "Неразмеченные списания", ["unclassified"]],
  ["income", "Доходы", ["external_income"]],
];

function mergedCategories(byType, types) {
  const totals = {};
  for (const type of types) {
    for (const [name, raw] of Object.entries(byType?.[type] || {})) {
      const amount = Number(raw);
      if (Number.isFinite(amount) && amount > 0) totals[name] = (totals[name] || 0) + amount;
    }
  }
  return totals;
}

function drawDonut(card, data, label, onSelect, formatName = categoryLabel) {
  const entries = Object.entries(data || {}).map(([name, raw]) => [name, Number(raw)])
    .filter(([, value]) => Number.isFinite(value) && value > 0)
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    card.append(this.el("p", "За выбранный месяц пока нет размеченных сумм для этой диаграммы.", "muted"));
    return;
  }
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const segments = entries.slice(0, 6);
  const rest = entries.slice(6).reduce((sum, [, value]) => sum + value, 0);
  if (rest > 0) segments.push(["Остальное", rest]);
  const gradient = activeIndex => {
    let offset = 0;
    const stops = segments.map(([, value], index) => {
      const start = offset;
      offset += value / total * 100;
      const color = activeIndex < 0 || activeIndex === index ? COLORS[index] :
        `color-mix(in srgb, ${COLORS[index]} 18%, #e7edf0)`;
      return `${color} ${start}% ${offset}%`;
    });
    return `conic-gradient(${stops.join(",")})`;
  };
  const layout = this.el("div", undefined, "chart-layout");
  const donut = this.el("div", undefined, "donut");
  donut.style.background = gradient(-1);
  donut.setAttribute("role", "img");
  donut.setAttribute("aria-label", `${label}: ${entries.map(([name, value]) =>
    `${formatName(name)} ${money(value)}, ${Math.round(value / total * 100)}%`).join(", ")}`);
  const center = this.el("div", undefined, "donut-center");
  const centerValue = this.el("strong", money(total));
  const centerLabel = this.el("small", "за месяц");
  center.append(centerValue, centerLabel);
  donut.append(center);
  const legend = this.el("div", undefined, "chart-legend");
  const segmentRows = [];
  const selectRow = (row, name) => {
    if (!onSelect) return;
    row.classList.add("is-link");
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-label", `Показать операции: ${formatName(name)}`);
    row.addEventListener("click", () => onSelect(name));
    row.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault(); onSelect(name);
      }
    });
  };
  const legendRow = ([name, value], index) => {
    const line = this.el("div", undefined, "chart-legend-row");
    const swatch = this.el("span", undefined, "chart-swatch");
    swatch.style.background = COLORS[Math.min(index, 6)];
    const valueLabel = this.el("span", undefined, "chart-legend-value");
    valueLabel.append(this.el("strong", money(value)),
      this.el("small", `${Math.round(value / total * 100)}%`));
    line.append(swatch, this.el("span", formatName(name)), valueLabel);
    selectRow(line, name);
    return line;
  };
  entries.slice(0, 6).forEach((entry, index) => {
    const row = legendRow(entry, index);
    segmentRows.push(row);
    legend.append(row);
  });
  if (rest > 0) {
    const details = this.el("details", undefined, "chart-rest");
    const summary = this.el("summary", undefined, "chart-rest-summary");
    const swatch = this.el("span", undefined, "chart-swatch");
    swatch.style.background = COLORS[6];
    summary.append(swatch, this.el("span", `Показать остальные (${entries.length - 6})`),
      this.el("strong", `${money(rest)} · ${Math.round(rest / total * 100)}%`));
    segmentRows.push(summary);
    details.append(summary);
    entries.slice(6).forEach((entry, index) => details.append(legendRow(entry, index + 6)));
    legend.append(details);
  }
  let activeIndex = -1;
  const highlight = index => {
    if (index === activeIndex) return;
    if (activeIndex >= 0) segmentRows[activeIndex].classList.remove("is-active");
    activeIndex = index;
    donut.style.background = gradient(index);
    if (index >= 0) {
      segmentRows[index].style.setProperty("--chart-accent", COLORS[index]);
      segmentRows[index].classList.add("is-active");
      centerValue.textContent = money(segments[index][1]);
      centerLabel.textContent = formatName(segments[index][0]);
    } else {
      centerValue.textContent = money(total);
      centerLabel.textContent = "за месяц";
    }
  };
  segmentRows.forEach((row, index) => {
    row.addEventListener("pointerenter", () => highlight(index));
    row.addEventListener("pointerleave", () => highlight(-1));
  });
  const sectorAt = event => {
    const rect = donut.getBoundingClientRect();
    const dx = event.clientX - rect.left - rect.width / 2;
    const dy = event.clientY - rect.top - rect.height / 2;
    const radius = Math.hypot(dx, dy);
    if (radius > rect.width / 2 || radius < rect.width * 0.31) {
      return -1;
    }
    const percent = ((Math.atan2(dx, -dy) * 180 / Math.PI + 360) % 360) / 3.6;
    let cumulative = 0;
    const index = segments.findIndex(([, value]) => (cumulative += value / total * 100) > percent);
    return index < 0 ? segments.length - 1 : index;
  };
  donut.addEventListener("pointermove", event => highlight(sectorAt(event)));
  donut.addEventListener("click", event => {
    if (!onSelect) return;
    const index = sectorAt(event);
    if (index < 0) return;
    if (rest > 0 && index === segments.length - 1) {
      const details = legend.querySelector(".chart-rest");
      details.open = true;
      details.querySelector("summary").focus();
      return;
    }
    onSelect(segments[index][0]);
  });
  donut.addEventListener("pointerleave", () => highlight(-1));
  layout.append(donut, legend);
  card.append(layout);
}

export function renderCharts(holder, month) {
  const hasMortgage = Boolean(this.options?.mortgages?.length);
  const availableFilters = CATEGORY_FILTERS.filter(([key]) => hasMortgage || key !== "mortgage");
  const section = this.el("section", undefined, "chart-section");
  const head = this.el("div", undefined, "section-head");
  head.append(this.el("h3", `Куда уходят деньги · ${monthTitle(month.period)}`),
    this.el("p", hasMortgage ?
      "По умолчанию диаграмма показывает платежи без всей ипотеки и инвестиций. Неразмеченные списания включены предварительно; проценты по ипотеке можно посмотреть отдельным фильтром." :
      "По умолчанию диаграмма показывает платежи без инвестиций. Неразмеченные списания включены предварительно.", "muted"));
  section.append(head);
  const grid = this.el("div", undefined, "split");
  const categories = this.el("section", undefined, "surface chart-card");
  const categoryHead = this.el("div", undefined, "chart-head");
  categoryHead.append(this.el("h3", "Категории"));
  const filters = this.el("div", undefined, "chart-filters");
  const filter = this.choice("Показать", "chart_type",
    availableFilters.map(([key, title]) => [key, key === "all" && !hasMortgage ? "Без инвестиций" : title]),
    availableFilters.some(([key]) => key === this.chartFilter) ? this.chartFilter : "all");
  const projectNames = Object.keys(month.spending_by_project_pln || {}).sort((a, b) => a.localeCompare(b, "ru"));
  const project = this.choice("Проект", "chart_project",
    [["", "Все проекты"], ...projectNames.map(name => [name, name])],
    projectNames.includes(this.chartProject) ? this.chartProject : "");
  const body = this.el("div");
  const draw = () => {
    this.chartFilter = filter.querySelector("select").value;
    this.chartProject = project.querySelector("select").value;
    body.replaceChildren();
    const [, title, types] = availableFilters.find(([key]) => key === this.chartFilter);
    const byType = this.chartProject ?
      month.category_by_project_type_pln?.[this.chartProject] : month.category_by_type_pln;
    drawDonut.call(this, body, mergedCategories(byType, types),
      this.chartProject ? `${title}, проект ${this.chartProject}` : title,
      name => this.openReviewFilter({ category: name, project: this.chartProject || "" }));
  };
  filter.querySelector("select").onchange = () => {
    if (project.querySelector("select").value && !["all", "consumption", "project_expense"].includes(filter.querySelector("select").value))
      project.querySelector("select").value = "";
    draw();
  };
  project.querySelector("select").onchange = () => {
    if (project.querySelector("select").value && !["all", "consumption", "project_expense"].includes(filter.querySelector("select").value))
      filter.querySelector("select").value = "all";
    draw();
  };
  filters.append(filter, project);
  categoryHead.append(filters);
  categories.append(categoryHead, body);
  draw();
  const projects = this.el("section", undefined, "surface chart-card");
  projects.append(this.el("h3", "Проекты"));
  drawDonut.call(this, projects, month.spending_by_project_pln, "Проекты",
    name => this.openReviewFilter({ project: name }), name => name);
  grid.append(categories, projects);
  section.append(grid);
  holder.append(section);
}
