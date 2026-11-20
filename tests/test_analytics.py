from readonly_mcp.analytics import explain_marketplace_metrics, check_financial_summary
import pytest


def test_revenue_is_endpoint_specific_and_unknown_fields_are_not_guessed():
    result = explain_marketplace_metrics('ozon', 'ozon_analytics_data', ['revenue', 'mystery'])
    assert result['metrics']['revenue']['meaning'] == 'Заказано на сумму'
    assert result['unknown_fields'] == ['mystery']
    assert explain_marketplace_metrics('ozon', 'unknown', ['revenue'])['unknown_fields'] == ['revenue']


def test_missing_costs_do_not_become_zero_profit_inputs():
    result = check_financial_summary('1000', '200')
    assert result['profit'] is None
    assert 'cost_of_goods' in result['missing_inputs']
    assert result['after_marketplace'] == '800'


def test_profit_uses_decimal_and_negative_refunds_are_preserved():
    result = check_financial_summary('1000.10', '200.05', '300', '50', '60', '20', '-10', complete=True)
    assert result['profit'] == '360.05'
    assert result['formula'] == 'realized_revenue - marketplace_expenses - cost_of_goods - advertising - taxes - other_expenses + adjustments'


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', 'bad'])
def test_invalid_unsigned_input_is_rejected(value):
    with pytest.raises(ValueError):
        check_financial_summary(value, '0')


def test_incomplete_data_blocks_profit_even_with_all_costs():
    result = check_financial_summary('1000', '200', '300', '0', '0', '0', '0', complete=False)
    assert result['profit'] is None
    assert result['status'] == 'incomplete'


def test_reconciliation_refuses_orders_vs_realized_sales():
    from readonly_mcp.analytics import reconcile_marketplace_totals
    context = dict(market='ozon', cabinet='one', currency='RUB', date_from='2026-10-01',
                   date_to='2026-10-31', date_basis='operation_date', metric_kind='realized_sales')
    other = {**context, 'metric_kind': 'ordered_amount'}
    result = reconcile_marketplace_totals('100', '100', context, other)
    assert result['status'] == 'not_comparable'
    assert 'metric_kind' in result['mismatched_context']


def test_reconciliation_reports_exact_decimal_difference():
    from readonly_mcp.analytics import reconcile_marketplace_totals
    context = dict(market='ozon', cabinet='one', currency='RUB', date_from='2026-10-01',
                   date_to='2026-10-31', date_basis='operation_date', metric_kind='accruals')
    result = reconcile_marketplace_totals('100.05', '100.01', context, context)
    assert result['status'] == 'mismatch'
    assert result['difference'] == '0.04'
