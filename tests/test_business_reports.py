from datetime import date
import json
from pathlib import Path

import pytest

from readonly_mcp.business_reports import business_report


@pytest.mark.asyncio
async def test_refresh_saves_and_export_uses_saved_data_without_api(monkeypatch,tmp_path):
    monkeypatch.setenv('MARKETPLACE_MCP_HOME',str(tmp_path))
    monkeypatch.setattr('readonly_mcp.business_reports.active_cabinet',lambda m:'shop')
    async def fetch(**kwargs):
        return dict(markets={'WB':dict(status='ok',cabinet='shop',display_truncated=False,
            rows=[dict(sku='1',article='dr.1',units=10)],summary={'units':10},
            economics_status='partial',retrieved_at='2026-11-24T12:00:00+00:00')})
    monkeypatch.setattr('readonly_mcp.business_reports.get_product_rnp',fetch)
    args=dict(market='wb',date_from=date(2026,11,16),date_to=date(2026,11,22))
    saved=await business_report(action='refresh',**args)
    assert saved['status']=='saved'
    async def forbidden(**kwargs):
        raise AssertionError('Saved/export must never fetch from marketplaces')
    monkeypatch.setattr('readonly_mcp.business_reports.get_product_rnp',forbidden)
    cached=await business_report(action='saved',**args)
    assert cached['report']['rows'][0]['units']==10
    exported=await business_report(action='export',**args)
    path=Path(exported['path'])
    assert path.parent==tmp_path/'exports'
    assert json.loads(path.read_text())['report']['summary']['units']==10
    assert path.stat().st_mode&0o777==0o600
    assert exported['economics_status']=='partial'


@pytest.mark.asyncio
async def test_missing_saved_report_does_not_fetch_automatically(monkeypatch,tmp_path):
    monkeypatch.setenv('MARKETPLACE_MCP_HOME',str(tmp_path))
    monkeypatch.setattr('readonly_mcp.business_reports.active_cabinet',lambda m:'shop')
    async def forbidden(**kwargs):raise AssertionError('Unexpected API call')
    monkeypatch.setattr('readonly_mcp.business_reports.get_product_rnp',forbidden)
    result=await business_report('saved','wb',date(2026,11,16),date(2026,11,22))
    assert result['status']=='not_saved'


@pytest.mark.asyncio
async def test_truncated_refresh_cannot_replace_saved_full_report(monkeypatch,tmp_path):
    monkeypatch.setenv('MARKETPLACE_MCP_HOME',str(tmp_path))
    monkeypatch.setattr('readonly_mcp.business_reports.active_cabinet',lambda m:'shop')
    async def fetch(**kwargs):
        return dict(markets={'WB':dict(status='ok',cabinet='shop',display_truncated=True,
            rows=[],economics_status='ok')})
    monkeypatch.setattr('readonly_mcp.business_reports.get_product_rnp',fetch)
    result=await business_report('refresh','wb',date(2026,11,16),date(2026,11,22))
    assert result['status']=='incomplete'
    assert (await business_report('saved','wb',date(2026,11,16),date(2026,11,22)))['status']=='not_saved'
