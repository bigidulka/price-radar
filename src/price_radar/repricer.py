"""Repricing rules.

The strategy is deliberately simple and explainable, because a seller has to trust it:

1. Look only at competitors that are in stock.
2. Target = cheapest competitor minus a step (absolute roubles or percent).
3. Never go below the floor price (cost + minimum margin + commission).
4. Never go above ``max_price`` (e.g. recommended retail price).
5. If nobody is in stock, raise towards ``max_price`` or by ``raise_pct`` —
   competitors ran out, there is no reason to stay cheap.
6. Ignore changes smaller than ``min_change`` to avoid price flapping.

Every decision carries a human-readable reason that the bot and dashboard show.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Action, Decision, Offer, Product


@dataclass(slots=True)
class Strategy:
    undercut_abs: float = 10.0  # roubles below the leader
    undercut_pct: float = 0.0  # or percent below the leader (takes precedence if > 0)
    raise_pct: float = 7.0  # raise when no competitor is in stock
    min_change: float = 5.0  # ignore smaller moves
    round_to: int = 10  # psychological rounding: 1 990 instead of 1 987.40

    def target_below(self, leader_price: float) -> float:
        if self.undercut_pct > 0:
            return leader_price * (1 - self.undercut_pct / 100)
        return leader_price - self.undercut_abs


def rub(value: float) -> str:
    return f"{value:,.0f}".replace(",", "\u202f") + " ₽"


def _round_down(value: float, step: int) -> float:
    if step <= 1:
        return round(value, 2)
    return float(math.floor(value / step) * step)


def _round_up(value: float, step: int) -> float:
    if step <= 1:
        return round(value, 2)
    return float(math.ceil(value / step) * step)


def decide(product: Product, offers: list[Offer], strategy: Strategy | None = None) -> Decision:
    s = strategy or Strategy()
    floor = _round_up(product.floor_price, s.round_to)
    ceiling = product.max_price
    live = sorted((o for o in offers if o.in_stock and o.price > 0), key=lambda o: o.price)

    def make(action: Action, proposed: float, reason: str, leader: Offer | None = None) -> Decision:
        proposed = round(proposed, 2)
        if action in (Action.LOWER, Action.RAISE) and abs(proposed - product.price) < s.min_change:
            action, proposed = Action.KEEP, product.price
            reason = f"{reason}; изменение меньше {s.min_change:g} ₽ — цену не трогаем"
        return Decision(
            sku=product.sku,
            action=action,
            current=product.price,
            proposed=proposed,
            reason=reason,
            margin_pct=product.margin_at(proposed),
            leader=leader,
        )

    if not live:
        if not offers:
            return make(Action.KEEP, product.price, "нет данных по конкурентам")
        target = product.price * (1 + s.raise_pct / 100)
        if ceiling:
            target = min(target, ceiling)
        target = max(_round_down(target, s.round_to), floor)
        if target <= product.price:
            return make(Action.KEEP, product.price, "у конкурентов нет в наличии, цена уже на потолке")
        return make(Action.RAISE, target, f"у всех {len(offers)} конкурентов нет в наличии — поднимаем")

    leader = live[0]
    target = _round_down(s.target_below(leader.price), s.round_to)
    if ceiling:
        target = min(target, ceiling)

    if target < floor:
        if product.price <= floor:
            return make(Action.HOLD_FLOOR, floor if product.price < floor else product.price,
                        f"{leader.seller} продаёт за {rub(leader.price)} — ниже нашего минимума "
                        f"{rub(floor)}, не демпингуем", leader)
        return make(Action.HOLD_FLOOR, floor,
                    f"{leader.seller} за {rub(leader.price)} ниже минимума — опускаемся только до "
                    f"{rub(floor)}", leader)

    if target < product.price:
        return make(Action.LOWER, target,
                    f"лидер {leader.seller} — {rub(leader.price)}, встаём ниже", leader)
    if target > product.price:
        return make(Action.RAISE, target,
                    f"дешевле всех и с запасом: лидер {leader.seller} — {rub(leader.price)}, "
                    f"поднимаем до шага ниже него", leader)
    return make(Action.KEEP, product.price, "цена уже оптимальна", leader)
