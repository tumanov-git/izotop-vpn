from __future__ import annotations

from urllib.parse import urlencode


def build_happ_deeplink(subscription_url: str) -> str:
    return f"happ://add/{subscription_url}"


def build_happ_link(app_base_url: str, subscription_url: str) -> str:
    base_url = app_base_url.rstrip("/")
    return f"{base_url}/happlink?{urlencode({'link': subscription_url})}"
