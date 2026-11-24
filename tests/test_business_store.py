from pathlib import Path

import pytest

from readonly_mcp.business_store import BusinessStore


def test_cost_and_tax_survive_reopening_and_are_scoped_by_cabinet(tmp_path):
    path = tmp_path / 'business.sqlite3'
    store = BusinessStore(path)
    store.save_settings('wb', 'shop', costs=[dict(article='dr.1', amount='42.50',
        effective_from='2026-11-01')], tax=dict(regime='income', rate_percent='6',
        vat_percent='0', effective_from='2026-01-01'))
    reopened = BusinessStore(path)
    assert reopened.settings('wb','shop','2026-11-20')['costs']['dr.1']['amount']=='42.50'
    assert reopened.settings('ozon','shop','2026-11-20')['costs']=={}
    assert reopened.settings('wb','other','2026-11-20')['tax'] is None
    assert reopened.settings('wb','shop','2026-11-20')['tax']['regime']=='income'


def test_effective_dates_preserve_historical_cost_and_latest_revision(tmp_path):
    store = BusinessStore(tmp_path/'b.sqlite3')
    for day, amount in [('2026-11-01','42'),('2026-12-01','50'),('2026-11-01','43')]:
        store.save_settings('wb','shop',costs=[dict(article='dr.1',amount=amount,effective_from=day)])
    assert store.settings('wb','shop','2026-11-20')['costs']['dr.1']['amount']=='43'
    assert store.settings('wb','shop','2026-12-20')['costs']['dr.1']['amount']=='50'
    assert store.settings('wb','shop','2026-10-20')['costs']=={}
    assert store.settings_history('wb','shop')['revision_count']==3


def test_invalid_settings_rollback_entire_batch(tmp_path):
    store = BusinessStore(tmp_path/'b.sqlite3')
    with pytest.raises(ValueError):
        store.save_settings('wb','shop',costs=[
            dict(article='valid',amount='42',effective_from='2026-11-01'),
            dict(article='bad',amount='NaN',effective_from='2026-11-01')])
    assert store.settings('wb','shop','2026-11-20')['costs']=={}


def test_partial_tax_does_not_invent_vat_or_rate(tmp_path):
    store=BusinessStore(tmp_path/'b.sqlite3')
    store.save_settings('wb','shop',tax=dict(regime='income',effective_from='2026-11-01'))
    tax=store.settings('wb','shop','2026-11-20')['tax']
    assert tax['rate_percent'] is None and tax['vat_percent'] is None


def test_snapshot_retries_are_idempotent_and_failed_refresh_preserves_last_complete(tmp_path):
    store=BusinessStore(tmp_path/'b.sqlite3')
    context=dict(market='wb',cabinet='shop',dataset='rnp',date_from='2026-11-16',
                 date_to='2026-11-22',date_basis='order_date',currency='RUB')
    first=store.save_snapshot(context,{'units':10},complete=True)
    second=store.save_snapshot(context,{'units':10},complete=True)
    assert first==second
    store.save_snapshot(context,{'units':2},complete=False)
    assert store.latest_snapshot(context)['payload']=={'units':10}
    store.save_snapshot(context,{'units':11},complete=True)
    assert store.latest_snapshot(context)['payload']=={'units':11}


def test_unknown_tax_regime_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        BusinessStore(tmp_path/'b.sqlite3').save_settings('wb','shop',tax=dict(
            regime='magic',effective_from='2026-11-01'))


def test_reobserved_old_payload_becomes_latest_complete_again(tmp_path):
    store=BusinessStore(tmp_path/'b.sqlite3')
    context=dict(market='wb',cabinet='shop',dataset='daily',date_from='2026-11-22',
                 date_to='2026-11-22',date_basis='source_date',currency='RUB')
    store.save_snapshot(context,{'units':10},complete=True)
    store.save_snapshot(context,{'units':11},complete=True)
    store.save_snapshot(context,{'units':10},complete=True)
    assert store.latest_snapshot(context)['payload']['units']==10
