export const TYPE_INFO = {
  purchase_refund: ["Возврат покупки", "Связан с исходной покупкой и уменьшает её расход."],
  reimbursement: ["Возврат за другого человека", "Погашение суммы, оплаченной за другого."],
  unclassified: ["Не определено", "Операция ещё не учтена в расходах или доходах."],
  consumption: ["Повседневный расход", "Покупки и регулярные траты семьи."],
  external_income: ["Доход извне", "Зарплата и другие поступления не со своих счетов."],
  project_expense: ["Разовый проект", "Крупная трата, которая не входит в обычный бюджет."],
  investment_transfer: ["Перевод в инвестиции", "Движение денег в инвестиции, не расход на жизнь."],
  mortgage_interest: ["Ипотека — только проценты", "Укажите части списания в появившейся форме. Проценты входят в расходы на жизнь."],
  mortgage_principal: ["Ипотека — платёж или тело", "Укажите долю тела, процентов и комиссии по данным банка в появившейся форме."],
  fx_conversion: ["Обмен валюты", "Конвертация денег, не доход и не расход."],
  external_transfer: ["Другой перевод", "Перевод внешнему получателю, который не является покупкой."],
  internal_transfer: ["Свой перевод", "Движение денег между своими счетами; не доход и не расход."],
};

export const TYPE_CHOICES = Object.entries(TYPE_INFO).map(([key, [label]]) => [key, label]);

const CATEGORY_LABELS = {
  Housing: "Жильё",
  "Housing/Mortgage payment": "Жильё / Ипотечный платёж",
  "Housing/Mortgage interest": "Жильё / Проценты по ипотеке",
  "Housing/Mortgage fees": "Жильё / Комиссии по ипотеке",
  "Housing/Maintenance": "Жильё / Обслуживание и ремонт",
  "Housing/Energy": "Жильё / Коммунальные услуги",
  "Housing/Insurance": "Жильё / Страхование",
  "Housing/Internet": "Жильё / Интернет",
  Income: "Доходы",
  "Income/Salary": "Доходы / Зарплата",
  "Income/Bonus": "Доходы / Премия",
  "Income/Interest": "Доходы / Проценты банка",
  "Income/Gift": "Доходы / Подарок",
  "Income/Other": "Доходы / Другой доход",
  Food: "Питание",
  "Food/Groceries": "Питание / Продукты",
  "Food/Eating out": "Питание / Кафе и рестораны",
  "Food/Delivery": "Питание / Доставка еды",
  Sports: "Спорт",
  "Sports/Tennis": "Спорт / Теннис",
  "Sports/Yoga": "Спорт / Йога",
  Subscriptions: "Подписки",
  "Subscriptions/AI": "Подписки / ИИ",
  "Subscriptions/Apple": "Подписки / Apple",
  "Subscriptions/Hosting": "Подписки / Хостинг",
  Transport: "Транспорт",
  "Transport/Fuel": "Транспорт / Топливо",
  "Transport/Vehicle": "Транспорт / Автомобиль",
  "Transport/Transit": "Транспорт / Общественный транспорт",
  Shopping: "Покупки",
  Health: "Здоровье",
  Travel: "Путешествия",
  Entertainment: "Развлечения",
  Other: "Прочее",
  "Other/Uncategorized": "Прочее / Без категории",
  "Other/Unclassified": "Прочее / Требует разметки",
  "Other/External transfer": "Прочее / Внешние переводы",
};

// Translate known parent paths in custom subcategories without changing their API values.
export function categoryLabel(path) {
  if (!path) return path || "";
  if (Object.hasOwn(CATEGORY_LABELS, path)) return CATEGORY_LABELS[path];
  const [parent, ...children] = path.split("/");
  return [Object.hasOwn(CATEGORY_LABELS, parent) ? CATEGORY_LABELS[parent] : parent,
    ...children].join(" / ");
}
export function categoryChoices(paths) { return paths.map(path => [path, categoryLabel(path)]); }
export function isMortgageType(type) { return type === "mortgage_principal" || type === "mortgage_interest"; }
export function isMortgageCategory(path) {
  return path === "Housing/Mortgage payment" || path === "Housing/Mortgage interest";
}

export function reviewEconomicType(amount, category, project, special = "") {
  if (special) return special;
  if (Number(amount) > 0) return category?.startsWith("Income/") ? "external_income" : "unclassified";
  if (isMortgageCategory(category)) return "mortgage_principal";
  return project ? "project_expense" : "consumption";
}

export function money(value, currency = "PLN") {
  if (value == null) return "Нет данных";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number)} ${currency}`;
}

export function monthTitle(period) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(period || "")) return period || "";
  return new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${period}-01T12:00:00Z`));
}

export function percent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "—";
}
