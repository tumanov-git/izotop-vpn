from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def parse_amount_minor(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return int((amount * 100).to_integral_value())


@dataclass(slots=True)
class TributeEvent:
    event_key: str
    event_name: str
    telegram_user_id: int | None
    telegram_username: str | None
    tribute_subscription_id: int | None
    period_id: int | None
    channel_id: int | None
    expires_at: datetime | None
    cancelled: bool
    donation_request_id: int | None
    amount_minor: int | None
    currency: str | None
    raw_payload: dict[str, Any]

    @property
    def is_subscription_event(self) -> bool:
        return self.tribute_subscription_id is not None or self.event_name.endswith("_subscription")


class TributeService:
    def __init__(
        self,
        *,
        secret: str,
        signature_header: str = "trbt-signature",
    ) -> None:
        self.secret = secret
        self.signature_header = signature_header.lower()

    def verify_signature(self, headers: dict[str, str], body: bytes) -> bool:
        received = ""
        for key, value in headers.items():
            if key.lower() == self.signature_header:
                received = value.strip()
                break
        if not received:
            return False
        received = received.removeprefix("sha256=").strip()
        return hmac.compare_digest(
            received,
            hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest(),
        )

    def parse_event(self, payload: dict[str, Any]) -> TributeEvent:
        event_name = str(payload.get("name", "")).strip()
        data = payload.get("payload", {}) or {}
        telegram_user_id = data.get("telegram_user_id")
        subscription_id = data.get("subscription_id")
        donation_request_id = data.get("donation_request_id")
        created_at = payload.get("created_at") or payload.get("sent_at") or data.get("createdAt") or ""
        expires_at = parse_datetime(data.get("expires_at"))
        event_key_parts = [event_name, str(created_at)]
        if donation_request_id is not None:
            event_key_parts.append(str(donation_request_id))
        else:
            event_key_parts.extend(
                [
                    str(telegram_user_id or "unknown"),
                    str(subscription_id or "none"),
                ]
            )
        event_key = ":".join(event_key_parts)
        return TributeEvent(
            event_key=event_key,
            event_name=event_name,
            telegram_user_id=int(telegram_user_id) if telegram_user_id is not None else None,
            telegram_username=data.get("telegram_username"),
            tribute_subscription_id=int(subscription_id) if subscription_id is not None else None,
            period_id=int(data["period_id"]) if data.get("period_id") is not None else None,
            channel_id=int(data["channel_id"]) if data.get("channel_id") is not None else None,
            expires_at=expires_at,
            cancelled=event_name == "cancelled_subscription",
            donation_request_id=int(donation_request_id) if donation_request_id is not None else None,
            amount_minor=parse_amount_minor(data.get("amount")),
            currency=str(data.get("currency")).strip().casefold() if data.get("currency") is not None else None,
            raw_payload=payload,
        )

    @staticmethod
    def dump_payload(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
