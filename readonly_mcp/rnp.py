"""Compact order pulse by marketplace SKU."""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel

from ozon_mcp import server as ozon_server
from wb_mcp import server as wb_server

MSK = timezone(timedelta(hours=3))
DAY = timedelta(days=1)
Market = Literal["all", "wb", "ozon"]
PAGE = 1000


class SourceError(ValueError):
    pass


def source(server, operation):
    async def request(query, body):
        spec = server.catalog.get(operation)
        if spec.safety != "read":
            raise RuntimeError("Report requires a read-only API endpoint")
        result = await server.client.call_spec(spec, query=query, json_body=body)
        if not result.get("ok"):
            code = result.get("code")
            raise SourceError(f"API {code}" if isinstance(code, int) else "API недоступен")
        return result["data"]
    return request


async def pages(request, body, unpack):
    offset = 0
    for _ in range(2000):
        rows = unpack(await request(None, {**body, "offset": offset, "limit": PAGE}))
        if not isinstance(rows, list):
            raise SourceError("Неожиданный формат API")
        if not rows:
            return
        yield rows
        offset += len(rows)
        if offset >= 200_000:
            break
    raise SourceError("Достигнут предел выгрузки API")


def metric(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise SourceError("Некорректный показатель API")
    return value


async def wb_rows(request, start, end):
    body = {"selectedPeriod": {"start": str(start), "end": str(end)},
            "pastPeriod": {"start": str(start - 7 * DAY), "end": str(start - DAY)},
            "skipDeletedNm": False, "orderBy": {"field": "orderSum", "mode": "desc"}}

    def unpack(result):
        data = result["data"]
        if data["currency"] != "RUB":
            raise SourceError("Отчёт WB использует валюту, отличную от RUB")
        return data["products"]

    rows = {}
    async for batch in pages(request, body, unpack):
        for row in batch:
            product, stat = row["product"], row["statistic"]
            sku = str(product["nmId"])
            current, prev = stat["selected"], stat["past"]
            rows[sku] = (sku, product.get("vendorCode") or "", product["title"],
                         metric(current["orderCount"]), metric(current["orderSum"]),
                         metric(prev["orderCount"]), metric(prev["orderSum"]))
    return rows.values()


async def ozon_rows(request, start, end):
    body = {"date_from": str(start - 7 * DAY), "date_to": str(end),
            "metrics": ["ordered_units", "revenue"], "dimension": ["sku", "day"],
            "sort": [{"key": "revenue", "order": "DESC"}]}
    rows = {}
    seen = set()
    async for batch in pages(request, body, lambda reply: reply["result"]["data"]):
        for row in batch:
            product, day = row["dimensions"]
            sku, day = str(product["id"]), date.fromisoformat(day["id"])
            if (sku, day) in seen:
                raise SourceError("Повтор SKU и даты в выгрузке Ozon")
            seen.add((sku, day))
            if not start - 7 * DAY <= day <= end:
                raise SourceError("Дата вне запрошенного окна Ozon")
            bucket = rows.setdefault(sku, [sku, "", product["name"], 0, 0, 0, 0])
            qty, amount = map(metric, row["metrics"])
            pos = 3 if day >= start else 5
            bucket[pos] += qty
            bucket[pos + 1] += amount
    return rows.values()


def display_rows(rows, query, limit):
    term = (query or "").strip().casefold()
    outcome = []
    for sku, article, name, qty, amount, previous_qty, previous_amount in rows:
        if not any((qty, amount, previous_qty, previous_amount)):
            continue
        if term and not any(term in text.casefold() for text in (sku, article, name)):
            continue
        delta = (amount / previous_amount - 1) * 100 if previous_amount else None
        outcome.append(dict(sku=sku, article=article, name=name, units=int(qty),
                            ordered_rub=float(amount), previous_units=int(previous_qty),
                            previous_rub=float(previous_amount),
                            change_pct=float(round(delta, 1)) if delta is not None else None))
    outcome.sort(key=lambda r: (-r["ordered_rub"], -r["previous_rub"], r["sku"]))
    return {"status": "ok", "total": len(outcome), "rows": outcome[:limit],
            "display_truncated": len(outcome) > limit,
            "metric_kind": "ordered_amount", "currency": "RUB",
            "warning": "Сумма заказов не является продажами, выплатой или прибылью."}


async def report(market, query, limit, end, wb=None, ozon=None):
    start = end - 6 * DAY

    async def collect(fetch, request):
        try:
            return display_rows(await fetch(request, start, end), query, limit)
        except SourceError as exc:
            return {"status": "unavailable", "message": str(exc), "rows": []}
        except (KeyError, ValueError, TypeError, InvalidOperation):
            logging.getLogger(__name__).warning("Invalid product RNP payload: %s", fetch.__name__)
            return {"status": "unavailable", "message": "Неожиданный формат API", "rows": []}

    markets = {}
    if market in ("all", "wb"):
        markets["WB"] = (wb_rows, wb or source(wb_server, "wb_analytics_funnel"))
    if market in ("all", "ozon"):
        markets["Ozon"] = (ozon_rows, ozon or source(ozon_server, "ozon_analytics_data"))
    results = await asyncio.gather(*(collect(*m) for m in markets.values()))
    return {"start": str(start), "end": str(end), "previous_start": str(start - 7 * DAY),
            "previous_end": str(start - DAY), "markets": dict(zip(markets, results))}


class ProductReport(BaseModel):
    start: str
    end: str
    previous_start: str
    previous_end: str
    markets: dict[str, dict]


async def get_product_rnp(market: Market = "all", query: str | None = None,
                          limit: int = 30, end_date: date | None = None) -> ProductReport:
    """РНП по товарам WB/Ozon. Показывает заказы в штуках и рублях по SKU,
    за 7 завершённых дней МСК и изменение к предыдущим 7 дням.
    query фильтрует SKU, артикул продавца WB или название.
    """
    today = datetime.now(MSK).date()
    end = end_date or today - DAY
    if not 1 <= limit <= 100 or end >= today:
        raise ValueError("Лимит от 1 до 100. Дата окончания должна быть раньше сегодняшней по МСК.")
    return ProductReport(**await report(market, query, limit, end))
