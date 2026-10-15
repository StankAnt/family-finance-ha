"""Send an aggregate, non-retained MQTT event after classification."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Transaction
from .sync import database_engine

TOPIC = "family_finance/event/new_unclassified"


def count_new_unclassified(db: Session, since: datetime) -> int:
    return db.scalar(select(func.count(Transaction.id)).where(
        Transaction.imported_at > since,
        Transaction.status == "BOOK",
        Transaction.economic_type == "unclassified")) or 0


def publish_new_unclassified(project_dir: Path, since: datetime) -> int:
    engine = database_engine(project_dir / "secrets" / "production_database_url_host")
    try:
        with Session(engine) as db:
            count = count_new_unclassified(db, since)
    finally:
        engine.dispose()
    if count:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id="family-finance-new-unclassified")
        client.connect("127.0.0.1", 1883, keepalive=30)
        client.loop_start()
        try:
            result = client.publish(TOPIC, str(count), qos=1, retain=False)
            result.wait_for_publish(timeout=5)
            if not result.is_published():
                raise RuntimeError("MQTT notification publish timed out")
        finally:
            client.disconnect()
            client.loop_stop()
    return count
