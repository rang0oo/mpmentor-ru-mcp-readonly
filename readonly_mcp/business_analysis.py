"""Explicit, reproducible business calculations, independent of MPSTATS."""
from decimal import Decimal, ROUND_CEILING
from readonly_mcp.analytics import _number, check_financial_summary
from readonly_mcp.rnp_economics import percent


def abc_analysis(items,a_threshold='0.8',b_threshold='0.95'):
    a,b=Decimal(a_threshold),Decimal(b_threshold)
    if not 0<a<b<1:
        raise ValueError('Expected 0 < A threshold < B threshold < 1')
    rows=[{**item,'value':_number(str(item['value']),'value',signed=True)} for item in items]
    if len({r['sku'] for r in rows})!=len(rows):
        raise ValueError('Aggregate duplicate SKUs before ABC')
    rows.sort(key=lambda row:(-row['value'],row['sku']))
    total=sum((row['value'] for row in rows if row['value']>0),Decimal(0))
    cumulative=Decimal(0)
    for row in rows:
        value=row['value']
        if value<=0:
            group='loss' if value<0 else 'no_activity'
        else:
            group='A' if cumulative/total<a else 'B' if cumulative/total<b else 'C'
            cumulative+=value
        row.update(abc=group,share_percent=percent(max(value,Decimal(0)),total),
                   cumulative_percent=percent(cumulative,total),value=str(value))
    return rows


def supply_plan(*,demand_units,observed_days,available,incoming_before_target,
                lead_days,review_days,safety_days):
    inputs=dict(demand_units=demand_units,observed_days=observed_days,available=available,
                incoming_before_target=incoming_before_target,lead_days=lead_days,
                review_days=review_days,safety_days=safety_days)
    missing=[key for key,value in inputs.items() if value is None]
    if missing:
        return dict(kind='forecast',recommended_units=None,missing_inputs=missing)
    values={key:_number(str(value),key) for key,value in inputs.items()}
    for key in ('observed_days','lead_days','review_days','safety_days'):
        if values[key]!=values[key].to_integral_value():
            raise ValueError('Days must be integers')
    if not values['observed_days']:
        return dict(kind='forecast',recommended_units=None,missing_inputs=['observed_days'])
    speed=values['demand_units']/values['observed_days']
    horizon=values['lead_days']+values['review_days']+values['safety_days']
    units=max(Decimal(0),speed*horizon-values['available']-values['incoming_before_target'])
    return dict(kind='forecast',model='mean demand × (lead + review + safety) − available − arriving stock',
        daily_demand=float(speed),days_of_cover=float(values['available']/speed) if speed else None,
        recommended_units=int(units.to_integral_value(rounding=ROUND_CEILING)),missing_inputs=[],
        stockout_before_arrival=values['available']<speed*values['lead_days'],
        warning='План по средней скорости. Не учитывает сезонность, будущие акции и неизвестные сроки поставок; '
                'дни отсутствия товара требуют отдельного учёта скрытого спроса.')


def funnel_metrics(*,views,opens,carts,orders):
    values={key:None if value is None else _number(str(value),key)
            for key,value in dict(views=views,opens=opens,carts=carts,orders=orders).items()}
    result=dict(ctr_percent=percent(values['opens'],values['views']),
                add_to_cart_percent=percent(values['carts'],values['opens']),
                cart_to_order_percent=percent(values['orders'],values['carts']),warnings=[])
    if any(value is not None and value>100 for key,value in result.items() if key!='warnings'):
        result['warnings'].append('Конверсия выше 100%: проверьте периоды, события, количество единиц и когорты. Значение не обрезано.')
    return result


def profit_calculation(*,realized_revenue,marketplace_expenses_excluding_ads,cost_of_goods,
                       advertising,taxes,other_expenses,adjustments,expenses_complete):
    return check_financial_summary(realized_revenue,marketplace_expenses_excluding_ads,
        cost_of_goods=cost_of_goods,advertising=advertising,taxes=taxes,
        other_expenses=other_expenses,adjustments=adjustments,complete=expenses_complete)
