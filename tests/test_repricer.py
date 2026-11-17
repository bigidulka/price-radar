from price_radar.models import Action, Offer, Product
from price_radar.repricer import Strategy, decide


def product(**kw) -> Product:
    base = dict(sku="A", title="Фильтр", cost=500, price=900, min_margin_pct=20, commission_pct=15, max_price=1000)
    base.update(kw)
    return Product(**base)


def offer(price: float, seller: str = "X", in_stock: bool = True) -> Offer:
    return Offer(source="demo", url=f"demo://{seller}", title="", seller=seller, price=price, in_stock=in_stock)


def test_floor_price_includes_margin_and_commission():
    p = product()
    assert p.floor_price == round(500 * 1.2 / 0.85, 2)  # 705.88
    assert p.margin_at(p.floor_price) == 20.0


def test_lowers_one_step_below_leader():
    d = decide(product(), [offer(950, "B"), offer(860, "A")])
    assert d.action is Action.LOWER
    assert d.proposed == 850  # 860 - 10, rounded down to tens
    assert d.leader.seller == "A"


def test_never_goes_below_floor():
    d = decide(product(), [offer(650)])  # floor rounds up to 710
    assert d.action is Action.HOLD_FLOOR
    assert d.proposed == 710
    assert d.margin_pct >= 20


def test_already_at_floor_keeps_price_when_dumped():
    d = decide(product(price=710), [offer(600)])
    assert d.action is Action.HOLD_FLOOR
    assert d.proposed == 710 and d.delta == 0


def test_raises_when_cheapest_with_headroom_but_respects_ceiling():
    d = decide(product(price=700), [offer(1200)])
    assert d.action is Action.RAISE
    assert d.proposed == 1000  # capped by max_price


def test_out_of_stock_competitors_ignored_and_raise():
    d = decide(product(), [offer(500, in_stock=False), offer(510, "B", in_stock=False)])
    assert d.action is Action.RAISE
    assert d.proposed == 960  # 900 * 1.07 = 963 -> 960


def test_small_moves_are_suppressed():
    d = decide(product(price=850), [offer(862)], Strategy(min_change=5))
    assert d.action is Action.KEEP and d.proposed == 850


def test_percent_undercut():
    d = decide(product(), [offer(880)], Strategy(undercut_pct=2, round_to=1))
    assert d.proposed == round(880 * 0.98, 2)


def test_reason_keeps_punctuation_and_groups_thousands():
    d = decide(product(cost=5000, price=9000, max_price=None), [offer(8600, "A")])
    assert "8 600 ₽, встаём ниже" in d.reason


def test_no_data():
    d = decide(product(), [])
    assert d.action is Action.KEEP and "нет данных" in d.reason
