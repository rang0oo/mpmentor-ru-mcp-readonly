from readonly_mcp.methodology import allocate_expense, calculate_pnl, forecast_sales, match_product
import pytest


def test_allocation_conserves_kopecks_with_deterministic_ties_and_credits():
    result=allocate_expense('0.05',{'b':'1','a':'1','c':'1'},'by_units')
    assert result['allocated']=={'a':'0.02','b':'0.02','c':'0.01'}
    assert result['unallocated']=='0.00'
    credit=allocate_expense('-0.05',{'a':'1','b':'1','c':'1'},'by_units')
    assert credit['allocated']=={'a':'-0.02','b':'-0.02','c':'-0.01'}
    assert credit['conservation_verified'] is True


def test_unknown_or_zero_basis_stays_unallocated():
    for basis in ({'a':None,'b':'10'},{'a':'0'},{}) :
        result=allocate_expense('100',basis,'by_revenue')
        assert result['allocated']=={}
        assert result['unallocated']=='100'
    assert allocate_expense('100',{'a':'10'},'at_business')['allocated']=={}


def test_subkopeck_source_precision_is_preserved_in_unallocated():
    result=allocate_expense('1.005',{'a':'1'},'by_units')
    assert result['allocated']=={'a':'1.00'}
    assert result['unallocated']=='0.005'
    assert result['conservation_verified']


def test_pnl_reversals_are_signed_and_return_cost_recovered_once():
    fees={k:'0' for k in ['commission','logistics','acquiring','storage','acceptance',
                          'advertising','penalties','other_marketplace','other_business']}
    fees.update(commission='100',logistics='80',advertising='-20')
    result=calculate_pnl('900',fees,'200','40','54','0',True)
    assert result['profit']=='526'
    assert result['kind']=='realized'
    assert result['ros_percent']==58.44
    assert calculate_pnl('900',{**fees,'storage':None},'200','40','54','0',True)['profit'] is None
    assert calculate_pnl('900',fees,'200','40','54','0',False)['profit'] is None


def test_forecast_is_sum_of_daily_models_not_average_percent():
    result=forecast_sales([{'ordered_units':'10','ordered_rub':'1000','buyout_percent':'50'},
                           {'ordered_units':'100','ordered_rub':'10000','buyout_percent':'90'}])
    assert result['predicted_units']=='95'
    assert result['predicted_revenue']=='9500'
    assert result['kind']=='forecast'
    assert forecast_sales([{'ordered_units':'10','ordered_rub':'1000','buyout_percent':None}])['predicted_revenue'] is None
    assert forecast_sales([])['predicted_revenue'] is None


def test_wb_forecast_rounds_quantity_and_cash_per_day_before_aggregation():
    days=[{'ordered_units':'3','ordered_rub':'100','buyout_percent':'80'},
          {'ordered_units':'3','ordered_rub':'100','buyout_percent':'80'}]
    result=forecast_sales(days,model='wb_daily_round')
    assert result['predicted_units']=='4'
    assert result['predicted_revenue']=='133.34'
    assert result['model']=='wb_daily_round'


def test_product_matching_never_falls_back_to_name_or_other_marketplace():
    catalog=[dict(market='wb',cabinet='shop',sku='10',article='same'),
             dict(market='ozon',cabinet='shop',sku='10',article='same')]
    assert match_product('wb','shop',sku='10',article=None,catalog=catalog)['market']=='wb'
    assert match_product('wb','other',sku='10',article='same',catalog=catalog) is None
    with pytest.raises(ValueError):
        match_product('wb','shop',sku=None,article='same',catalog=catalog+[
            dict(market='wb',cabinet='shop',sku='11',article='same')])
