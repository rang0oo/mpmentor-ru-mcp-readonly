"""Read current Ozon accruals without inventing SKU allocation or net profit."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from ozon_mcp import server
from readonly_mcp.analytics import _number


async def get_ozon_finance_audit(date_from: str, date_to: str) -> dict:
    """Read Ozon accruals via /v1/finance/accrual/by-day, sequentially by day.

    Active Ozon cabinet: check ozon_list_cabinets first. Dates inclusive YYYY-MM-DD
    within one calendar month; source accrual dates, not order dates. Read all
    last_id pages (maximum 200 requests per invocation). Sum ONLY
    total_amount.amount, preserving signs and checking one currency. Fees and
    commission components are already included and MUST NOT be added again.
    Returns categories and counts without SKU allocation. Empty upstream last_id
    is the observed cursor exhaustion signal, not proof of final accounting data.
    Retired /v3/finance/transaction methods are never called. Profit requires
    additional cost, tax and other expense inputs and is always null here.
    """
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if start > end or (start.year, start.month) != (end.year, end.month):
        raise ValueError('Use an ordered date range within one calendar month')
    if end >= datetime.now(timezone(timedelta(hours=3))).date():
        raise ValueError('Use completed days only')
    spec = server.catalog.get('ozon_finance_accrual_by_day')
    if spec is None or spec.safety != 'read':
        raise RuntimeError('Financial audit requires the current read-only accrual endpoint')
    result = {
        'status': 'incomplete', 'date_from': str(start), 'date_to': str(end),
        'date_basis': 'Ozon accrual date; source calendar, not order date',
        'currency': None, 'source': spec.path,
        'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'signed_operations_total': None, 'profit': None, 'warnings': [],
        'pages_fetched': 0,
    }
    seen, groups, currencies = set(), {}, set()
    amount_sum = Decimal(0)
    without_sku = multiple_sku = 0
    day = start
    while day <= end:
        cursor, cursors = '', set()
        while True:
            if result['pages_fetched'] >= 200:
                result['warnings'].append('Request limit reached; total withheld')
                return result
            response = await server.client.call_spec(spec, json_body={'date': str(day), 'last_id': cursor})
            result['pages_fetched'] += 1
            if not response.get('ok'):
                result['error_type'] = response.get('error_type')
                result['warnings'].append('Accrual request failed; total withheld')
                return result
            try:
                payload = response['data']
                accruals, next_cursor = payload['accruals'], payload['last_id']
                if not isinstance(accruals, list) or not isinstance(next_cursor, str):
                    raise ValueError('Invalid accrual page')
                for accrual in accruals:
                    identifier = accrual['accrual_id']
                    if type(identifier) not in (int, str) or identifier == '' or identifier in seen:
                        raise ValueError('Missing or duplicate accrual ID')
                    seen.add(identifier)
                    if date.fromisoformat(accrual['date'][:10]) != day:
                        raise ValueError('Accrual date outside requested day')
                    money = accrual['total_amount']
                    currency = money['currency']
                    if not isinstance(currency, str) or not currency:
                        raise ValueError('Missing currency')
                    currencies.add(currency)
                    if len(currencies) != 1:
                        raise ValueError('Mixed currencies')
                    amount = _number(money['amount'], 'total_amount.amount', signed=True)
                    amount_sum += amount
                    category = accrual.get('accrued_category', 'unknown')
                    groups[category] = groups.get(category, Decimal(0)) + amount
                    posting = accrual.get('posting') or {}
                    fees = accrual.get('item_fees') or {}
                    skus = {item['sku'] for item in posting.get('products', []) + fees.get('fees', [])
                            if item.get('sku') is not None}
                    without_sku += not skus
                    multiple_sku += len(skus) > 1
                if not next_cursor:
                    break
                if next_cursor in cursors:
                    raise ValueError('Repeated cursor')
                cursors.add(next_cursor)
                cursor = next_cursor
            except (KeyError, ValueError, TypeError, AttributeError):
                result['warnings'].append('Invalid accrual data, currency, date, duplicate ID or repeated cursor; total withheld')
                return result
        day += timedelta(days=1)
    result.update(
        status='ledger_complete', pagination_status='upstream_cursor_exhausted',
        currency=next(iter(currencies), None), signed_operations_total=str(amount_sum),
        operation_count=len(seen),
        operations_by_category={key: str(value) for key, value in groups.items()},
        operations_without_sku=without_sku, operations_with_multiple_skus=multiple_sku,
    )
    result['warnings'].extend([
        'Signed accrual balance is not a payout or profit. Costs, taxes and external expenses are not verified.',
        'No independent total was reconciled. Empty last_id is the upstream exhaustion signal, not proof of a consistent final snapshot.',
        'Closed days may receive financial corrections. Shared costs have not been allocated to SKU.',
    ])
    return result
