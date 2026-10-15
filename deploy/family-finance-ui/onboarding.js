export function renderOnboarding(holder) {
  const state = this.setupStatus || {};
  const section = this.el("section", undefined, "surface onboarding");
  section.append(this.el("h3", "Подключение банка"),
    this.el("p", "Настройка доступна только администратору Home Assistant. Ключ хранится на этом сервере; ссылка авторизации и итоговый URL обрабатываются здесь.", "muted"));
  const progress = this.el("p", `Ключ: ${state.has_key ? "готов" : "не добавлен"} · UUID приложения: ${state.has_application_id ? "готов" : "не добавлен"} · Банковская сессия: ${state.has_session ? "есть" : "нет"}`, "muted");
  section.append(progress);
  if (this.authorizationError) section.append(this.el("p", this.authorizationError, "banner"));

  const keyBlock = this.el("details");
  const keySummary = this.el("summary", "1. RSA ключ и публичный сертификат");
  keyBlock.append(keySummary);
  const keyHelp = this.el("p", "Создайте новую пару на сервере или загрузите свой приватный PEM. В Enable Banking Control Panel загрузите только публичный сертификат. Приватный ключ туда не копируйте.", "muted");
  keyBlock.append(keyHelp);
  const generate = this.el("button", "Создать пару ключей"); generate.type = "button";
  generate.disabled = !!state.has_key;
  generate.onclick = () => this.busy(async () => {
    this.setupStatus = await this.api("setup_generate_key");
    this.render();
  }, "Ключи сохранены локально");
  const upload = this.el("input"); upload.type = "file"; upload.accept = ".pem,.key,text/plain";
  upload.setAttribute("aria-label", "Загрузить приватный PEM");
  const useKey = this.el("button", "Сохранить мой PEM"); useKey.type = "button";
  useKey.onclick = () => this.busy(async () => {
    const file = upload.files?.[0];
    if (!file || file.size > 16000) throw new Error("Выберите PEM файл размером до 16 КБ");
    this.setupStatus = await this.api("setup_credentials", { private_key: await file.text() });
    upload.value = "";
    this.render();
  }, "Приватный ключ сохранён локально");
  keyBlock.append(generate, upload, useKey);
  if (state.has_certificate) {
    const certificate = this.el("button", "Показать публичный сертификат"); certificate.type = "button";
    certificate.onclick = () => this.busy(async () => {
      const result = await this.api("setup_public_certificate");
      const output = this.el("textarea"); output.readOnly = true; output.rows = 12;
      output.value = result.certificate;
      output.setAttribute("aria-label", "Публичный сертификат для Enable Banking");
      certificate.replaceWith(output);
    });
    keyBlock.append(certificate);
  }
  section.append(keyBlock);

  const appBlock = this.el("details");
  appBlock.open = !state.has_application_id;
  appBlock.append(this.el("summary", "2. Приложение Enable Banking"));
  const appForm = this.el("form", undefined, "setup-form");
  const appId = this.el("input"); appId.name = "application_id"; appId.required = true;
  appId.placeholder = "UUID приложения"; appId.autocomplete = "off";
  const callback = this.el("input"); callback.name = "callback_url"; callback.type = "url";
  callback.required = true; callback.value = state.callback_url ||
    `${window.location.origin}${window.location.pathname}`;
  callback.autocomplete = "off";
  const saveApp = this.el("button", "Сохранить настройки", "primary"); saveApp.type = "submit";
  appForm.append(this.el("label", "UUID приложения"), appId,
    this.el("label", "Redirect URL, зарегистрированный в Enable Banking"), callback, saveApp);
  appForm.onsubmit = event => {
    event.preventDefault();
    this.busy(async () => {
      this.setupStatus = await this.api("setup_credentials", {
        application_id: appId.value.trim(), callback_url: callback.value.trim(),
      });
      appId.value = "";
      this.render();
    }, "Настройки приложения сохранены");
  };
  appBlock.append(this.el("p", "Создайте AIS приложение в Control Panel, загрузите публичный сертификат и зарегистрируйте этот же Redirect URL. Адрес HA в домашней сети может начинаться с http://, если Control Panel его примет. Браузер, завершающий вход в банк, должен видеть HA по этому адресу. После входа итоговый адрес заполнится ниже; если это не случилось, скопируйте его из адресной строки.", "muted"), appForm);
  section.append(appBlock);

  const authBlock = this.el("details"); authBlock.open = state.has_key && state.has_application_id && !state.has_session;
  authBlock.append(this.el("summary", "3. Авторизация счетов"));
  const bank = this.el("input"); bank.placeholder = "Название банка из списка";
  bank.setAttribute("aria-label", "Название банка в Enable Banking");
  bank.setAttribute("list", "family-finance-bank-list");
  const bankList = this.el("datalist"); bankList.id = "family-finance-bank-list";
  const loadBanks = this.el("button", "Загрузить список банков"); loadBanks.type = "button";
  loadBanks.disabled = !state.has_key || !state.has_application_id;
  loadBanks.onclick = () => this.busy(async () => {
    const result = await this.api("auth_banks");
    bankList.replaceChildren(...result.banks.map(name => {
      const option = this.el("option"); option.value = name; return option;
    }));
    this.status(`Доступно банков: ${result.banks.length}. Выберите точное название из списка.`, true);
  });
  const start = this.el("button", "Получить ссылку авторизации", "primary"); start.type = "button";
  start.disabled = !state.has_key || !state.has_application_id;
  const linkArea = this.el("div", undefined, "auth-link");
  start.onclick = () => this.busy(async () => {
    const result = await this.api("auth_start", { bank_name: bank.value.trim() });
    const anchor = this.el("a", "Открыть вход в банк");
    anchor.href = result.url; anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
    linkArea.replaceChildren(anchor, this.el("p", `После входа скопируйте конечный адрес браузера (${result.callback_url}) и вставьте его ниже.`, "muted"));
  });
  const finalUrl = this.el("input"); finalUrl.type = "url"; finalUrl.autocomplete = "off";
  finalUrl.value = this.pendingRedirectUrl || "";
  finalUrl.placeholder = "Итоговый URL с code и state";
  finalUrl.setAttribute("aria-label", "Итоговый URL после входа в банк");
  const finish = this.el("button", "Завершить подключение", "primary"); finish.type = "button";
  finish.onclick = () => this.busy(async () => {
    const result = await this.api("auth_complete", { redirected_url: finalUrl.value.trim() });
    finalUrl.value = "";
    this.pendingRedirectUrl = "";
    linkArea.replaceChildren();
    this.setupStatus = await this.api("setup_status");
    this.render();
    this.status(`Доступ подтверждён: ${result.authorized_accounts} счетов. Можно обновить операции на вкладке «Обзор».`, true);
  });
  authBlock.append(bank, bankList, loadBanks, start, linkArea, finalUrl, finish,
    this.el("p", "Чтобы добавить счета другого члена семьи, снова получите ссылку авторизации в том же приложении. Новая сессия добавится к существующим.", "muted"));
  section.append(authBlock);

  const aiBlock = this.el("details");
  aiBlock.append(this.el("summary", "Классификация OpenAI (необязательно)"),
    this.el("p", "При включении приложение отправляет OpenAI текст получателя и назначение операции после удаления номеров счетов, карт и email. Суммы, даты и ключи не отправляются. Классификация может запускаться после загрузки новых операций.", "muted"));
  const aiKey = this.el("input"); aiKey.type = "password"; aiKey.autocomplete = "new-password";
  aiKey.placeholder = state.has_openai_key ? "Ключ уже сохранён; оставить пустым" : "OpenAI API key";
  aiKey.setAttribute("aria-label", "OpenAI API key");
  const aiConsent = this.el("input"); aiConsent.type = "checkbox"; aiConsent.checked = !!state.ai_enabled;
  const aiLabel = this.el("label");
  aiLabel.append(aiConsent, document.createTextNode(" Разрешаю классификацию новых операций через OpenAI"));
  const aiSave = this.el("button", "Сохранить настройку OpenAI"); aiSave.type = "button";
  aiSave.onclick = () => this.busy(async () => {
    const payload = { ai_enabled: aiConsent.checked };
    if (aiKey.value) payload.openai_api_key = aiKey.value;
    this.setupStatus = await this.api("setup_credentials", payload);
    aiKey.value = "";
    this.render();
  }, "Настройка OpenAI сохранена");
  aiBlock.append(aiKey, aiLabel, aiSave);
  section.append(aiBlock);
  holder.append(section);
}
