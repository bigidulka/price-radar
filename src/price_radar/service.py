"""Orchestration: poll providers, store observations, compute decisions, build alerts."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from .models import Action, Decision, Offer, Product, utcnow
from .providers import Provider, ProviderError
from .repricer import Strategy, decide, rub
from .storage import Store

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RefreshReport:
    fetched: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (url, error)
    decisions: list[Decision] = field(default_factory=list)
    applied: list[Decision] = field(default_factory=list)

    @property
    def actionable(self) -> list[Decision]:
        return [d for d in self.decisions if d.action is not Action.KEEP and d.delta != 0]


class Radar:
    def __init__(self, store: Store, providers: dict[str, Provider], strategy: Strategy | None = None,
                 concurrency: int = 4) -> None:
        self.store = store
        self.providers = providers
        self.strategy = strategy or Strategy()
        self._sem = asyncio.Semaphore(concurrency)

    async def _fetch(self, source: str, url: str) -> Offer:
        provider = self.providers.get(source)
        if provider is None:
            raise ProviderError(f"источник {source} не подключён")
        async with self._sem:
            return await provider.fetch(url)

    async def refresh(self, *, apply: bool = False, now: datetime | None = None) -> RefreshReport:
        """Fetch every tracked listing once, then compute a decision per product.

        A failing source never aborts the run: it is reported and the product is
        decided on the remaining (latest known) offers.
        """
        report = RefreshReport()
        watches = self.store.watches()
        results = await asyncio.gather(*(self._fetch(w.source, w.url) for w in watches), return_exceptions=True)
        for w, res in zip(watches, results):
            if isinstance(res, Exception):
                report.failed.append((w.url, str(res)))
                log.warning("fetch failed %s: %s", w.url, res)
                continue
            if self.store.record_offer(w, res):
                report.fetched += 1
        for product in self.store.products():
            d = self.decide(product)
            report.decisions.append(d)
            if apply and d.action is not Action.KEEP and d.delta != 0:
                self.store.set_price(product.sku, d.proposed, d.reason, now or utcnow())
                report.applied.append(d)
        return report

    def decide(self, product: Product) -> Decision:
        return decide(product, self.store.latest_offers(product.sku), self.strategy)


def format_decision(d: Decision, title: str = "") -> str:
    icon = {Action.LOWER: "🔻", Action.RAISE: "🔺", Action.HOLD_FLOOR: "🛑", Action.KEEP: "✅"}[d.action]
    head = f"{icon} {d.sku} {title}".strip()
    price = f"{rub(d.current)} → {rub(d.proposed)}" if d.delta else rub(d.current)
    return f"{head}\n{price} · маржа {d.margin_pct:g}%\n{d.reason}"
