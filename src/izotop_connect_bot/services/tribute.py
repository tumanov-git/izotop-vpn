from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


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
    order_uuid: str | None
    order_status: str | None
    raw_payload: dict[str, Any]

    @property
    def is_subscription_event(self) -> bool:
        return self.tribute_subscription_id is not None or self.event_name.endswith("_subscription")

    @property
    def is_shop_event(self) -> bool:
        return self.order_uuid is not None or self.event_name.startswith("shop_")

    @property
    def is_paid_shop_event(self) -> bool:
        if not self.is_shop_event:
            return False
        status = (self.order_status or "").strip().casefold()
        return self.event_name in {"shop_order", "shop_order_charge_success"} or status in {
            "paid",
            "success",
        }


@dataclass(frozen=True, slots=True)
class TributeShopOrder:
    order_uuid: str
    status: str
    payment_url: str | None
    webapp_payment_url: str | None
    amount_minor: int
    currency: str
    title: str
    raw_payload: dict[str, Any]


class TributeService:
    def __init__(
        self,
        *,
        secret: str,
        signature_header: str = "trbt-signature",
        api_key: str | None = None,
        shop_base_url: str = "https://tribute.tg/api/v1",
        success_url: str | None = None,
        fail_url: str | None = None,
    ) -> None:
        self.secret = secret
        self.signature_header = signature_header.lower()
        self.api_key = api_key
        self.shop_base_url = shop_base_url.rstrip("/")
        self.success_url = success_url
        self.fail_url = fail_url

    def verify_signature(self, headers: dict[str, str], body: bytes) -> bool:
        received = ""
        for key, value in headers.items():
            if key.lower() == self.signature_header:
                received = value.strip()
                break
        if not received:
            return False
        received = received.removeprefix("sha256=").strip()
        candidate_secrets = [self.secret]
        if self.api_key and self.api_key != self.secret:
            candidate_secrets.append(self.api_key)
        return any(
            hmac.compare_digest(
                received,
                hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest(),
            )
            for secret in candidate_secrets
        )

    def parse_event(self, payload: dict[str, Any]) -> TributeEvent:
        event_name = str(payload.get("name", "")).strip()
        data = payload.get("payload", {}) or {}
        telegram_user_id = data.get("telegram_user_id")
        subscription_id = data.get("subscription_id")
        order_uuid = data.get("uuid") or data.get("id")
        order_status = data.get("status")
        created_at = payload.get("created_at") or payload.get("sent_at") or data.get("createdAt") or ""
        expires_at = parse_datetime(data.get("expires_at"))
        event_key_parts = [event_name, str(created_at)]
        if order_uuid:
            event_key_parts.append(str(order_uuid))
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
            order_uuid=str(order_uuid) if order_uuid else None,
            order_status=str(order_status) if order_status is not None else None,
            raw_payload=payload,
        )

    async def create_shop_order(
        self,
        *,
        customer_id: str,
        title: str,
        amount_minor: int,
        currency: str,
        description: str | None = None,
        comment: str | None = None,
        success_url: str | None = None,
        fail_url: str | None = None,
    ) -> TributeShopOrder:
        api_key = self.api_key or self.secret
        payload: dict[str, Any] = {
            "title": title,
            "amount": amount_minor,
            "currency": currency,
            "customerId": customer_id,
            "period": "onetime",
        }
        if description:
            payload["description"] = description
        if comment:
            payload["comment"] = comment
        if success_url or self.success_url:
            payload["successUrl"] = success_url or self.success_url
        if fail_url or self.fail_url:
            payload["failUrl"] = fail_url or self.fail_url

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.shop_base_url}/shop/orders",
                json=payload,
                headers={
                    "Api-Key": api_key,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            raw_payload = response.json()

        data = raw_payload.get("payload", raw_payload)
        order_uuid = str(data.get("uuid") or data.get("id") or "")
        if not order_uuid:
            raise ValueError("Tribute order response does not contain order uuid")
        return TributeShopOrder(
            order_uuid=order_uuid,
            status=str(data.get("status") or "pending"),
            payment_url=data.get("paymentUrl") or data.get("payment_url"),
            webapp_payment_url=data.get("webAppUrl") or data.get("webapp_payment_url"),
            amount_minor=int(data.get("amount") or amount_minor),
            currency=str(data.get("currency") or currency),
            title=str(data.get("title") or title),
            raw_payload=raw_payload,
        )

    @staticmethod
    def dump_payload(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
