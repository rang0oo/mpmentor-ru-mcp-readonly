"""Audit candidate formulas against explicitly supplied MPSTATS reference reports.

No credentials or API access. Customer reference data and results stay outside
the repository. Numerical agreement is evidence on this sample, not proof of
an inaccessible proprietary algorithm or complete accounting inputs.
"""
import argparse
import json
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from readonly_mcp.methodology import calculate_pnl,forecast_sales


def audit(current,previous,ozon,wb_daily=None,ozon_daily=None):
    checks={}
    def check(name,sku,actual,expected,tolerance='0.01'):
        if actual is None or expected is None:return
        entry=checks.setdefault(name,dict(tested=0,matched=0,max_abs_error='0',mismatches=[]))
        error=abs(D(str(actual))-expected)
        entry['tested']+=1
        entry['max_abs_error']=str(max(D(entry['max_abs_error']),error))
        if error<=D(tolerance):entry['matched']+=1
        else:entry['mismatches'].append(dict(row=sku,actual=str(actual),expected=str(expected),error=str(error)))
    def ratio(a,b):return a/b*100 if b>0 else None
    wbs=[('2026-11-16..22',current['wbprod']['data']['data']+current['wbprod2']['data']['data'],
          current['wbprod']['data']['total']),
         ('2026-11-09..15',previous['wb_previous']['data']['data'],previous['wb_previous']['data']['total'])]
    for period,rows,total in wbs:
        if len(rows)!=total:raise ValueError('Incomplete WB reference')
        for row in rows:
            n=lambda key:D(str(row[key]))
            if not any(n(k) for k in ('sales_count','profit','orders_count','logistic_all')):continue
            identity=period+':'+row['sa_name']+':'+str(row['nm_id'])
            check('wb.profit_from_net_marketplace',identity,row['profit'],
                  n('for_pay')-n('sales_cost')+n('returns_cost')-n('taxes'))
            fees=sum((n(k) for k in ('total_commission_without_spp','logistic_all','storage_fee',
                'acceptance','advertisement','penalty','deduction','total_cashback','acquiring')),D(0))
            check('wb.net_marketplace_from_expenses',identity,row['for_pay'],n('sales_ret_sum')-fees,'0.03')
            mapped=dict(commission=str(n('total_commission_without_spp')),logistics=str(n('logistic_all')),
                acquiring=str(n('acquiring')),storage=str(n('storage_fee')),acceptance=str(n('acceptance')),
                advertising=str(n('advertisement')),penalties=str(n('penalty')),
                other_marketplace=str(n('deduction')+n('total_cashback')),other_business='0')
            independent=calculate_pnl(str(n('sales_ret_sum')),mapped,str(n('sales_cost')),
                str(n('returns_cost')),str(n('taxes')),'0',True)
            check('wb.independent_pnl_engine',identity,row['profit'],D(independent['profit']))
            check('wb.drr_orders',identity,row['advertisement_expenses_in_orders'],ratio(n('advertisement'),n('orders_sum')))
            check('wb.drr_net_sales',identity,row['advertisement_expenses_in_sales'],ratio(n('advertisement'),n('sales_ret_sum')))
            check('wb.ros',identity,row['rentable'],ratio(n('profit'),n('sales_ret_sum')))
            margin=n('sales_ret_sum')-n('total_commission_without_spp')-n('logistic_all')-n('acquiring')-n('sales_cost')+n('returns_cost')
            check('wb.margin',identity,row['margin'],ratio(margin,n('sales_ret_sum')))
            net_units=n('sales_count')-n('returns_count')
            check('wb.average_profit',identity,row['avg_profit'],n('profit')/net_units if net_units>0 else None)
    for key in ('formula_oz_current','formula_oz_previous'):
        source=ozon[key]
        if len(source['rows'])!=source['total'] or source.get('truncated'):
            raise ValueError('Incomplete Ozon reference')
        for row in source['rows']:
            if row['sku'] is None or not row.get('sales_count'):continue
            n=lambda field:D(str(row[field]))
            identity=key+':'+str(row['sku'])
            check('ozon.profit_from_net_marketplace',identity,row['profit'],
                  n('to_pay')-n('sales_cost_price')+n('returns_cost')-n('expenses_taxes'))
            check('ozon.profit_from_expenses_total',identity,row['profit'],n('sales_after_returns')-n('expenses_total'))
            check('ozon.drr_gross_seller_sales',identity,row['expenses_promotion_share'],
                  ratio(n('expenses_promotion'),n('sales_revenue_seller_price')))
            check('ozon.ros',identity,row['ros'],ratio(n('profit'),n('sales_after_returns')))
            check('ozon.candidate_ros_gross_seller_sales',identity,row['ros'],ratio(n('profit'),n('sales_revenue_seller_price')))
    for period,market,data in [
        ('current','wb',current['wbpulse']),('previous','wb',previous['wb_pulse_previous']),
        ('current','ozon',current['ozpulse']),('previous','ozon',previous['oz_pulse_previous'])]:
        for row in data['products']:
            value=lambda x:D(str(x['value'] if isinstance(x,dict) else x))
            q=value(row['orders']['orders_count']); amount=value(row['orders']['orders_amount'])
            if q<=0:continue
            identity=period+':'+str(row['sku'])
            ad=value(row['advert_amount']); sales=value(row['sales']['sales_amount_predicted'])
            check(market+'.rnp_drr_orders',identity,row['drr']['drr_in_orders'],ratio(ad,amount),'0.02')
            check(market+'.rnp_drr_forecast_sales',identity,row['drr']['drr_in_sales'],ratio(ad,sales),'0.02')
            # Deliberately strict: keep counterexamples to the simple aggregate-rate hypothesis.
            predicted_q=value(row['sales']['sales_count_predicted'])
            rate=value(row['sales']['buyout_percent'])
            check(market+'.candidate_weekly_quantity_from_rounded_rate',identity,predicted_q,q*rate/100,'0.005')
    for market,daily,weekly in [('wb',wb_daily,current['wbpulse']),('ozon',ozon_daily,current['ozpulse'])]:
        if daily is None:continue
        if set(daily)!={f'2026-11-{day}' for day in range(16,23)}:
            raise ValueError('Daily reference must cover the exact comparison week')
        totals={}
        for day,source in daily.items():
            if source['total']!=len(source['products']):raise ValueError('Incomplete daily reference')
            for row in source['products']:
                q=D(str(row['orders']['orders_count'])); cash=D(str(row['orders']['orders_amount']))
                predicted_q=D(str(row['sales']['sales_count_predicted']))
                predicted_cash=D(str(row['sales']['sales_amount_predicted']))
                key=str(row['sku']); total=totals.setdefault(key,[D(0),D(0)])
                total[0]+=predicted_q;total[1]+=predicted_cash
                if not q:continue
                rate=D(str(row['sales']['buyout_percent']))/100
                qty_step=D(1) if market=='wb' else D('.01')
                cash_step=D('.01') if market=='wb' else D(1)
                check(market+'.daily_qty_from_displayed_rate',day+':'+key,predicted_q,
                      (q*rate).quantize(qty_step,rounding=ROUND_HALF_UP),'0.005')
                check(market+'.daily_cash_from_predicted_qty',day+':'+key,predicted_cash,
                      (predicted_q*cash/q).quantize(cash_step,rounding=ROUND_HALF_UP))
                if market=='wb':
                    calculated=forecast_sales([dict(ordered_units=str(q),ordered_rub=str(cash),
                        buyout_percent=str(rate*100))],model='wb_daily_round')
                    check('wb.independent_forecast_engine_qty',day+':'+key,predicted_q,D(calculated['predicted_units']))
                    check('wb.independent_forecast_engine_cash',day+':'+key,predicted_cash,D(calculated['predicted_revenue']))
        for row in weekly['products']:
            if not row['orders']['orders_count']:continue
            key=str(row['sku']);qty,cash=totals.get(key,[D(0),D(0)])
            check(market+'.candidate_weekly_qty_sum_of_daily',key,row['sales']['sales_count_predicted'],qty)
            check(market+'.candidate_weekly_cash_sum_of_daily',key,row['sales']['sales_amount_predicted'],cash)
    return dict(periods=['2026-11-09/2026-11-15','2026-11-16/2026-11-22'],checks=checks,
        warning='Two reference weeks; no claim of full MPSTATS equivalence. Zero-activity rows excluded. '
                'Failed candidate formulas must not be labelled recovered algorithms.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('current','previous','ozon','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--wb-daily',type=Path)
    parser.add_argument('--ozon-daily',type=Path)
    args=parser.parse_args()
    load=lambda path:json.loads(path.read_text())
    result=audit(load(args.current),load(args.previous),load(args.ozon),
                 load(args.wb_daily) if args.wb_daily else None,load(args.ozon_daily) if args.ozon_daily else None)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    for name,check in result['checks'].items():print(name,str(check['matched'])+'/'+str(check['tested']),
                                                   'max error',check['max_abs_error'])


if __name__=='__main__':main()
