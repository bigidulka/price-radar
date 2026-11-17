"""Price sources. Each provider turns a listing URL into an :class:`Offer`."""
from __future__ import annotations

from urllib.parse import urlparse

from .base import Provider, ProviderError
from .demo import DemoProvider
from .ozon import OzonProvider
from .wb import WildberriesProvider

__all__ = ["Provider", "ProviderError", "DemoProvider", "OzonProvider", "WildberriesProvider", "detect_source"]


def detect_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.endswith("wildberries.ru") or host.endswith("wildberries.by") or host.endswith("wb.ru"):
        return "wb"
    if "ozon." in host:
        return "ozon"
    if url.startswith("demo://"):
        return "demo"
    raise ProviderError(f"неизвестная площадка: {host or url}")
