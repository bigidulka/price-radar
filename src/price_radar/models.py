"""Domain model: own products, competitor offers and repricing decisions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass(slots=True)
class Product:
    """A product we sell. Prices are in roubles."""

    sku: str
    title: str
    brand: str = ""
    oem: str = ""  # original part number, used to match competitors
    cost: float = 0.0  # purchase cost per unit
    price: float = 0.0  # our current shelf price
    min_margin_pct: float = 15.0  # never reprice below cost * (1 + margin)
    max_price: float | None = None  # upper bound, e.g. recommended retail price
    channel: str = "ozon"
    commission_pct: float = 0.0  # marketplace fee taken from the sale price

    @property
    def floor_price(self) -> float:
        """Lowest price that still keeps the minimum margin after commission."""
        keep = 1 - self.commission_pct / 100
        if keep <= 0:
            raise ValueError("commission must be below 100%")
        return round(self.cost * (1 + self.min_margin_pct / 100) / keep, 2)

    def margin_at(self, price: float) -> float:
        """Margin in percent of cost at a given shelf price, after commission."""
        if self.cost <= 0:
            return 0.0
        net = price * (1 - self.commission_pct / 100)
        return round((net - self.cost) / self.cost * 100, 1)


@dataclass(slots=True)
class Offer:
    """One observation of a competitor listing."""

    source: str  # ozon / wb / demo ...
    url: str
    title: str
    seller: str
    price: float
    in_stock: bool = True
    seen_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class Watch:
    """Link between our product and a competitor listing we track."""

    id: int
    sku: str
    source: str
    url: str


class Action(str, Enum):
    KEEP = "keep"
    LOWER = "lower"
    RAISE = "raise"
    HOLD_FLOOR = "hold_floor"  # competitor is below our floor; we do not follow


@dataclass(slots=True)
class Decision:
    sku: str
    action: Action
    current: float
    proposed: float
    reason: str
    margin_pct: float
    leader: Offer | None = None

    @property
    def delta(self) -> float:
        return round(self.proposed - self.current, 2)
