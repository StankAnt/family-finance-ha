# Family Finance for Home Assistant (self-hosted preview)

This package installs a private finance API, a Home Assistant custom integration,
and a dashboard. Bank access uses **read-only Enable Banking AIS**. Bank data and
RSA keys stay on your server. The browser sees transaction details only inside an
authenticated Home Assistant administrator session.

## Supported installation

- Linux server with Docker Compose v2, Python 3.11+ for the installer, and a
  **Home Assistant Core container in host-network mode on the same server**.
- Writable Home Assistant configuration directory on that server.
- A Home Assistant address reachable from the browser that completes bank login:
  either HTTPS or a local `http://192.168...` address on the same home network.
  A public HA endpoint is not required.
- An Enable Banking AIS application and permission to link your accounts.
- The current bank chooser covers Polish banks returned by Enable Banking.

Home Assistant OS/Supervised and a Home Assistant instance on another host need
different service addressing. This preview installer stops before changing those
setups. The finance API stays on a dedicated internal Docker subnet chosen during
bootstrap; the installer confirms the HA host can reach it. The callback's
administration endpoint binds to host loopback only.

## Install

1. Clone a tagged release into a private directory owned by your user. Keep
   the checkout outside Home Assistant's `/config` and public web directories:

   ```sh
   git clone https://github.com/StankAnt/family-finance-ha.git
   cd family-finance-ha
   git checkout v0.1.18
   ```
2. Run `python3 distribution/bootstrap.py`. It creates local random database and
   API credentials, mode-600 files under `secrets/`, and `.env` with your UID/GID.
   It does not create or import a banking key.
3. Start the database, run migrations and seed generic categories, then start
   the services:

   ```sh
   docker compose --env-file .env -f distribution/compose.yaml up -d db
   docker compose --env-file .env -f distribution/compose.yaml run --rm migrate
   docker compose --env-file .env -f distribution/compose.yaml up -d api callback
   ```

4. Install the dashboard into Home Assistant. Substitute the **host path** of
   your HA configuration directory:

   ```sh
   python3 distribution/install_ha.py --config-dir /path/to/homeassistant/config \
     --notify-service mobile_app_your_phone
   ```

   The script backs up `configuration.yaml`, adds an admin-only dashboard, copies
   the bundled integration and card, and copies the API key with mode 600.
   It also checks the private API address before installing. It refuses unfamiliar
   `frontend`/`lovelace` include layouts. In that case,
   adapt the small YAML snippets manually; do not force the installer.
5. Check the Home Assistant configuration and restart the HA container using
   your usual method. Open **Семейные финансы → Настройки и ввод** as an HA
   administrator.

## Connect a bank entirely from the dashboard

1. In **Подключение банка**, generate an RSA key pair locally or upload your own
   private PEM. Use **Показать публичный сертификат** to copy the certificate
   into the Enable Banking Control Panel. The private PEM is stored only in
   `secrets/production/enable_banking.pem`; it is never included in the archive.
