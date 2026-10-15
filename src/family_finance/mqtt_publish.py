"""Publish aggregate-only Home Assistant MQTT Discovery sensors."""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .accounting import monthly_report, position_report
from .models import BankConnection, SyncRun
from .sync import database_engine

BASE = "family_finance"
AVAILABILITY = f"{BASE}/availability"
DEVICE = {"identifiers": ["family_finance_local"], "name": "Family Finance",
          "manufacturer": "Local", "model": "Household ledger"}

METRICS = {
    "income_monthly": ("Income this month", "PLN", "mdi:cash-plus"),
    "consumption_monthly": ("Spending this month", "PLN", "mdi:cart"),
    "extraordinary_expenses_monthly": ("Projects this month", "PLN", "mdi:calendar-star"),
    "cashflow_monthly": ("Cashflow this month", "PLN", "mdi:cash-flow"),
    "liquid_savings": ("Bank cash", "PLN", "mdi:bank"),
    "invested": ("Investments", "PLN", "mdi:chart-line"),
    "mortgage_principal_paid_monthly": ("Mortgage principal this month", "PLN", "mdi:home-minus"),
    "mortgage_balance": ("Mortgage balance", "PLN", "mdi:home-lock"),
    "net_worth": ("Net worth", "PLN", "mdi:scale-balance"),
    "uncategorized_count": ("Unclassified this month", None, "mdi:help-circle"),
    "bank_sync_status": ("Bank sync status", None, "mdi:sync"),
    "last_successful_sync": ("Last successful sync", None, "mdi:clock-check"),
    "period": ("Reporting month", None, "mdi:calendar-month"),
    "report_complete": ("Monthly report complete", None, "mdi:check-circle"),
}


def aggregate_state(db: Session, today: date) -> dict[str, str]:
    month = monthly_report(db, today.year, today.month)
    position = position_report(db, today)
    amounts = month["amounts_pln"]
    components = position["components_pln"]
    latest = db.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
    connection = db.scalar(select(BankConnection).order_by(BankConnection.last_checked_at.desc()).limit(1))
    last_success = db.scalar(select(SyncRun).where(SyncRun.status == "SUCCESS")
                             .order_by(SyncRun.finished_at.desc()).limit(1))
    return {
        "income_monthly": amounts.get("external_income", "0.00"),
        "consumption_monthly": amounts.get("total_expense_with_interest", "0.00"),
        "extraordinary_expenses_monthly": amounts.get("exceptional_projects", "0.00"),
        "cashflow_monthly": amounts.get("cashflow", "0.00"),
        "liquid_savings": position["liquid_savings_pln"] or "None",
        "invested": components.get("investment", "None") if "investment" not in position["missing_components"] else "None",
        "mortgage_principal_paid_monthly": amounts.get("mortgage_principal_confirmed", "0.00"),
        "mortgage_balance": components.get("mortgage_debt", "None") if "mortgage_debt" not in position["missing_components"] else "None",
        "net_worth": position["net_worth_pln"] or "None",
        "uncategorized_count": str(month["counts"].get("unclassified", 0)),
        "bank_sync_status": (f"{connection.consent_status}/{latest.status}" if connection and latest else "unknown"),
        "last_successful_sync": last_success.finished_at.isoformat() if last_success and last_success.finished_at else "unknown",
        "period": month["period"],
        "report_complete": "yes" if month["living_cost_complete"] else "no",
    }


def discovery_payload(metric: str) -> dict:
    name, unit, icon = METRICS[metric]
    payload = {"name": name, "unique_id": f"family_finance_{metric}",
               "default_entity_id": f"sensor.family_finance_{metric}",
               "state_topic": f"{BASE}/state/{metric}",
               "availability_topic": AVAILABILITY, "payload_available": "online",
               "payload_not_available": "offline", "icon": icon, "device": DEVICE,
               "origin": {"name": "family-finance", "sw_version": "0.1.0"}}
    if unit:
        payload["unit_of_measurement"] = unit
    return payload


def publish_discovery(client: mqtt.Client) -> None:
    for metric in METRICS:
        client.publish(f"homeassistant/sensor/family_finance_{metric}/config",
                       json.dumps(discovery_payload(metric)), qos=1, retain=True)


def publish_state(client: mqtt.Client, db: Session, today: date) -> None:
    values = aggregate_state(db, today)
    for metric, value in values.items():
        client.publish(f"{BASE}/state/{metric}", value, qos=1, retain=True)
    client.publish(AVAILABILITY, "online", qos=1, retain=True)


def main() -> None:
    engine = database_engine(Path("secrets/production_database_url"))
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="family-finance-publisher")
    client.will_set(AVAILABILITY, "offline", qos=1, retain=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            publish_discovery(client)
            client.subscribe("homeassistant/status", qos=0)
            client.publish(AVAILABILITY, "online", qos=1, retain=True)

    def on_message(client, userdata, message):
        if message.topic == "homeassistant/status" and message.payload == b"online":
            publish_discovery(client)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("host.docker.internal", 1883, keepalive=60)
    client.loop_start()
    try:
        while True:
            try:
                with Session(engine) as db:
                    publish_state(client, db, datetime.now(ZoneInfo("Europe/Warsaw")).date())
            except Exception:
                client.publish(AVAILABILITY, "offline", qos=1, retain=True)
            time.sleep(60)
    finally:
        client.publish(AVAILABILITY, "offline", qos=1, retain=True)
        client.disconnect()
        client.loop_stop()
        engine.dispose()


if __name__ == "__main__":
    main()
