"""Excel report: one sheet with recommendations, one with every competitor offer."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .repricer import Strategy
from .storage import Store
from .view import snapshot

FILL = {
    "lower": PatternFill("solid", fgColor="FDE2E1"),
    "raise": PatternFill("solid", fgColor="DDF3E4"),
    "floor": PatternFill("solid", fgColor="FFF1CC"),
}


def _autosize(ws) -> None:
    for i, col in enumerate(ws.columns, 1):
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 60)


def workbook_bytes(store: Store, strategy: Strategy | None = None) -> bytes:
    snap = snapshot(store, strategy)
    wb = Workbook()
    ws = wb.active
    ws.title = "Рекомендации"
    ws.append(["SKU", "Товар", "Бренд", "OEM", "Себестоимость", "Мин. цена", "Текущая цена",
               "Рекомендуемая", "Изменение", "Маржа, %", "Место по цене", "Действие", "Причина"])
    for r in snap["rows"]:
        p, d = r["product"], r["decision"]
        ws.append([p.sku, p.title, p.brand, p.oem, p.cost, r["floor"], d.current, d.proposed, d.delta,
                   d.margin_pct, f"{r['position']} из {r['competitors'] + 1}", r["action_label"], d.reason])
        fill = FILL.get(r["action_css"])
        if fill:
            for cell in ws[ws.max_row]:
                cell.fill = fill
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.freeze_panes = "A2"
    _autosize(ws)

    ws2 = wb.create_sheet("Конкуренты")
    ws2.append(["SKU", "Площадка", "Продавец", "Цена", "В наличии", "Обновлено", "Ссылка"])
    for r in snap["rows"]:
        for o in r["offers"]:
            ws2.append([r["product"].sku, o.source, o.seller, o.price, "да" if o.in_stock else "нет",
                        o.seen_at.strftime("%Y-%m-%d %H:%M"), o.url])
    for c in ws2[1]:
        c.font = Font(bold=True)
    ws2.freeze_panes = "A2"
    _autosize(ws2)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
