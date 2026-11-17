"""Ozon via `ozon-client <https://github.com/bigidulka/ozon-client>`_.

Ozon product pages are rendered from a layout envelope behind an antibot; plain HTTP
gets challenged. ``ozon-client`` solves that with a warm browser session (CDP) and
parses ``widgetStates``. It is an optional dependency: ``pip install price-radar[ozon]``.
"""
from __future__ import annotations

import asyncio
import re

from ..models import Offer
from .base import ProviderError

_SKU = re.compile(r"/product/(?:[^/?#]*-)?(\d{5,})(?:[/?#]|$)")


def ozon_sku(url: str) -> str:
    m = _SKU.search(url)
    if not m:
        raise ProviderError(f"не нашёл SKU Ozon в ссылке: {url}")
    return m.group(1)


def parse_price(text: str | None) -> float | None:
    """'1 990 ₽' / '1 990,50 ₽' → 1990.0 / 1990.5"""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.]", "", text.replace(" ", "").replace("\xa0", "")).replace(",", ".")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def parse_product(card: dict, url: str) -> Offer:
    """Map ``OzonClient.product()`` output to an :class:`Offer`."""
    block = card.get("price") if isinstance(card.get("price"), dict) else {}
    price = parse_price(block.get("price"))
    if price is None:
        raise ProviderError("в карточке Ozon нет цены (товар снят или закончился)")
    seller = card.get("seller") if isinstance(card.get("seller"), dict) else {}
    available = block.get("is_available")
    return Offer(
        source="ozon",
        url=url,
        title=card.get("title") or card.get("heading") or "",
        seller=seller.get("name") or "Ozon seller",
        price=price,
        in_stock=True if available is None else bool(available),
    )


class OzonProvider:
    name = "ozon"

    def __init__(self, cdp: str | None = None) -> None:
        self.cdp = cdp
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from ozon_client import OzonClient  # type: ignore
            except ImportError as e:  # pragma: no cover - optional dependency
                raise ProviderError("для Ozon установите extra: pip install 'price-radar[ozon]'") from e
            self._client = OzonClient(cdp=self.cdp)
        return self._client

    async def fetch(self, url: str) -> Offer:
        sku = ozon_sku(url)
        client = self._get_client()
        try:
            card = await asyncio.to_thread(client.product, sku)
        except Exception as e:  # antibot, removed listing, markup change
            raise ProviderError(f"Ozon: {type(e).__name__}: {e}") from e
        return parse_product(card, url)
