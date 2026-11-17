import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from io import BytesIO

from price_radar import demo
from price_radar.bot import digest, parse_add
from price_radar.export import workbook_bytes
from price_radar.models import Action, Offer, Product
from price_radar.providers import ProviderError
from price_radar.service import Radar
from price_radar.storage import Store
from price_radar.view import render, snapshot
from price_radar.web import create_app


class FakeProvider:
    name = "fake"

    def __init__(self, prices: dict[str, float | Exception]):
        self.prices = prices

    async def fetch(self, url: str) -> Offer:
        v = self.prices[url]
        if isinstance(v, Exception):
            raise v
        return Offer(source="fake", url=url, title="t", seller=url, price=v,
                     seen_at=datetime(2026, 11, 17, tzinfo=timezone.utc))


def make_radar(prices) -> Radar:
    store = Store()
    store.upsert_product(Product("A", "Фильтр", cost=500, price=900, min_margin_pct=20, commission_pct=15))
    for url in prices:
        store.add_watch("A", "fake", url)
    return Radar(store, {"fake": FakeProvider(prices)})


def test_refresh_survives_failing_source_and_applies():
    radar = make_radar({"s1": 860.0, "s2": ProviderError("blocked")})
    report = asyncio.run(radar.refresh(apply=True))
    assert report.fetched == 1
    assert report.failed == [("s2", "blocked")]
    assert [d.sku for d in report.applied] == ["A"]
    assert radar.store.product("A").price == 850
    assert radar.store.price_changes("A")[0]["old_price"] == 900
    assert "Не удалось: 1" in digest(report, radar.store)


def test_same_observation_is_not_duplicated():
    radar = make_radar({"s1": 860.0})
    asyncio.run(radar.refresh())
    report = asyncio.run(radar.refresh())  # same timestamp from the fake provider
    assert report.fetched == 0
    assert len(radar.store.history("A")) == 1


def test_demo_simulation_end_to_end():
    store = Store()
    asyncio.run(demo.simulate(store, ticks=12))
    snap = snapshot(store)
    assert len(snap["rows"]) == len(demo.PRODUCTS)
    for row in snap["rows"]:
        p = row["product"]
        assert p.price >= p.floor_price - 10  # repricer never sold below the floor (rounding step)
        assert row["chart"]["lines"]
    html = render(snap, demo=True)
    assert "синтетические" in html and "MANN-FILTER" in html
    wb = load_workbook(BytesIO(workbook_bytes(store)))
    assert wb.sheetnames == ["Рекомендации", "Конкуренты"]
    assert wb["Рекомендации"].max_row == len(demo.PRODUCTS) + 1


def test_web_api():
    radar = make_radar({"s1": 860.0})
    asyncio.run(radar.refresh())
    client = TestClient(create_app(radar))
    assert client.get("/").status_code == 200
    data = client.get("/api/products").json()
    assert data[0]["decision"]["action"] == Action.LOWER.value
    assert client.get("/api/products/A/offers").json()[0]["price"] == 860.0
    assert client.get("/api/products/nope/offers").status_code == 404
    assert client.get("/export.xlsx").headers["content-type"].startswith("application/vnd.openxml")


def test_parse_add():
    p = parse_add("OF-712 520 890 20 15 Фильтр масляный MANN")
    assert (p.sku, p.cost, p.price, p.min_margin_pct, p.commission_pct) == ("OF-712", 520, 890, 20, 15)
    assert p.title == "Фильтр масляный MANN"
    p = parse_add("X 100,5 200 Свеча")
    assert p.cost == 100.5 and p.min_margin_pct == 15 and p.title == "Свеча"
