"""Operational sales and advertising with explicit date bases and missing data."""
import asyncio
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from readonly_mcp.analytics import _number


# Names verified against Ozon's accrual-types dictionary. This is an explicit
# promotion basket, not every expense, and not an assertion of MPSTATS parity.
OZON_PROMOTION_TYPES = {
    'BrandCommission', 'BrandPromotion', 'BrandShelf', 'ExternalPromotion',
    'InternetSiteAdvertising', 'Marketing', 'PayPerClick', 'Promotion',
    'PushCampaign', 'Stencil', 'SocialMediaAdvertising', 'DisplayAdvertisingPlacement',
}


def percent(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return float(round(Decimal(str(numerator)) / Decimal(str(denominator)) * 100, 2))


def amount(value):
    if value['currency'] != 'RUB':
        raise ValueError('Expected RUB')
    return _number(value['amount'], 'amount', signed=True)


def bucket(rows, sku):
    if sku is None or str(sku) == '':
        raise ValueError('Missing SKU')
    return rows.setdefault(str(sku), dict(buyouts=0, returns=0,
        realized_rub=Decimal(0),sales_rub=Decimal(0),returns_rub=Decimal(0),advertising_rub=Decimal(0)))


def parse_ozon_accruals(accruals, types):
    rows, unallocated = {}, Decimal(0)
    for accrual in accruals:
        for product in (accrual.get('posting') or {}).get('products', []):
            commission = product.get('commission')
            if commission is None:
                continue
            value = amount(commission['sale_amount'])
            qty = _number(str(product['quantity']), 'quantity')
            if qty != qty.to_integral_value():
                raise ValueError('Noninteger quantity')
            item = bucket(rows, product['sku'])
            item['buyouts' if value > 0 else 'returns'] += int(qty) if value else 0
            item['realized_rub'] += value
            item['sales_rub' if value>0 else 'returns_rub'] += abs(value)
        for product in (accrual.get('item_fees') or {}).get('fees', []):
            for fee in product['fees']:
                if fee['type_id'] not in types:
                    raise ValueError('Unknown Ozon accrual type')
                if types[fee['type_id']] in OZON_PROMOTION_TYPES:
                    bucket(rows, product['sku'])['advertising_rub'] -= amount(fee['accrued'])
        fee = accrual.get('non_item_fee')
        if fee:
            if fee['type_id'] not in types:
                raise ValueError('Unknown Ozon accrual type')
            if types[fee['type_id']] in OZON_PROMOTION_TYPES:
                unallocated -= amount(fee['accrued'])
    return dict(status='ok', rows=rows, unallocated_advertising_rub=unallocated)


def parse_wb_advertising(campaigns, start, end):
    rows, total, seen = {}, Decimal(0), set()
    for campaign in campaigns:
        if campaign['advertId'] in seen or campaign['currency'] != 'RUB':
            raise ValueError('Duplicate campaign or unexpected currency')
        seen.add(campaign['advertId'])
        total += _number(str(campaign['sum']), 'advertising')
        for day in campaign['days']:
            if not start <= date.fromisoformat(day['date'][:10]) <= end:
                raise ValueError('Advertising date outside requested range')
            for app in day['apps']:
                for item in app['nms']:
                    bucket(rows, item['nmId'])['advertising_rub'] += _number(str(item['sum']), 'advertising')
    allocated = sum((row['advertising_rub'] for row in rows.values()), Decimal(0))
    if allocated > total + Decimal('0.01'):
        raise ValueError('SKU advertising exceeds campaign totals')
    return dict(status='ok', rows=rows, total_advertising_rub=total,
                unallocated_advertising_rub=total - allocated)


async def wb_sales(request, start, end, pause=60):
    rows, seen, cursor = {}, set(), str(start)
    for page in range(20):
        if page:
            await asyncio.sleep(pause)
        batch = await request({'dateFrom': cursor, 'flag': 0}, None)
        if not isinstance(batch, list):
            raise ValueError('Invalid sales page')
        if not batch:
            return dict(status='ok', rows=rows, date_basis='sale_date_msk',
                        revenue_basis='priceWithDisc_before_SPP', pages=page + 1)
        next_cursor = max(item['lastChangeDate'] for item in batch)
        if next_cursor <= cursor:
            raise ValueError('WB sales cursor did not advance')
        for item in batch:
            identifier = item['saleID']
            if identifier in seen:
                continue
            seen.add(identifier)
            if not start <= date.fromisoformat(item['date'][:10]) <= end:
                continue
            if not identifier.startswith(('S', 'R')):
                raise ValueError('Unknown WB sale operation')
            row = bucket(rows, item['nmId'])
            row['article'] = item.get('supplierArticle', '')
            value = _number(str(item['priceWithDisc']), 'priceWithDisc', signed=True)
            returned = identifier.startswith('R')
            row['returns' if returned else 'buyouts'] += 1
            row['realized_rub'] += -abs(value) if returned else abs(value)
            row['returns_rub' if returned else 'sales_rub'] += abs(value)
        cursor = next_cursor
    raise ValueError('WB sales pagination budget reached')


def combine(order_rows, sales, advertising):
    sales_ok, ads_ok = sales['status'] == 'ok', advertising['status'] == 'ok'
    allocation_complete = ads_ok and not advertising.get('unallocated_advertising_rub')
    rows = {r['sku']: dict(r) for r in order_rows}
    for sku in sales.get('rows', {}).keys() | advertising.get('rows', {}).keys():
        rows.setdefault(sku, dict(sku=sku, article='', name='', units=0, ordered_rub=0,
                                  previous_units=0, previous_rub=0, change_pct=None))
    for sku, row in rows.items():
        sale, ads = sales.get('rows', {}).get(sku, {}), advertising.get('rows', {}).get(sku, {})
        row['article'] = row.get('article') or sale.get('article', '')
        row['name'] = row.get('name') or sale.get('name', '')
        for key in ('buyouts', 'returns', 'realized_rub'):
            row[key] = sale.get(key, 0) if sales_ok else None
        for key in ('sales_rub','returns_rub'):
            row[key] = sale.get(key) if sales_ok else None
            if sales_ok and sku not in sales['rows']:
                row[key]=0
        row['advertising_rub'] = ads.get('advertising_rub', 0) if allocation_complete else None
        row['net_buyouts'] = row['buyouts'] - row['returns'] if sales_ok else None
        row['drr_in_orders'] = percent(row['advertising_rub'], row['ordered_rub'])
        row['drr_in_sales'] = percent(row['advertising_rub'], row['realized_rub'])
        row['drr_in_net_sales']=row['drr_in_sales']
        row['drr_in_gross_sales']=percent(row['advertising_rub'],row['sales_rub'])
    summary = {}
    for key in ('units', 'ordered_rub', 'buyouts', 'returns', 'net_buyouts', 'realized_rub',
                'sales_rub','returns_rub','advertising_rub'):
        values = [row[key] for row in rows.values()]
        summary[key] = None if any(v is None for v in values) else sum(
            (Decimal(str(v)) for v in values), Decimal(0))
    if not sales_ok:
        for key in ('buyouts', 'returns', 'net_buyouts', 'realized_rub','sales_rub','returns_rub'):
            summary[key] = None
    summary['unallocated_advertising_rub'] = advertising.get('unallocated_advertising_rub') if ads_ok else None
    summary['advertising_rub'] = (sum((r.get('advertising_rub', Decimal(0))
        for r in advertising['rows'].values()), Decimal(0)) +
        summary['unallocated_advertising_rub']) if ads_ok else None
    summary['drr_in_orders'] = percent(summary['advertising_rub'], summary['ordered_rub'])
    summary['drr_in_sales'] = percent(summary['advertising_rub'], summary['realized_rub'])
    summary['drr_in_net_sales']=summary['drr_in_sales']
    summary['drr_in_gross_sales']=percent(summary['advertising_rub'],summary['sales_rub'])
    return dict(rows=list(rows.values()), summary=summary,
                advertising_allocation_complete=allocation_complete,
                metric_definitions={'drr_in_sales':'legacy alias of drr_in_net_sales',
                    'drr_in_net_sales':'advertising / seller revenue after refunds × 100',
                    'drr_in_gross_sales':'advertising / seller revenue before refunds × 100',
                    'drr_in_orders':'advertising / ordered amount × 100'},
                sources=dict(sales={k:v for k,v in sales.items() if k != 'rows'},
                             advertising={k:v for k,v in advertising.items() if k != 'rows'}))


async def wb_advertising(campaign_request, stats_request, start, end, pause=20):
    inventory = await campaign_request(None, None)
    groups = inventory.get('adverts') or []
    all_ids = [item['advertId'] for group in groups for item in group['advert_list']]
    if len(set(all_ids)) != inventory['all']:
        raise ValueError('Incomplete WB campaign inventory')
    # The fullstats API accepts running, paused and completed campaigns.
    ids = sorted({item['advertId'] for group in groups if group['status'] in (7, 9, 11)
                  for item in group['advert_list'] if group['status'] != 7 or
                  date.fromisoformat(item['changeTime'][:10]) >= start})
    result = []
    for offset in range(0, len(ids), 50):
        if offset:
            await asyncio.sleep(pause)
        batch_ids = ids[offset:offset + 50]
        batch = await stats_request(dict(ids=','.join(map(str, batch_ids)),
                                        beginDate=str(start), endDate=str(end)), None)
        if not isinstance(batch, list) or any(c['advertId'] not in batch_ids for c in batch):
            raise ValueError('Invalid WB campaign statistics')
        result.extend(batch)
    return {**parse_wb_advertising(result, start, end),
            'date_basis': 'advertising_statistics_date',
            'scope': 'WB fullstats campaigns in statuses 7, 9, 11; media excluded',
            'campaigns_requested': len(ids), 'campaigns_returned': len(result)}


async def ozon_accruals(request, start, end, types):
    rows, seen, requests = [], set(), 0
    day = start
    while day <= end:
        cursor, cursors = '', set()
        while True:
            if requests >= 200:
                raise ValueError('Ozon accrual request budget reached')
            page = await request(None, dict(date=str(day), last_id=cursor))
            requests += 1
            batch, next_cursor = page['accruals'], page['last_id']
            if not isinstance(batch, list) or not isinstance(next_cursor, str):
                raise ValueError('Invalid Ozon accrual page')
            for item in batch:
                if item['accrual_id'] in seen or date.fromisoformat(item['date'][:10]) != day:
                    raise ValueError('Duplicate or out-of-period Ozon accrual')
                if item.get('container_fees'):
                    raise ValueError('Unmapped container fees; promotion total withheld')
                seen.add(item['accrual_id'])
            rows.extend(batch)
            if not next_cursor:
                break
            if next_cursor in cursors:
                raise ValueError('Ozon accrual cursor repeated')
            cursors.add(next_cursor)
            cursor = next_cursor
        day += timedelta(days=1)
    return {**parse_ozon_accruals(rows, types), 'pages': requests,
            'date_basis': 'Ozon accrual date, not order or final realization date',
            'revenue_basis': 'commission.sale_amount signed; seller amount',
            'preliminary': True, 'promotion_types': sorted(OZON_PROMOTION_TYPES),
            'warning': 'Оперативные продажи по начислениям. Не закрывающий отчёт реализации и не прогноз. '
                       'Расходы — выбранные виды продвижения по дате начисления, не Performance.'}


async def safe_fetch(fetch):
    try:
        return await fetch()
    except (ValueError, KeyError, TypeError, InvalidOperation):
        # Never echo upstream payloads or arbitrary exceptions into the tool.
        return dict(status='unavailable', rows={},
                    message='Источник недоступен или контракт данных не прошёл проверку; суммы не рассчитаны.')


async def fetch_economics(market, start, end, skus=()):
    # Import lazily so the order module can use this enrichment without a cycle.
    from readonly_mcp.rnp import source
    from wb_mcp import server as wb
    from ozon_mcp import server as ozon

    if market == 'WB':
        sales, ads = await asyncio.gather(
            safe_fetch(lambda: wb_sales(source(wb, 'wb_stats_sales'), start, end)),
            safe_fetch(lambda: wb_advertising(source(wb, 'wb_adv_count'),
                        source(wb, 'wb_get_adv_fullstats'), start, end)))
        return sales, ads

    async def fetch():
        catalog = await source(ozon, 'ozon_finance_accrual_types')(None, {})
        types = {row['id']: row['name'] for row in catalog['accrual_types']}
        return await ozon_accruals(source(ozon, 'ozon_finance_accrual_by_day'), start, end, types)
    result = await safe_fetch(fetch)
    if result['status'] == 'ok':
        identifiers = sorted(set(skus) | result['rows'].keys())
        try:
            for offset in range(0, len(identifiers), 1000):
                products = await source(ozon, 'ozon_product_info_list')(
                    None, {'sku': identifiers[offset:offset + 1000]})
                for product in products['items']:
                    for sku in {str(product['sku'])} | {str(s['sku']) for s in product.get('sources', [])}:
                        if sku in identifiers:
                            row = bucket(result['rows'], sku)
                            row['article'], row['name'] = product['offer_id'], product['name']
            result['product_metadata_status'] = 'ok'
        except (ValueError, KeyError, TypeError):
            result['product_metadata_status'] = 'unavailable'
    return result, result
