"""Compact order pulse by marketplace SKU."""
import asyncio
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, Field

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
    duration=end-start+DAY
    body = {"selectedPeriod": {"start": str(start), "end": str(end)},
            "pastPeriod": {"start": str(start - duration), "end": str(start - DAY)},
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
    duration=end-start+DAY
    body = {"date_from": str(start - duration), "date_to": str(end),
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
            if not start - duration <= day <= end:
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


async def report(market, query, limit, end, wb=None, ozon=None, include_economics=False,
                 start_date=None):
    start = start_date or end - 6 * DAY
    if start>end or (end-start).days>=31:
        raise ValueError('Период от 1 до 31 дня')
    duration=end-start+DAY

    async def collect(name, fetch, request):
        try:
            raw = await fetch(request, start, end)
            if not include_economics:
                return display_rows(raw, query, limit)
            from readonly_mcp.rnp_economics import combine, fetch_economics
            orders = display_rows(raw, None, 200_000)
            sales, ads = await fetch_economics(name, start, end,
                                             skus=[row['sku'] for row in orders['rows']])
            enriched = combine(orders['rows'], sales, ads)
            term = (query or '').strip().casefold()
            filtered = [row for row in enriched['rows'] if not term or any(
                term in str(row.get(key, '')).casefold() for key in ('sku', 'article', 'name'))]
            filtered.sort(key=lambda row: (-row['ordered_rub'], row['sku']))
            server = wb_server if name == 'WB' else ozon_server
            cabinet = server.client.config.store.list_cabinets(server.client.config.name).get('active')
            return {**orders, **enriched, 'rows': filtered[:limit], 'total': len(filtered),
                    'cabinet': cabinet or 'environment credentials',
                    'retrieved_at': datetime.now(timezone.utc).isoformat(),
                    'display_truncated': len(filtered) > limit,
                    'summary_scope': 'all products in active cabinet, before query and display limit',
                    'economics_status': 'ok' if sales['status'] == ads['status'] == 'ok' else 'partial'}
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
    results = await asyncio.gather(*(collect(name, *m) for name, m in markets.items()))
    return {"start": str(start), "end": str(end), "previous_start": str(start - duration),
            "previous_end": str(start - DAY), "markets": dict(zip(markets, results))}


class ProductReport(BaseModel):
    start: str
    end: str
    previous_start: str
    previous_end: str
    markets: dict[str, dict]


async def get_product_rnp(market: Market = "all", query: str | None = None,
                          limit: Annotated[int, Field(ge=1, le=1000)] = 100,
                          end_date: date | None = None,
                          include_economics: bool = True,
                          start_date: date | None = None) -> ProductReport:
    """РНП WB/Ozon за 7 завершённых дней МСК и сравнение с предыдущими 7.

    Заказы, выкупы, возвраты, реклама и ДРР заказов/продаж по SKU и кабинету.
    WB: продажи Statistics по дате продажи, реклама fullstats (без медийной).
    Ozon: предварительные продажи и выбранные виды продвижения по дате начисления;
    не окончательная реализация, не Performance и не прогноз MPSTATS.
    sources содержит базы дат и предупреждения. Неизвестное — null, не ноль.
    summary — весь кабинет до query/limit; limit 1..1000 ограничивает показ.
    start_date задаёт начало периода (1..31 закрытый день); без него — 7 дней.
    include_economics=False — только заказы. Прибыль не рассчитывается.
    """
    today = datetime.now(MSK).date()
    end = end_date or today - DAY
    if not 1 <= limit <= 1000 or end >= today:
        raise ValueError("Лимит от 1 до 1000. Дата окончания должна быть раньше сегодняшней по МСК.")
    payload=await report(market, query, limit, end,
                         include_economics=include_economics,start_date=start_date)
    from readonly_mcp.business_settings import get_business_settings
    for name,data in payload['markets'].items():
        if data.get('status')!='ok':
            continue
        data['order_source']={'operation_id':'wb_analytics_funnel' if name=='WB' else 'ozon_analytics_data',
                              'date_basis':'order_date','currency':'RUB'}
        articles=sorted({row['article'] for row in data['rows'] if row.get('article')})
        try:
            data['business_inputs']=get_business_settings('wb' if name=='WB' else 'ozon',
                                                         articles=articles,on_date=str(end))
            data['business_inputs']['missing_article_skus']=[row['sku'] for row in data['rows']
                                                             if not row.get('article')]
        except (ValueError,OSError,sqlite3.Error):
            data['business_inputs']={'status':'unavailable','profit':None}
    return ProductReport(**payload)
