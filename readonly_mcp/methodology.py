"""Versioned independent formulas. No inferred facts, hidden allocation or MPSTATS calls."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Literal

from readonly_mcp.analytics import _number
from readonly_mcp.rnp_economics import percent

EXPENSES=('commission','logistics','acquiring','storage','acceptance','advertising',
          'penalties','other_marketplace','other_business')
ALLOCATION_METHODS={'by_revenue','by_units','by_stock_volume_days','by_received_units','at_business'}


def allocate_expense(amount:str,basis:dict[str,str|None],method:str='at_business')->dict:
    """Allocate an explicitly selected expense, preserving signs and source precision.

    This is our management-accounting policy, not a recovered MPSTATS algorithm.
    Direct SKU charges must remain direct; do not call this to redistribute them.
    No missing basis may be silently dropped or reweighted. Sub-kopeck residue
    remains unallocated. Deterministic largest-remainder allocation in kopecks.
    """
    if method not in ALLOCATION_METHODS:
        raise ValueError('Unknown allocation method')
    total=_number(amount,'amount',signed=True)
    parsed={str(key):None if value is None else _number(value,'basis') for key,value in basis.items()}
    unknown=[key for key,value in parsed.items() if value is None]
    weights=sum((v for v in parsed.values() if v is not None),Decimal(0))
    if method=='at_business' or unknown or not weights:
        return dict(method=method,methodology_version='1',allocated={},unallocated=str(total),
                    missing_basis=unknown,conservation_verified=True,estimated=False)
    keys=sorted(parsed)
    cents=int((abs(total)*100).to_integral_value(rounding=ROUND_FLOOR))
    quotas={key:Decimal(cents)*parsed[key]/weights for key in keys}
    allocated={key:int(quotas[key].to_integral_value(rounding=ROUND_FLOOR)) for key in keys}
    remainder=cents-sum(allocated.values())
    ranked=sorted(keys,key=lambda key:(-(quotas[key]-allocated[key]),key))
    for key in ranked[:remainder]:allocated[key]+=1
    sign=Decimal(-1) if total<0 else Decimal(1)
    money={key:sign*Decimal(allocated[key])/100 for key in keys}
    residue=total-sum(money.values(),Decimal(0))
    assert sum(money.values(),Decimal(0))+residue==total
    return dict(method=method,methodology_version='1',
                allocated={key:format(value,'.2f') for key,value in money.items()},
                unallocated=str(residue),missing_basis=[],conservation_verified=True,estimated=True)


def calculate_pnl(revenue_net:str|None,expenses:dict[str,str|None],
                  sold_cogs:str|None,recovered_return_cogs:str|None,taxes:str|None,
                  adjustments:str|None,coverage_complete:bool=False)->dict:
    """Realized P&L from an already matched, non-overlapping ledger.

    Expenses are signed costs (positive=expense, negative=credit). Revenue is
    already net of refunds. Adjustments are signed income. Recovery of returned
    COGS is explicit, not automatically every refund. Taxes are supplied amounts,
    not a universal tax rule. Coverage is caller-asserted, not certified here.
    """
    if set(expenses)-set(EXPENSES):
        raise ValueError('Classify unsupported expense categories explicitly before calculation')
    inputs=dict(revenue_net=revenue_net,sold_cogs=sold_cogs,
                recovered_return_cogs=recovered_return_cogs,taxes=taxes,adjustments=adjustments,
                **{key:expenses.get(key) for key in EXPENSES})
    missing=[key for key,value in inputs.items() if value is None]
    values={key:_number(value,key,signed=key not in ('sold_cogs','recovered_return_cogs'))
            for key,value in inputs.items() if value is not None}
    profit=None
    if coverage_complete is True and not missing:
        profit=(values['revenue_net']-sum((values[k] for k in EXPENSES),Decimal(0))-
                values['sold_cogs']+values['recovered_return_cogs']-values['taxes']+values['adjustments'])
    return dict(kind='realized',methodology_version='1',
        status='calculated' if profit is not None else 'incomplete',
        profit=str(profit) if profit is not None else None,
        ros_percent=percent(profit,values.get('revenue_net')),
        missing_inputs=missing,coverage_asserted=coverage_complete,
        formula='net_revenue - signed_expenses - sold_cogs + recovered_return_cogs - taxes + signed_adjustments',
        warning='Арифметика по подготовленным данным. Полноту источников, налоговую базу и отсутствие двойного счёта нужно подтвердить отдельно.')


def forecast_sales(daily_orders:list[dict],model:Literal['expected_value','wb_daily_round']='expected_value')->dict:
    """Daily forecast with explicit rounding and aggregation policy.

    expected_value is our unrounded expectation. wb_daily_round reproduces the
    observed WB daily arithmetic: integer expected quantity, then that quantity
    times daily average order value, rounded to kopecks; sum days afterwards.
    Half-up ties are our explicit policy; exact vendor tie handling is unverified.
    Historical buyout rates must be provided from completed cohorts, not guessed.
    """
    if model not in ('expected_value','wb_daily_round'):
        raise ValueError('Unknown forecast model')
    units,revenue=Decimal(0),Decimal(0)
    missing=[]
    for index,row in enumerate(daily_orders):
        if any(row.get(k) is None for k in ('ordered_units','ordered_rub','buyout_percent')):
            missing.append(index)
            continue
        q=_number(row['ordered_units'],'ordered_units')
        cash=_number(row['ordered_rub'],'ordered_rub')
        rate=_number(row['buyout_percent'],'buyout_percent')
        if rate>100:
            raise ValueError('Buyout percent must be 0..100')
        quantity=q*rate/100
        amount=cash*rate/100
        if model=='wb_daily_round':
            if not q and cash:
                raise ValueError('Nonzero order amount without ordered units')
            quantity=quantity.quantize(Decimal(1),rounding=ROUND_HALF_UP)
            amount=(quantity*cash/q if q else Decimal(0)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        units+=quantity
        revenue+=amount
    usable=bool(daily_orders) and not missing
    return dict(kind='forecast',model=model,methodology_version='1',
        predicted_units=str(units) if usable else None,
        predicted_revenue=str(revenue) if usable else None,missing_days=missing,
        missing_inputs=['daily_orders'] if not daily_orders else [],
        formula=('sum(round(day.units × buyout_rate)), sum(round(day.predicted_units × daily_avg_bill,2))'
                 if model=='wb_daily_round' else 'sum(day.units × buyout_rate), sum(day.ordered_rub × buyout_rate)'),
        warning='Процент выкупа нужен из завершённых исторических когорт до даты прогноза. '
                'Без него прогноз не строится. Точные внутренние ставки и правила ничьих округления MPSTATS не подтверждены.')


def match_product(market,cabinet,*,sku,article,catalog):
    """Exact identity in one cabinet; no fuzzy names or implicit cross-market joins."""
    candidates=[row for row in catalog if row['market']==market and row['cabinet']==cabinet]
    if sku is not None:
        candidates=[row for row in candidates if str(row['sku'])==str(sku)]
    elif article:
        candidates=[row for row in candidates if row['article']==article]
    else:
        return None
    if len(candidates)>1:
        raise ValueError('Ambiguous product identity; supply SKU or dated mapping')
    if not candidates:
        return None
    if article and candidates[0]['article']!=article:
        raise ValueError('SKU/article conflict; verify historical mapping')
    return dict(candidates[0])


def explain_business_methodology()->dict:
    """Формулы нашего MCP, базы показателей и границы подтверждения MPSTATS.

    Прочитай перед расчётом. Проверка на выборке не доказывает внутренний
    алгоритм. Общие расходы не распределяются без явно выбранного правила.
    Самостоятельные расчёты не обращаются к MPSTATS и не зависят от подписки.
    """
    return dict(version='1',validated_on='2026-11-24',reference_periods=[
        '2026-11-09/2026-11-15','2026-11-16/2026-11-22'],
        formulas=[
            dict(id='drr_orders',formula='advertising / ordered_rub × 100',status='reference_checked'),
            dict(id='drr_gross_sales',formula='advertising / seller_sales_before_refunds × 100',
                 status='Ozon_products_reference_checked'),
            dict(id='drr_net_sales',formula='advertising / seller_sales_after_refunds × 100',
                 status='WB_products_reference_checked_and_our_standard'),
            dict(id='drr_forecast',formula='advertising / forecast_revenue × 100',
                 status='documented_RNP_base; precision_varies'),
            dict(id='profit_settlement_bridge',formula='after_marketplace - sold_cogs + returned_cogs - taxes',
                 status='44_active_reference_rows_exact',warning='after_marketplace is an accounting subtotal, not a bank payout'),
            dict(id='full_pnl',formula='net_revenue - signed_expenses - sold_cogs + recovered_return_cogs - taxes + signed_adjustments',
                 status='our_explicit_ledger_model; WB 26 rows exact',expense_categories=list(EXPENSES)),
            dict(id='wb_forecast',formula='sum daily round(units × buyout_rate); cash = daily rounded_qty × daily average bill, rounded to kopecks',
                 status='64_SKU_days_exact_and_12_weekly_SKUs_exact',warning='Vendor tie handling and exact historical rate estimator unverified'),
            dict(id='ozon_forecast',formula='expected_value model with explicit historical rates',
                 status='our_model; exact_vendor_period_aggregation_not_recovered'),
            dict(id='allocation',formula='signed cost × selected causal basis / total basis; kopecks by largest remainder',
                 status='our_policy',default='at_business',warning='Not claimed equivalent to MPSTATS allocation'),
            dict(id='matching',formula='market + cabinet + exact SKU; unique seller article only when SKU absent',
                 status='our_policy',warning='Ambiguity and identifier conflicts are not guessed'),
            dict(id='abc_supply',formula='ABC by positive contribution; stock plan from explicit demand, stock and lead time',
                 status='our_models; not claimed MPSTATS parity')],
        rules=['Не смешивать продажи, прогнозы и суммы заказов.',
               'Сначала прямые расходы SKU; общие расходы остаются общими до выбора правила.',
               'Сохранить знак корректировок и не учитывать итог вместе с компонентами.',
               'null не означает ноль. Неполные затраты блокируют прибыль.',
               'Налоги и историческая себестоимость берутся из подтверждённых пользователем данных.'],
        references=['https://wiki.mpstats.io/Личный_кабинет/Товары',
                    'https://wiki.mpstats.io/ru/Кабинет_Ozon/Рука_на_пульсе_Ozon'])