2. Create a **production AIS application** in the
   [Enable Banking Control Panel](https://enablebanking.com/docs/api/control-panel/).
   The form may require an application description, data protection email,
   privacy policy, and terms URL. Link the intended bank accounts in the Control
   Panel if the application is restricted. Register a
   redirect URL pointing to **your own Home Assistant dashboard path**, such as
   `http://192.168.0.123:8123/family-finance/overview` on the home network or
   `https://your-ha.example/family-finance/overview`. The setup form proposes
   the URL currently open in your browser.
   The exact same URL must appear in the Enable Banking application settings.
3. Copy the application's UUID into the dashboard and save it with the redirect
   URL. Select the bank, press **Получить ссылку авторизации**, and open the link.
4. After bank approval, the dashboard detects the redirected URL and removes
   `code` and `state` from the address bar. If the field is not filled, copy the
   **final browser URL** containing both parameters into **Завершить подключение**.
   Treat this URL as a one-time secret;
   do not send it to a chat or another person. The dashboard verifies the state,
   exchanges the code once, and keeps the session locally. Repeat the last two
   steps for another family member's accounts under the same application.
5. On **Обзор**, press **Обновить реальные операции**. The first request can be
   slow, and bank rate limits still apply. Read-only bank data collection does
   not initiate payments.

The redirect can land on a regular Home Assistant page. The copy-and-paste flow
does not require a reverse-proxy callback worker; the URL must remain visible in
the address bar long enough to copy. [Enable Banking's AIS flow](https://enablebanking.com/docs/api/reference/)
documents that its redirect adds `code` and `state` and that the code is
exchanged through `POST /sessions`.

### No public domain or public Home Assistant endpoint

For a Home Assistant instance that is reachable only on the home network, open
the finance dashboard by its LAN IP, for example
`http://192.168.0.123:8123/family-finance/overview`. Register that exact URL
as a redirect URL in the Enable Banking application and save it in the finance
dashboard. After bank approval, Enable Banking redirects the **browser** to
that address; Enable Banking does not need to contact the Raspberry Pi itself.
The device that finishes bank login must be on the same network and already
able to open HA. If HA login or a bank app changes browsers and automatic
capture fails, copy the final URL with `code` and `state` into the dashboard.
Do not send it to another person. Whether a production Enable Banking
application accepts a private IP redirect must be verified in its Control
Panel; the provider's API reference includes HTTP examples but does not
explicitly guarantee this case.

The LAN HTTP option sends the one-time `code` and `state` without TLS on that
network. Use the private HTTPS option below if you want encryption for the
callback. Public HTTP URLs remain rejected by the application. `localhost`
works only when the browser that finishes bank login runs on the HA host;
on a phone or laptop it refers to that device instead of the Raspberry Pi.

You can also keep Home Assistant private and give the browser an HTTPS callback.
One option is [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve):

1. Join the HA host and the phone/computer used for bank login to the same
   tailnet. Enable MagicDNS and HTTPS certificates for the tailnet.
2. On the HA host, where Home Assistant listens on `127.0.0.1:8123`, run
   `tailscale serve --bg 8123`. Run `tailscale serve status` to see its
   `https://<machine>.<tailnet>.ts.net` address. **Use Serve, not Funnel**;
   Serve is available only within the tailnet.
3. Open the finance dashboard through that HTTPS address and verify HA login
   works before starting bank authorization. Register the exact dashboard URL,
   for example `https://<machine>.<tailnet>.ts.net/family-finance/overview`,
   in the Enable Banking Control Panel and in the finance setup form.
4. Keep Tailscale connected on the device that finishes the bank flow. Some bank
   apps open the device's default browser, which must also be able to reach the
   tailnet and sign in to Home Assistant. The dashboard can accept the final
   redirect URL by copy and paste if automatic capture does not work.

If HA responds with a reverse-proxy error, configure only the actual proxy IP
as a trusted proxy in [Home Assistant HTTP settings](https://www.home-assistant.io/integrations/http/)
and retest. The Enable Banking Control Panel must accept the chosen HTTPS URL;
this particular tailnet callback has not yet been tested against a production
bank. Tailscale certificates publish the device's hostname to the public
certificate-transparency log, while Serve access remains restricted to the
tailnet. Choose a non-sensitive machine name.

## Optional OpenAI classification

OpenAI processing starts **disabled** in a new installation. If you choose to
enable it, enter an API key in **Настройки и ввод → Классификация OpenAI** and
tick the consent box. The key is stored locally in `secrets/openai/api_key`.
The application sends redacted merchant/description text for classification;
amounts, dates, account identifiers, and full bank records are not sent.

## Mortgage balance

Enter a bank-confirmed remaining debt with its date in **Настройки и ввод**.
After that date, the dashboard subtracts principal from mortgage payments you
have split into principal, interest and fees. Interest and fees do not reduce
the debt. A newer bank-confirmed balance becomes the new starting point; older
payments are not subtracted twice. The displayed result is a calculation and
should be checked against the bank, especially if a payment has not been split.

## Cash and reimbursements

The **Наличные** tab is a local wallet for PLN, EUR and USD. Enter an opening balance separately for each currency if you
already have cash, then record cash purchases with a category and optional
project. The wallet balance is included once in family assets. **Всего денег**
shows bank balances plus the wallet, with a breakdown of both amounts. Cash purchases enter
the same monthly spending chart as bank purchases. Cash amounts remain in their
original currency. Expenses and reimbursements are converted to PLN using the
NBP rate available on the transaction date; each currency's remaining balance
is valued using the rate available at the report date. Weekend and holiday
dates use the latest rate from the preceding seven days. The dashboard fetches
missing NBP rates when needed and shows a gap if a rate is still unavailable.

If you paid for someone else and they returned cash, open the **bank purchase**
in **Операции**, choose **⋯ → Вернули наличными**, and record the amount and
receipt date. Partial reimbursements are supported. Enable **Добавить полученные деньги
в наличный кошелёк** only when the receipt should increase the wallet; it is off
by default in the dashboard. The returned amount reduces that purchase's family
expense in the bank posting month. It is not external income; the original bank outflow
still shows the full bank payment. You can delete an incorrect cash entry from
the wallet history. Completed purchases and cash receipts may be in PLN, EUR or USD.

For shared purchases, use **⋯ → Оплатил за других**. Enter each participant and
their share; the remainder is the family's
expense. The dashboard tracks partial cash and bank repayments by participant.
Outstanding amounts appear under **Вам должны вернуть** and are included in family
assets, separately from bank and cash balances. When splitting a purchase that
already has repayments, select who made each earlier repayment; this keeps the
expense and wallet from being adjusted twice.

For store refunds, the incoming bank transaction offers possible purchases with
matching merchant text, currency, amount and dates. Confirm the association; it
is never applied automatically. You may also choose a debit and credit manually
through their **⋯** menus. A bank repayment from a participant uses the same
selection panel with **Вернули за другого человека** and the participant's name.
Bank links currently match the full incoming transaction to one purchase in the
same currency; multiple partial receipts may link to that purchase. Confirmed
refunds reduce the original purchase month's category and project, while the
cashflow follows the actual receipt date. The link can be undone to restore the
incoming transaction's previous classification.

**Все исходящие платежи** shows gross cash outflows before refunds.
**Расходы с учётом возвратов** shows purchases and projects after confirmed
refunds and other participants' shares, with unclassified debits included
provisionally. It excludes the whole mortgage payment and investment transfers.
Confirmed repayment and store-refund credits are excluded from **Доходы извне**.

The wallet is local to the finance database. Entering cash does not contact the
bank or send cash notes to MQTT or OpenAI. Back up the database before updates.

## Updates and backups

Releases are applied **on each friend's own server**. A push to GitHub does not
alter their installation by itself. Prefer a tested version tag over tracking
the moving `main` branch. From the same checkout used for installation:

```sh
git fetch --tags origin
git checkout v0.1.18                       # latest release tag
python3 distribution/update.py \
  --config-dir /path/to/homeassistant/config \
  --ha-container homeassistant            # omit if HA has another restart method
```

The updater builds the new images, starts the database, runs Alembic migrations,
recreates only the finance API and callback containers, installs the card and HA
integration, then checks and restarts the named HA container. Without
`--ha-container`, check the HA configuration and restart it yourself. It does
not run `bootstrap.py`, delete the database volume, or replace `.env`, bank
keys, sessions, OpenAI key, or dashboard API credentials. If the migration or
build fails, stop and inspect the error before retrying; a database migration
may need a version-specific rollback plan. Back up `secrets/` and the Docker
database volume together **before** upgrading. Never publish either one.

If using the archive rather than Git, extract a newer release into the same
installation directory without overwriting `secrets/` or `.env`, then run the
same updater. A Git checkout is simpler for repeat updates.

Keep `secrets/`, `.env`, database exports, and redirected `code` URLs out of Git.
Do not initialize a public repository from a personal working directory that
contains old deployment configs or banking test data; publish only the curated
distribution source after reviewing it.

The HA integration refreshes bank operations and account balances every six hours and sends a
phone notification for new items requiring classification when a valid
`--notify-service` is configured. The dashboard's **Отправить тестовый пуш**
button verifies the selected HA notify service without contacting the bank.
This package does not configure an off-host backup target.

Bank consent must be renewed periodically. New authorizations request up to
180 days, within the bank's advertised `maximum_consent_validity`. The bank may
end access earlier. The dashboard shows when all or part of the household needs
reauthorization. Open **Настройки и ввод → Авторизация счетов**, obtain a new
authorization link and sign in as each affected account owner separately, then
refresh bank operations. Existing keys and transaction classifications are kept.
Closed older sessions do not block sessions that are still authorized.

Monthly reports and category charts use the transaction date (falling back to booking date, then value date), matching the operations filter. Only completed bank transactions count. Bank balance reconciliation and PLN exchange rates still use bank posting dates.

Account cards and the available-money total use the bank-provided available balance, including holds. When unavailable in the latest balance sync, the booked balance is shown explicitly as a fallback. Booked balances remain the basis for net worth and balance reconciliation.

Income can be assigned to a budget month in the operation editor (for example, salary received in November for October). The income card, income categories and operations month filter follow this choice. The original transaction date, bank balance, currency conversion date and cashflow remain unchanged. Clear the month to use the transaction date again. The assignment survives bank syncs, is audited, and is never copied to other payments by category learning.
