"""FastAPI dashboard and JSON API."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

from .export import workbook_bytes
from .service import Radar
from .view import render, snapshot


def create_app(radar: Radar, *, demo: bool = False) -> FastAPI:
    app = FastAPI(title="Price Radar", version="0.1.0")
    store = radar.store

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return render(snapshot(store, radar.strategy), demo=demo)

    @app.get("/api/products")
    def products() -> list[dict]:
        out = []
        for p in store.products():
            d = radar.decide(p)
            out.append({**asdict(p), "floor_price": p.floor_price,
                        "decision": {"action": d.action.value, "proposed": d.proposed, "delta": d.delta,
                                     "margin_pct": d.margin_pct, "reason": d.reason}})
        return out

    @app.get("/api/products/{sku}/offers")
    def offers(sku: str) -> list[dict]:
        if store.product(sku) is None:
            raise HTTPException(404, "unknown sku")
        return [{**asdict(o), "seen_at": o.seen_at.isoformat()} for o in store.latest_offers(sku)]

    @app.post("/api/refresh")
    async def refresh(apply: bool = False) -> dict:
        report = await radar.refresh(apply=apply)
        return {"fetched": report.fetched, "failed": report.failed,
                "actionable": [d.sku for d in report.actionable], "applied": [d.sku for d in report.applied]}

    @app.get("/export.xlsx")
    def export() -> Response:
        return Response(workbook_bytes(store, radar.strategy),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="price-radar.xlsx"'})

    return app
