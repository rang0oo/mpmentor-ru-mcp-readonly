from datetime import date
from decimal import Decimal

import pytest

from readonly_mcp import rnp_economics as econ


def test_drr_uses_totals_and_preserves_unknown_and_nonpositive_base():
    assert econ.percent(Decimal('10'), Decimal('200')) == 5
    assert econ.percent(None, Decimal('200')) is None
    assert econ.percent(Decimal('10'), Decimal('0')) is None
    assert econ.percent(Decimal('10'), Decimal('-1')) is None


@pytest.mark.asyncio
async def test_wb_sales_filter_operation_date_and_deduplicate_cursor_overlap():
    sale = dict(saleID='S1', nmId=10, supplierArticle='cat', date='2026-11-16',
                lastChangeDate='2026-11-17T10:00:00', priceWithDisc=100)
    ret = dict(saleID='R2', nmId=10, supplierArticle='cat', date='2026-11-22',
               lastChangeDate='2026-11-24T10:00:00', priceWithDisc=80)
    pages = [[sale], [sale, ret], []]
    async def request(query, body):
        return pages.pop(0)
    result = await econ.wb_sales(request, date(2026, 11, 16), date(2026, 11, 22), pause=0)
    assert result['rows']['10']['buyouts'] == 1
    assert result['rows']['10']['returns'] == 1
    assert result['rows']['10']['realized_rub'] == Decimal('20')
    assert result['rows']['10']['sales_rub'] == Decimal('100')
    assert result['rows']['10']['returns_rub'] == Decimal('80')


def test_ozon_counts_only_commission_sales_not_logistics_and_preserves_adjustment():
    money = lambda amount: dict(amount=str(amount), currency='RUB')
    rows = [dict(accrual_id=1, date='2026-11-22', posting=dict(products=[
        dict(sku=10, quantity=2, commission=dict(sale_amount=money(200)))])),
        dict(accrual_id=2, date='2026-11-22', posting=dict(products=[
        dict(sku=10, quantity=1, commission=dict(sale_amount=money(-100)))])),
        dict(accrual_id=3, date='2026-11-22', posting=dict(products=[
        dict(sku=10, quantity=1, commission=None)]),
        item_fees=dict(fees=[dict(sku=10, fees=[dict(type_id=41, accrued=money(-20))])])),
        dict(accrual_id=4, date='2026-11-22', non_item_fee=dict(
            type_id=41, accrued=money(5)))]
    result = econ.parse_ozon_accruals(rows, {41: 'PayPerClick'})
    assert result['rows']['10']['buyouts'] == 2
    assert result['rows']['10']['returns'] == 1
    assert result['rows']['10']['realized_rub'] == Decimal('100')
    assert result['rows']['10']['sales_rub'] == Decimal('200')
    assert result['rows']['10']['returns_rub'] == Decimal('100')
    assert result['rows']['10']['advertising_rub'] == Decimal('20')
    assert result['unallocated_advertising_rub'] == Decimal('-5')


def test_wb_advertising_never_adds_parent_totals_to_sku_totals():
    campaigns = [dict(advertId=1, currency='RUB', sum=10, days=[
        dict(date='2026-11-16', apps=[dict(nms=[dict(nmId=10, sum=10)])])])]
    result = econ.parse_wb_advertising(campaigns, date(2026, 11, 16), date(2026, 11, 22))
    assert result['rows']['10']['advertising_rub'] == Decimal('10')
    assert result['total_advertising_rub'] == Decimal('10')


def test_incomplete_advertising_never_becomes_zero_drr():
    result = econ.combine([dict(sku='10', units=2, ordered_rub=100)],
                          dict(status='ok', rows={'10': dict(buyouts=1, returns=0,
                               realized_rub=Decimal('50'))}),
                          dict(status='unavailable', rows={}))
    assert result['rows'][0]['advertising_rub'] is None
    assert result['summary']['drr_in_orders'] is None


@pytest.mark.asyncio
async def test_ozon_repeated_cursor_withholds_all_economic_totals():
    async def request(query, body):
        return dict(accruals=[], last_id='same')
    with pytest.raises(ValueError, match='cursor'):
        await econ.ozon_accruals(request, date(2026, 11, 22), date(2026, 11, 22), {})


def test_summary_includes_unallocated_adjustments_and_uses_ratio_of_sums():
    result = econ.combine([dict(sku='10', units=2, ordered_rub=100),
                           dict(sku='20', units=1, ordered_rub=300)],
                          dict(status='ok', rows={}),
                          dict(status='ok', rows={'10':dict(advertising_rub=Decimal(20)),
                              '20':dict(advertising_rub=Decimal(10))},
                               unallocated_advertising_rub=Decimal(-10)))
    assert result['summary']['advertising_rub'] == 20
    assert result['summary']['drr_in_orders'] == 5


@pytest.mark.asyncio
async def test_failed_wb_campaign_batch_never_returns_partial_spend_as_complete():
    async def campaigns(query, body):
        return dict(adverts=[dict(status=11, advert_list=[dict(advertId=1)])], all=1)
    async def stats(query, body):
        raise ValueError('API 403')
    with pytest.raises(ValueError):
        await econ.wb_advertising(campaigns, stats, date(2026, 11, 16), date(2026, 11, 22))


@pytest.mark.asyncio
async def test_wb_completed_campaigns_before_period_are_excluded():
    async def campaigns(query, body):
        return dict(adverts=[dict(status=7, advert_list=[
            dict(advertId=1, changeTime='2025-01-01T10:00:00+03:00'),
            dict(advertId=2, changeTime='2026-11-16T10:00:00+03:00')])], all=2)
    async def stats(query, body):
        assert query['ids'] == '2'
        return []
    result = await econ.wb_advertising(campaigns, stats, date(2026, 11, 16), date(2026, 11, 22))
    assert result['total_advertising_rub'] == 0


def test_unallocated_spend_withholds_sku_drr_but_retains_cabinet_drr():
    result = econ.combine([dict(sku='10', units=1, ordered_rub=100)],
        dict(status='ok', rows={}),
        dict(status='ok', rows={}, unallocated_advertising_rub=Decimal(20)))
    assert result['rows'][0]['advertising_rub'] is None
    assert result['rows'][0]['drr_in_orders'] is None
    assert result['summary']['drr_in_orders'] == 20


def test_gross_and_net_drr_have_separate_bases():
    result=econ.combine([dict(sku='10',units=4,ordered_rub=500)],
        dict(status='ok',rows={'10':dict(buyouts=4,returns=1,
            realized_rub=Decimal(300),sales_rub=Decimal(400),returns_rub=Decimal(100))}),
        dict(status='ok',rows={'10':dict(advertising_rub=Decimal(20))},
             unallocated_advertising_rub=Decimal(0)))
    assert result['summary']['drr_in_gross_sales']==5
    assert result['summary']['drr_in_net_sales']==6.67
    assert result['summary']['drr_in_sales']==6.67
