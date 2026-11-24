from datetime import date
import pytest
from readonly_mcp.business_collector import collect_days
from readonly_mcp.business_store import BusinessStore


@pytest.mark.asyncio
async def test_daily_collection_keeps_incomplete_economics_separate_from_complete_orders(tmp_path):
    store=BusinessStore(tmp_path/'b.sqlite3')
    async def fetch(**kwargs):
        return dict(start=kwargs['start_date'].isoformat(),end=kwargs['end_date'].isoformat(),
                    markets={'WB':dict(status='ok',cabinet='shop',display_truncated=False,
                    rows=[dict(sku='1',units=10)],summary={'units':10},
                    economics_status='partial',sources={})})
    result=await collect_days(store,'wb',date(2026,11,22),date(2026,11,22),fetch=fetch)
    assert result['saved_days']==1 and result['partial_economics_days']==1
    context=dict(market='wb',cabinet='shop',dataset='daily_orders',date_from='2026-11-22',
        date_to='2026-11-22',date_basis='order_date',currency='RUB')
    assert store.latest_snapshot(context)['payload']['rows'][0]['units']==10
    context.update(dataset='daily_economics',date_basis='see_sources')
    assert store.latest_snapshot(context) is None


@pytest.mark.asyncio
async def test_failed_day_does_not_stop_next_day(tmp_path):
    async def fetch(**kwargs):
        if kwargs['start_date'].day==21:
            raise ValueError('unavailable')
        return dict(markets={'WB':dict(status='ok',cabinet='shop',display_truncated=False,
            rows=[],summary={},economics_status='ok',sources={})})
    result=await collect_days(BusinessStore(tmp_path/'b.sqlite3'),'wb',
                              date(2026,11,21),date(2026,11,22),fetch=fetch)
    assert result['failed_days']==1 and result['saved_days']==1
