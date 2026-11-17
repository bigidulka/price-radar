"""View model shared by the live dashboard, the static demo site and the Excel export."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Action
from .repricer import Strategy, decide, rub
from .storage import Store

TEMPLATES = Path(__file__).parent / "templates"

ACTION_LABEL = {
    Action.LOWER: ("Снизить", "lower"),
    Action.RAISE: ("Поднять", "raise"),
    Action.HOLD_FLOOR: ("Держим минимум", "floor"),
    Action.KEEP: ("Без изменений", "keep"),
}


@dataclass(slots=True)
class Series:
    name: str
    points: list[tuple[datetime, float]]


def _sparkline(series: list[Series], width: int = 260, height: int = 64) -> dict:
    pts = [p for s in series for p in s.points]
    if len(pts) < 2:
        return {"width": width, "height": height, "lines": []}
    t0 = min(t for t, _ in pts).timestamp()
    t1 = max(t for t, _ in pts).timestamp() or t0 + 1
    lo = min(v for _, v in pts)
    hi = max(v for _, v in pts)
    span_v = (hi - lo) or 1
    span_t = (t1 - t0) or 1
    lines = []
    for s in series:
        coords = " ".join(
            f"{(t.timestamp() - t0) / span_t * (width - 4) + 2:.1f},"
            f"{height - 2 - (v - lo) / span_v * (height - 4):.1f}"
            for t, v in s.points
        )
        lines.append({"name": s.name, "points": coords})
    return {"width": width, "height": height, "lines": lines, "lo": lo, "hi": hi}


def snapshot(store: Store, strategy: Strategy | None = None) -> dict:
    rows = []
    totals = defaultdict(int)
    for p in store.products():
        offers = store.latest_offers(p.sku)
        d = decide(p, offers, strategy)
        label, css = ACTION_LABEL[d.action]
        totals[css] += 1

        history = store.history(p.sku)
        leader_by_time: dict[datetime, float] = {}
        for o in history:
            if o.in_stock:
                leader_by_time[o.seen_at] = min(o.price, leader_by_time.get(o.seen_at, o.price))
        changes = list(reversed(store.price_changes(p.sku, limit=1000)))
        ours: list[tuple[datetime, float]] = []
        if changes:
            ours.append((min(leader_by_time) if leader_by_time else datetime.fromisoformat(changes[0]["changed_at"]),
                         changes[0]["old_price"]))
            ours += [(datetime.fromisoformat(c["changed_at"]), c["new_price"]) for c in changes]
        if leader_by_time:
            ours.append((max(leader_by_time), p.price))
        chart = _sparkline([
            Series("Лучшая цена конкурента", sorted(leader_by_time.items())),
            Series("Наша цена", sorted(ours)),
        ])
        rows.append({
            "product": p,
            "decision": d,
            "action_label": label,
            "action_css": css,
            "offers": offers,
            "floor": p.floor_price,
            "chart": chart,
            "changes": store.price_changes(p.sku, limit=5),
            "position": 1 + sum(1 for o in offers if o.in_stock and o.price < p.price),
            "competitors": len(offers),
        })
    last_seen = max((o.seen_at for r in rows for o in r["offers"]), default=None)
    return {"rows": rows, "totals": dict(totals), "last_seen": last_seen}


def render(context: dict, *, demo: bool) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters["rub"] = lambda v: rub(v) if v is not None else "—"
    env.filters["dt"] = lambda v: v.strftime("%d.%m %H:%M") if v else "—"
    return env.get_template("dashboard.html").render(**context, demo=demo)
