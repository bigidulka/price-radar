"""Telegram bot (aiogram 3).

Commands
--------
/add SKU себестоимость цена [мин.маржа%] [комиссия%] Название — добавить товар
/track SKU ссылка — следить за карточкой конкурента (Ozon / WB)
/list — товары и рекомендации
/check — обновить цены сейчас
/apply SKU — принять рекомендацию по товару
/export — Excel-отчёт
/untrack ID, /remove SKU — убрать

Only user ids from ``PRICE_RADAR_ADMINS`` can use the bot: it manages prices.
A background loop refreshes every ``interval`` minutes and sends a digest of the
products that need attention.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .export import workbook_bytes
from .repricer import rub
from .models import Action, Product, utcnow
from .providers import ProviderError, detect_source
from .service import Radar, RefreshReport, format_decision

log = logging.getLogger(__name__)

HELP = (
    "Price Radar — слежу за ценами конкурентов и подсказываю цену.\n\n"
    "/add SKU себестоимость цена [маржа%] [комиссия%] Название\n"
    "  пример: /add OF-712 520 890 20 15 Фильтр масляный MANN W712/95\n"
    "/track SKU ссылка — карточка конкурента на Ozon или WB\n"
    "/list — товары и рекомендации\n"
    "/check — обновить цены сейчас\n"
    "/apply SKU — принять рекомендацию\n"
    "/export — Excel-отчёт\n"
    "/untrack ID · /remove SKU"
)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_add(args: str) -> Product:
    parts = args.split()
    if len(parts) < 3:
        raise ValueError("нужно минимум: SKU себестоимость цена")
    sku, cost, price = parts[0], _num(parts[1]), _num(parts[2])
    rest = parts[3:]
    nums: list[float] = []
    while rest and len(nums) < 2:
        try:
            nums.append(_num(rest[0].rstrip("%")))
            rest = rest[1:]
        except ValueError:
            break
    margin = nums[0] if nums else 15.0
    commission = nums[1] if len(nums) > 1 else 0.0
    if cost <= 0 or price <= 0:
        raise ValueError("себестоимость и цена должны быть больше нуля")
    return Product(sku=sku, title=" ".join(rest) or sku, cost=cost, price=price,
                   min_margin_pct=margin, commission_pct=commission)


def build_router(radar: Radar, admins: set[int]) -> Router:
    router = Router()
    store = radar.store

    @router.message.outer_middleware()
    async def only_admins(handler, event: Message, data):
        if admins and (event.from_user is None or event.from_user.id not in admins):
            return None
        return await handler(event, data)

    @router.message(Command("start", "help"))
    async def start(m: Message) -> None:
        await m.answer(HELP)

    @router.message(Command("add"))
    async def add(m: Message, command: CommandObject) -> None:
        try:
            p = parse_add(command.args or "")
        except ValueError as e:
            await m.answer(f"Не понял: {e}\n\n{HELP}")
            return
        store.upsert_product(p)
        await m.answer(f"Добавил {p.sku}: {p.title}\nминимальная цена {rub(p.floor_price)}")

    @router.message(Command("track"))
    async def track(m: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if len(parts) != 2:
            await m.answer("Формат: /track SKU ссылка")
            return
        sku, url = parts
        try:
            source = detect_source(url)
            w = store.add_watch(sku, source, url)
        except (ProviderError, KeyError) as e:
            await m.answer(f"Не получилось: {e}")
            return
        await m.answer(f"Слежу (#{w.id}, {source}). Первая цена появится после /check.")

    @router.message(Command("list"))
    async def list_(m: Message) -> None:
        products = store.products()
        if not products:
            await m.answer("Пока пусто. Начните с /add")
            return
        for p in products:
            d = radar.decide(p)
            kb = None
            if d.action is not Action.KEEP and d.delta:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text=f"Применить {rub(d.proposed)}", callback_data=f"apply:{p.sku}")]])
            await m.answer(format_decision(d, p.title), reply_markup=kb)

    async def _apply(sku: str) -> str:
        p = store.product(sku)
        if p is None:
            return "Нет такого SKU"
        d = radar.decide(p)
        if d.action is Action.KEEP or not d.delta:
            return "Менять нечего — цена уже оптимальна"
        store.set_price(sku, d.proposed, d.reason, utcnow())
        return f"Готово: {sku} теперь {rub(d.proposed)}. Не забудьте выгрузить цену на площадку."

    @router.message(Command("apply"))
    async def apply(m: Message, command: CommandObject) -> None:
        await m.answer(await _apply((command.args or "").strip()))

    @router.callback_query(F.data.startswith("apply:"))
    async def apply_cb(c: CallbackQuery) -> None:
        if admins and c.from_user.id not in admins:
            await c.answer()
            return
        text = await _apply(c.data.split(":", 1)[1])
        await c.answer(text[:190], show_alert=False)
        if c.message:
            await c.message.answer(text)

    @router.message(Command("check"))
    async def check(m: Message) -> None:
        await m.answer("Обновляю…")
        await m.answer(digest(await radar.refresh(), store))

    @router.message(Command("export"))
    async def export(m: Message) -> None:
        data = workbook_bytes(store, radar.strategy)
        await m.answer_document(BufferedInputFile(data, filename="price-radar.xlsx"), caption="Отчёт по ценам")

    @router.message(Command("untrack"))
    async def untrack(m: Message, command: CommandObject) -> None:
        ok = (command.args or "").strip().isdigit() and store.remove_watch(int(command.args))
        await m.answer("Убрал" if ok else "Нет такого ID")

    @router.message(Command("remove"))
    async def remove(m: Message, command: CommandObject) -> None:
        await m.answer("Удалил" if store.delete_product((command.args or "").strip()) else "Нет такого SKU")

    return router


def digest(report: RefreshReport, store) -> str:
    lines = [f"Обновлено карточек: {report.fetched}"]
    if report.failed:
        lines.append(f"Не удалось: {len(report.failed)} (" + "; ".join(e for _, e in report.failed[:3]) + ")")
    if not report.actionable:
        lines.append("Все цены в порядке ✅")
    for d in report.actionable:
        p = store.product(d.sku)
        lines.append("\n" + format_decision(d, p.title if p else ""))
    return "\n".join(lines)


async def run(token: str, radar: Radar, admins: set[int], interval_min: int = 30) -> None:
    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(build_router(radar, admins))

    async def scheduler() -> None:
        while True:
            await asyncio.sleep(interval_min * 60)
            try:
                report = await radar.refresh()
            except Exception:  # keep the loop alive; the next tick retries
                log.exception("scheduled refresh failed")
                continue
            if report.actionable or report.failed:
                for admin in admins:
                    await bot.send_message(admin, digest(report, radar.store))

    task = asyncio.create_task(scheduler())
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
