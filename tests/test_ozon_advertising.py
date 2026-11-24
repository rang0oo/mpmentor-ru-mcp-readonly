from datetime import date
import pytest
from readonly_mcp.ozon_advertising import parse_cpc_csv,parse_cpo_csv


def test_cpc_ignores_total_row_and_aggregates_counts_before_rates():
    csv='notice\nДень;sku;Показы;Клики;Добавления в корзину;Расход, ₽, с НДС;Продано товаров;Продажи в продвижении, ₽\n'
    csv+='16.11.2026;10;100;10;3;20,50;2;100,00\n17.11.2026;10;300;5;2;10,00;1;50,00\nВсего;;400;15;5;30,50;3;150,00\n'
    result=parse_cpc_csv(csv,'1',date(2026,11,16),date(2026,11,22))
    row=result['products'][0]
    assert row['expense_rub']=='30.50'
    assert row['ctr_percent']==3.75
    assert row['drr_attributed_percent']==20.33
    assert len(result['days'])==2


def test_cpc_rejects_duplicate_day_sku_and_wrong_date():
    header='День;sku;Показы;Клики;Добавления в корзину;Расход, ₽, с НДС;Продано товаров;Продажи в продвижении, ₽\n'
    row='16.11.2026;10;100;10;3;20,50;2;100,00\n'
    with pytest.raises(ValueError):parse_cpc_csv(header+row+row,'1',date(2026,11,16),date(2026,11,22))
    with pytest.raises(ValueError):parse_cpc_csv(header+row,'1',date(2026,11,17),date(2026,11,22))


def test_cpo_keeps_combo_and_order_expenses_separate():
    csv='SKU;Артикул;"Расход (""Комбо-модель""), ₽";"Расход (""Оплата за заказ""), ₽"\n'
    csv+='10;dr.1;10,00;20,00\n'
    result=parse_cpo_csv(csv)
    assert result['products'][0]['combo_expense_rub']=='10.00'
    assert result['products'][0]['cpo_expense_rub']=='20.00'
    assert result['scope']=='selected_products_only'


@pytest.mark.asyncio
async def test_pending_report_is_resumed_without_generating_another_job(monkeypatch):
    from readonly_mcp.ozon_advertising import get_ozon_advertising_details
    from uuid import UUID
    async def call(operation,**kwargs):
        assert operation=='ozonperf_get_api_client_statistics_uuid'
        return dict(state='IN_PROGRESS')
    monkeypatch.setattr('readonly_mcp.ozon_advertising.request',call)
    result=await get_ozon_advertising_details('cpc',date(2026,11,16),date(2026,11,22),
        campaign_id='1',report_id=UUID('a1d656dc-d5cc-4863-8f76-78a118349b5c'))
    assert result['status']=='in_progress'
    assert result['report_id']=='a1d656dc-d5cc-4863-8f76-78a118349b5c'
