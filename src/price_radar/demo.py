"""Demo catalogue: auto parts sold on a marketplace, with synthetic competitors.

All prices and seller names here are invented for the demo.
"""
from __future__ import annotations

from .models import Product
from .providers import DemoProvider
from .storage import Store

PRODUCTS = [
    Product("OF-712-95", "Фильтр масляный", "MANN-FILTER", "03C115561H", cost=520, price=890,
            min_margin_pct=20, max_price=990, commission_pct=15),
    Product("BP-1550", "Колодки тормозные передние", "TRW", "1K0698151", cost=2150, price=3390,
            min_margin_pct=18, max_price=3790, commission_pct=15),
    Product("SP-ILZKR7", "Свеча зажигания (комплект 4 шт.)", "NGK", "101905601F", cost=2480, price=3990,
            min_margin_pct=15, max_price=4490, commission_pct=15),
    Product("AF-C27009", "Фильтр воздушный", "MANN-FILTER", "1F0129620", cost=610, price=1090,
            min_margin_pct=20, max_price=1190, commission_pct=15),
    Product("TB-K015578", "Комплект ГРМ с помпой", "GATES", "06H198119", cost=9800, price=14900,
            min_margin_pct=12, max_price=15900, commission_pct=12),
    Product("WB-713610", "Подшипник ступицы передний", "SKF", "8V0498625", cost=3350, price=5290,
            min_margin_pct=15, max_price=5690, commission_pct=15),
]

SELLERS = ["АвтоДеталь+", "ZapMarket", "Partsy", "МоторПро"]

# relative price level of each synthetic competitor vs our starting price
_LEVEL = {"АвтоДеталь+": 0.98, "ZapMarket": 1.03, "Partsy": 0.96, "МоторПро": 1.07}
# one seller dumps below our cost on one item: the repricer must not follow
_OVERRIDE = {("Partsy", "WB-713610"): 0.78}


def build(store: Store) -> DemoProvider:
    base: dict[str, float] = {}
    titles: dict[str, str] = {}
    for p in PRODUCTS:
        store.upsert_product(p)
        for seller in SELLERS:
            url = f"demo://{seller}/{p.sku}"
            base[url] = p.price * _OVERRIDE.get((seller, p.sku), _LEVEL[seller])
            titles[url] = f"{p.brand} {p.title} {p.oem}"
            store.add_watch(p.sku, "demo", url)
    return DemoProvider(base, titles)


async def simulate(store: Store, ticks: int = 28) -> DemoProvider:
    """Seed the store and run ``ticks`` refresh cycles (6h each) applying decisions."""
    from .service import Radar

    provider = build(store)
    radar = Radar(store, {"demo": provider})
    for t in range(ticks):
        provider.tick = t
        await radar.refresh(apply=t < ticks - 1, now=provider.start + provider.step * t)  # last tick: show pending recommendations
    return provider
