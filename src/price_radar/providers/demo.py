"""Deterministic synthetic market for demos and tests.

URLs look like ``demo://<seller>/<sku>``. The price follows a seeded random walk
around a base price so the dashboard has a realistic-looking history, and the same
(url, tick) always yields the same price. **The numbers are synthetic** and are
labelled as such everywhere they are shown.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from ..models import Offer
from .base import ProviderError


class DemoProvider:
    name = "demo"

    def __init__(self, base_prices: dict[str, float], titles: dict[str, str] | None = None,
                 start: datetime | None = None, step: timedelta = timedelta(hours=6)) -> None:
        self.base_prices = base_prices
        self.titles = titles or {}
        self.start = start or datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.step = step
        self.tick = 0

    def _rng(self, url: str, tick: int) -> random.Random:
        seed = int(hashlib.sha256(f"{url}|{tick}".encode()).hexdigest()[:12], 16)
        return random.Random(seed)

    def price_at(self, url: str, tick: int) -> tuple[float, bool]:
        if url not in self.base_prices:
            raise ProviderError(f"нет такой демо-позиции: {url}")
        # mean-reverting noise around the base price: competitors react, run promos,
        # come back — they do not drift to zero
        deviation = 0.0
        in_stock = True
        for t in range(tick + 1):
            rng = self._rng(url, t)
            deviation = 0.65 * deviation + rng.gauss(0, 0.025)
            in_stock = rng.random() > 0.1
        price = self.base_prices[url] * (1 + deviation)
        return float(round(price / 10) * 10 - 10), in_stock

    async def fetch(self, url: str) -> Offer:
        price, in_stock = self.price_at(url, self.tick)
        seller = url.removeprefix("demo://").split("/")[0]
        return Offer(source="demo", url=url, title=self.titles.get(url, url), seller=seller, price=price,
                     in_stock=in_stock, seen_at=self.start + self.step * self.tick)
