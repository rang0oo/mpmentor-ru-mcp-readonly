import asyncio
from readonly_mcp.finance import get_ozon_finance_audit
from ozon_mcp import server


def accrual(identifier, amount='80.10', currency='RUB', **fields):
    return {'accrual_id': identifier, 'date': '2026-10-01',
            'total_amount': {'amount': amount, 'currency': currency},
            'accrued_category': 'POSTING', 'posting': None, **fields}


def run(monkeypatch, pages):
    sequence = iter(pages)
    async def call(spec, **kwargs):
        assert spec.operation_id == 'ozon_finance_accrual_by_day'
        assert kwargs['json_body']['date'] == '2026-10-01'
        return {'ok': True, 'data': next(sequence)}
    monkeypatch.setattr(server.client, 'call_spec', call)
    return asyncio.run(get_ozon_finance_audit('2026-10-01', '2026-10-01'))


def test_finance_audit_preserves_signed_totals_without_adding_components(monkeypatch):
    result = run(monkeypatch, [{'accruals': [
        accrual(1, posting={'products': [{'sku': 1, 'delivery': {'total_accrued': {'amount': '-20'}}}]}),
        accrual(2, '-10.05', accrued_category='NON_ITEM'),
    ], 'last_id': ''}])
    assert result['signed_operations_total'] == '70.05'
    assert result['operations_without_sku'] == 1
    assert result['currency'] == 'RUB'
    assert result['profit'] is None


def test_duplicate_accruals_block_financial_conclusion(monkeypatch):
    result = run(monkeypatch, [{'accruals': [accrual(1), accrual(1)], 'last_id': ''}])
    assert result['status'] == 'incomplete'
    assert result['signed_operations_total'] is None


def test_mixed_currencies_are_not_summed(monkeypatch):
    result = run(monkeypatch, [{'accruals': [accrual(1), accrual(2, currency='CNY')], 'last_id': ''}])
    assert result['signed_operations_total'] is None


def test_last_id_pages_and_item_fee_skus(monkeypatch):
    result = run(monkeypatch, [
        {'accruals': [accrual(1)], 'last_id': 'cursor'},
        {'accruals': [accrual(2, '10', item_fees={'fees': [{'sku': 123}]})], 'last_id': ''},
    ])
    assert result['operation_count'] == 2
    assert result['pages_fetched'] == 2
    assert result['signed_operations_total'] == '90.10'
    assert result['operations_without_sku'] == 1


def test_repeated_cursor_is_not_complete(monkeypatch):
    result = run(monkeypatch, [
        {'accruals': [accrual(1)], 'last_id': 'stuck'},
        {'accruals': [accrual(2)], 'last_id': 'stuck'},
    ])
    assert result['signed_operations_total'] is None
