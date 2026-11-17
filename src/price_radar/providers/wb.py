"""Wildberries public card API.

WB serves product cards to its own frontend from ``card.wb.ru``. Prices there are in
kopecks, stock is the sum of ``sizes[].stocks[].qty``. Since 2025 the endpoint is
protected by an antibot and is geo-dependent, so production use needs a regional
egress (``PRICE_RADAR_PROXY``) and polite request rates. Parsing is kept separate
from transport so it is covered by fixture tests.
"""
from __future__ import annotations

import re

import httpx

from ..models import Offer
from .base import ProviderError

CARD_URL = "https://card.wb.ru/cards/v4/detail"
_NM = re.compile(r"/catalog/(\d+)/")


def nm_id(url: str) -> int:
    m = _NM.search(url)
    if not m:
        raise ProviderError(f"не нашёл артикул WB в ссылке: {url}")
    return int(m.group(1))


def parse_card(payload: dict, url: str) -> Offer:
    products = payload.get("products") or payload.get("data", {}).get("products") or []
    if not products:
        raise ProviderError("WB вернул пустую карточку — товар снят или ссылка неверна")
    p = products[0]
    sizes = p.get("sizes") or []
    price_kop = None
    qty = 0
    for size in sizes:
        price = size.get("price") or {}
        value = price.get("product") or price.get("total")
        if value and (price_kop is None or value < price_kop):
            price_kop = value
        qty += sum(int(s.get("qty", 0)) for s in size.get("stocks") or [])
    if price_kop is None:
        price_kop = p.get("salePriceU") or p.get("priceU")
    if not price_kop:
        raise ProviderError("в карточке WB нет цены")
    return Offer(
        source="wb",
        url=url,
        title=p.get("name", ""),
        seller=p.get("supplier") or p.get("brand") or "WB seller",
        price=round(price_kop / 100, 2),
        in_stock=qty > 0 or bool(p.get("totalQuantity")),
    )


class WildberriesProvider:
    name = "wb"

    def __init__(self, proxy: str | None = None, dest: int = -1257786, timeout: float = 20) -> None:
        self.proxy = proxy
        self.dest = dest
        self.timeout = timeout

    async def fetch(self, url: str) -> Offer:
        params = {"appType": 1, "curr": "rub", "dest": self.dest, "nm": nm_id(url)}
        async with httpx.AsyncClient(proxy=self.proxy, timeout=self.timeout,
                                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as c:
            r = await c.get(CARD_URL, params=params)
        if r.status_code in (403, 429, 498):
            raise ProviderError(f"WB ограничил доступ (HTTP {r.status_code}) — нужен региональный выход или пауза")
        if r.status_code != 200:
            raise ProviderError(f"WB HTTP {r.status_code}")
        return parse_card(r.json(), url)
