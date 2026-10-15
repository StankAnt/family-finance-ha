# Family Finance for Home Assistant (self-hosted preview)

This package installs a private finance API, a Home Assistant custom integration,
and a dashboard. Bank access uses **read-only Enable Banking AIS**. Bank data and
RSA keys stay on your server. The browser sees transaction details only inside an
authenticated Home Assistant administrator session.

## Supported installation

- Linux server with Docker Compose v2, Python 3.11+ for the installer, and a
  **Home Assistant Core container in host-network mode on the same server**.
- Writable Home Assistant configuration directory on that server.
- An HTTPS address for your own Home Assistant, reachable during bank login.
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
   git checkout v0.1.0
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
   redirect URL pointing to **your own HTTPS Home Assistant dashboard path**,
   such as `https://your-ha.example/family-finance/overview`. The setup form
   proposes the current browser URL when the dashboard is opened over HTTPS.
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

## Optional OpenAI classification

OpenAI processing starts **disabled** in a new installation. If you choose to
enable it, enter an API key in **Настройки и ввод → Классификация OpenAI** and
tick the consent box. The key is stored locally in `secrets/openai/api_key`.
The application sends redacted merchant/description text for classification;
amounts, dates, account identifiers, and full bank records are not sent.

## Updates and backups

Releases are applied **on each friend's own server**. A push to GitHub does not
alter their installation by itself. Prefer a tested version tag over tracking
the moving `main` branch. From the same checkout used for installation:

```sh
git fetch --tags origin
git checkout v0.1.1                        # example tested release tag
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

The HA integration checks for new bank operations every six hours and sends a
phone notification for new items requiring classification when a valid
`--notify-service` is configured. The dashboard's **Отправить тестовый пуш**
button verifies the selected HA notify service without contacting the bank.
This package does not configure an off-host backup target.
