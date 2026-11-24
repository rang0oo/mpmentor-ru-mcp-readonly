import asyncio
from readonly_mcp.business_settings import save_business_settings, get_business_settings, CostInput, TaxInput


def test_chat_inputs_are_remembered_and_only_missing_values_are_requested(monkeypatch,tmp_path):
    monkeypatch.setenv('MARKETPLACE_MCP_HOME',str(tmp_path))
    monkeypatch.setattr('readonly_mcp.business_settings.active_cabinet',lambda market:'shop')
    before=get_business_settings('wb',articles=['dr.1'],on_date='2026-11-20')
    assert before['missing_cost_articles']==['dr.1']
    assert 'regime' in before['missing_tax_fields']
    save_business_settings('wb',costs=[CostInput(article='dr.1',amount='42,50',effective_from='2026-11-01')],
        tax=TaxInput(regime='income',rate_percent='6',vat_percent='0',effective_from='2026-11-01'))
    after=get_business_settings('wb',articles=['dr.1','ball.2'],on_date='2026-11-20')
    assert after['missing_cost_articles']==['ball.2']
    assert after['missing_tax_fields']==[]
    assert after['settings']['costs']['dr.1']['amount']=='42.50'


def test_gateway_keeps_remote_readonly_tools_and_marks_local_settings_as_local_write():
    from readonly_mcp.server import build,READ_ONLY_TOOLS,LOCAL_BUSINESS_TOOLS
    gateway=build()
    assert set(gateway._tool_manager._tools)==READ_ONLY_TOOLS|LOCAL_BUSINESS_TOOLS
    tool=gateway._tool_manager._tools['save_business_settings']
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.openWorldHint is False
