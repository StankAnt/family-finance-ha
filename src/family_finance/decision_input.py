"""Minimized text sent for an opt-in category decision."""

from __future__ import annotations

import hashlib
import re

from .models import Transaction


def prepare_input(transaction: Transaction) -> str:
    def redact(value: str) -> str:
        value = re.sub(r"\b[A-Z]{2}\s*\d{2}(?:[A-Z0-9][\s-]*){11,30}\b",
                       "[ACCOUNT]", value, flags=re.IGNORECASE)
        value = re.sub(r"\b\d{2}(?:[\s-]*\d{4}){6}\b", "[ACCOUNT]", value)
        value = re.sub(r"\b(?:\d{4}[\s-]*){3}\d{4}\b", "[CARD]", value)
        value = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Z]{2,}\b", "[EMAIL]", value,
                       flags=re.IGNORECASE)
        return re.sub(r"\b\d{10,}\b", "[NUMBER]", value)

    merchant = redact((transaction.counterparty_name or "").strip()[:300])
    description = redact((transaction.description or "").strip()[:1000])
    return f"Merchant: {merchant}\nDescription: {description}"


def input_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
