"""Background Decisions processing for the isolated production ledger.

No bank requests are made here. Each response is committed separately, so a
stopped worker can resume without resending completed items.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock, Thread
from collections.abc import Callable

from sqlalchemy.orm import Session

from .ai_decisions import DecisionsClient, suggest
from .secrets import FinanceError
from .sync import database_engine


class ProductionDecisionRunner:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self._lock = Lock()
        self._status_lock = Lock()
        self._callbacks: list[Callable[[], None]] = []
        self._status = {"state": "idle", "sent": 0, "proposed": 0,
                        "applied": 0, "error": None}

    def status(self) -> dict:
        with self._status_lock:
            return dict(self._status)

    def add_completion_callback(self, callback: Callable[[], None]) -> None:
        with self._status_lock:
            self._callbacks.append(callback)

    def start(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        with self._status_lock:
            self._status.update(state="running", sent=0, proposed=0,
                                applied=0, error=None)
        try:
            Thread(target=self._run, name="family-finance-decisions", daemon=True).start()
        except Exception:
            self._lock.release()
            raise
        return True

    def _run(self) -> None:
        engine = None
        client = None
        try:
            engine = database_engine(self.project_dir / "secrets" / "production_database_url_host")
            client = DecisionsClient(self.project_dir / "secrets" / "openai" / "api_key")
            while True:
                with Session(engine) as db:
                    sent, proposed, applied = suggest(
                        db, client, limit=25, environment="production",
                        include_classified=True)
                with self._status_lock:
                    self._status["sent"] += sent
                    self._status["proposed"] += proposed
                    self._status["applied"] += applied
                if sent == 0:
                    with self._status_lock:
                        self._status["state"] = "complete"
                    break
        except FinanceError as exc:
            with self._status_lock:
                self._status.update(state="failed", error=str(exc))
        except Exception:
            with self._status_lock:
                self._status.update(state="failed", error="Local AI classification failed")
        finally:
            if client is not None:
                client.close()
            if engine is not None:
                engine.dispose()
            with self._status_lock:
                callbacks, self._callbacks = self._callbacks, []
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    pass
            self._lock.release()
