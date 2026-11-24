from decimal import Decimal
import pytest
from readonly_mcp.business_analysis import abc_analysis, supply_plan, funnel_metrics, profit_calculation


def test_abc_keeps_losses_separate_and_assigns_first_large_item_to_a():
    rows=abc_analysis([{'sku':'a','value':'900'},{'sku':'b','value':'100'},
                       {'sku':'loss','value':'-30'},{'sku':'zero','value':'0'}])
    result={r['sku']:r for r in rows}
    assert result['a']['abc']=='A'
    assert result['loss']['abc']=='loss'
    assert result['zero']['abc']=='no_activity'
    assert result['a']['share_percent']==90


def test_supply_uses_daily_demand_and_explicit_lead_review_and_safety():
    result=supply_plan(demand_units=280,observed_days=28,available=20,
                       incoming_before_target=10,lead_days=5,review_days=7,safety_days=2)
    assert result['daily_demand']==10
    assert result['days_of_cover']==2
    assert result['recommended_units']==110
    assert result['stockout_before_arrival'] is True
    assert result['kind']=='forecast'


def test_supply_missing_lead_time_never_invents_recommendation():
    result=supply_plan(demand_units=20,observed_days=7,available=2,
                       incoming_before_target=0,lead_days=None,review_days=7,safety_days=2)
    assert result['recommended_units'] is None
    assert result['missing_inputs']==['lead_days']


def test_funnel_preserves_rates_above_100_and_flags_misaligned_cohorts():
    result=funnel_metrics(views=100,opens=20,carts=5,orders=8)
    assert result['cart_to_order_percent']==160
    assert result['warnings']
    assert funnel_metrics(views=None,opens=0,carts=0,orders=0)['ctr_percent'] is None


def test_profit_withholds_unknown_costs_and_prevents_advertising_double_count():
    args=dict(realized_revenue='1000',marketplace_expenses_excluding_ads='300',
              advertising='100',taxes='60',other_expenses='0',adjustments='0',
              expenses_complete=True)
    assert profit_calculation(cost_of_goods=None,**args)['profit'] is None
    assert profit_calculation(cost_of_goods='200',**args)['profit']=='340'
    assert profit_calculation(cost_of_goods='200',**{**args,'expenses_complete':False})['profit'] is None


def test_supply_rejects_negative_stock_and_fractional_days():
    with pytest.raises(ValueError):
        supply_plan(demand_units=10,observed_days=7,available=-1,incoming_before_target=0,
                    lead_days=1,review_days=7,safety_days=0)
