"""Admin-only WebSocket bridge to the private-network finance API."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from aiohttp import ClientTimeout
from homeassistant.components import websocket_api
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
import voluptuous as vol

from .request_body import backend_body

DOMAIN = "family_finance"
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): {
    vol.Optional("key_path", default="/config/family_finance_key"): str,
    vol.Optional("api_url", default="http://127.0.0.1:8766/api"): str,
    vol.Optional("callback_base_url", default="http://127.0.0.1:8765"): str,
    vol.Optional("notify_service", default=""): str,
    vol.Optional("scheduled_sync", default=False): bool,
}}, extra=vol.ALLOW_EXTRA)
KEY_PATH = Path("/config/family_finance_key")
API_URL = "http://127.0.0.1:8766/api"
BANK_CHECK_URL = "http://127.0.0.1:8765/internal/inspect-accounts"
BANK_SYNC_URL = "http://127.0.0.1:8765/internal/sync-production"
AI_START_URL = "http://127.0.0.1:8765/internal/ai-production"
AI_STATUS_URL = "http://127.0.0.1:8765/internal/ai-status"


@websocket_api.websocket_command({
    vol.Required("type"): "family_finance/request",
    vol.Required("operation"): vol.In(("overview", "options", "review", "bank_accounts", "bank_sync", "ai_start", "ai_status", "test_notification",
                                       "setup_status", "setup_credentials", "setup_generate_key", "setup_public_certificate", "auth_banks", "auth_start", "auth_complete", "correct", "correct_mortgage", "manual",
                                       "transfers", "decide_transfer", "manual_pair", "project", "category", "rule",
                                       "cash", "cash_add", "cash_delete", "cash_fx_sync", "purchase_shares", "return_link", "return_unlink")),
    vol.Optional("payload", default={}): dict,
    vol.Optional("source", default="production"): vol.In(("production",)),
    vol.Optional("user_agent"): vol.All(str, vol.Length(min=1, max=512)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_request(hass, connection, msg):
    """The browser receives records only through HA's authenticated admin socket."""
    try:
        configuration = hass.data.get(DOMAIN, {})
        callback_base = configuration.get("callback_base_url", "http://127.0.0.1:8765").rstrip("/")
        api_url = configuration.get("api_url", API_URL)
        if msg["operation"] == "test_notification":
            if msg.get("payload") or msg["source"] != "production":
                connection.send_error(msg["id"], "finance_error", "Unexpected test request fields")
                return
            notify_service = configuration.get("notify_service", "")
            if not notify_service or not hass.services.has_service("notify", notify_service):
                connection.send_error(msg["id"], "finance_unavailable", "Phone notification service is unavailable")
                return
            if configuration.get("scheduled_sync"):
                await hass.services.async_call("notify", notify_service, {
                    "title": "Семейные финансы",
                    "message": "Тестовое уведомление: связь с телефоном работает.",
                    "data": {"tag": "family_finance_test", "url": "/family-finance/overview#/operations"}},
                    blocking=True)
            else:
                if not hass.services.has_service("mqtt", "publish"):
                    connection.send_error(msg["id"], "finance_unavailable", "MQTT is unavailable")
                    return
                await hass.services.async_call("mqtt", "publish", {
                    "topic": "family_finance/event/new_unclassified", "payload": "test",
                    "qos": 1, "retain": False}, blocking=True)
            connection.send_result(msg["id"], {"published": True})
            return
        key_path = Path(configuration.get("key_path", str(KEY_PATH)))
        key = await hass.async_add_executor_job(key_path.read_text)
        session = async_get_clientsession(hass)
        bank_check = msg["operation"] in ("bank_accounts", "bank_sync")
        local_ai = msg["operation"] in ("ai_start", "ai_status")
        onboarding = msg["operation"] in ("setup_status", "setup_credentials", "setup_generate_key",
                                           "setup_public_certificate", "auth_banks", "auth_start", "auth_complete")
        cash_fx = msg["operation"] == "cash_fx_sync"
        headers = {"X-Finance-Key": key.strip(), "Cache-Control": "no-store"}
        if bank_check:
            if not connection.remote or not msg.get("user_agent") or msg.get("payload"):
                connection.send_error(msg["id"], "finance_error", "Browser identity unavailable")
                return
            headers.update({"X-Finance-PSU-IP": connection.remote,
                            "X-Finance-PSU-User-Agent": msg["user_agent"]})
        if local_ai and (msg.get("payload") or msg["source"] != "production"):
            connection.send_error(msg["id"], "finance_error", "Unexpected AI request fields")
            return
        if onboarding and (msg["source"] != "production" or len(str(msg.get("payload", {}))) > 40000):
            connection.send_error(msg["id"], "finance_error", "Invalid setup request")
            return
        if cash_fx and (msg["source"] != "production" or set(msg.get("payload", {})) != {"month"}):
            connection.send_error(msg["id"], "finance_error", "Invalid FX request")
            return
        method = "GET" if msg["operation"] == "ai_status" else "POST"
        url = (f"{callback_base}/internal/ai-status" if msg["operation"] == "ai_status" else
               f"{callback_base}/internal/ai-production" if msg["operation"] == "ai_start" else
               f"{callback_base}/internal/sync-production" if msg["operation"] == "bank_sync" else
               f"{callback_base}/internal/cash-fx" if cash_fx else
               f"{callback_base}/internal/inspect-accounts" if bank_check else
               f"{callback_base}/internal/onboarding" if onboarding else api_url)
        async with session.request(
            method, url,
            headers=headers,
            json=msg["payload"] if cash_fx else backend_body(msg, onboarding=onboarding, no_body=bank_check or local_ai),
            timeout=ClientTimeout(total=600 if msg["operation"] == "bank_sync" else 90 if bank_check or onboarding or cash_fx else 20),
        ) as response:
            data = await response.json()
            if response.status != 200:
                error = data.get("detail", "Finance API unavailable") if isinstance(data, dict) else "Finance API unavailable"
                connection.send_error(msg["id"], "finance_error", str(error)[:180])
                return
            connection.send_result(msg["id"], data)
    except Exception:
        connection.send_error(msg["id"], "finance_unavailable", "Finance API unavailable")


async def async_setup(hass, config):
    """Register the dashboard API when explicitly enabled in configuration.yaml."""
    hass.data[DOMAIN] = config.get(DOMAIN, {})
    websocket_api.async_register_command(hass, ws_request)
    settings = hass.data[DOMAIN]
    if settings.get("scheduled_sync"):
        async def scheduled_sync(_now):
            try:
                key = await hass.async_add_executor_job(
                    Path(settings.get("key_path", str(KEY_PATH))).read_text)
                base = settings.get("callback_base_url", "http://127.0.0.1:8765").rstrip("/")
                session = async_get_clientsession(hass)
                async with session.post(f"{base}/internal/sync-background",
                                        headers={"X-Finance-Key": key.strip()},
                                        timeout=ClientTimeout(total=900)) as response:
                    if response.status != 200:
                        return
                    result = await response.json()
                count = result.get("new_unclassified", 0)
                notify_service = settings.get("notify_service", "")
                if isinstance(count, int) and count > 0 and notify_service and hass.services.has_service("notify", notify_service):
                    await hass.services.async_call("notify", notify_service, {
                        "title": "Семейные финансы",
                        "message": f"Новых операций для разметки: {count}.",
                        "data": {"tag": "family_finance_unclassified",
                                 "url": "/family-finance/overview#/operations?status=unclassified"}},
                        blocking=True)
            except Exception:
                return
        async_track_time_interval(hass, scheduled_sync, timedelta(hours=6))
    return True
