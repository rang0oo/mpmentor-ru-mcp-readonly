"""One-shot collection of an explicitly requested period; no background work."""
import argparse
import asyncio
import json
from datetime import date, datetime, timedelta, timezone

from readonly_mcp.business_store import BusinessStore
from readonly_mcp.rnp import get_product_rnp


async def collect_days(store,market,start,end,*,fetch=get_product_rnp):
    if start>end:
        raise ValueError('Invalid period')
    result=dict(saved_days=0,failed_days=0,partial_economics_days=0,days=[])
    day=start
    while day<=end:
        try:
            report=await fetch(market=market,limit=1000,start_date=day,end_date=day)
            report=report.model_dump(mode='json') if hasattr(report,'model_dump') else report
            saved=False
            for name,data in report['markets'].items():
                if data.get('status')!='ok' or not data.get('cabinet'):
                    result['days'].append(dict(day=str(day),market=name,status='source_unavailable'))
                    continue
                context=dict(market='wb' if name=='WB' else 'ozon',cabinet=data['cabinet'],
                    date_from=str(day),date_to=str(day),currency='RUB')
                complete=not data['display_truncated']
                orders=dict(rows=[{k:v for k,v in row.items() if k in (
                    'sku','article','name','units','ordered_rub')} for row in data['rows']],
                    source=data.get('order_source'),scope=data.get('summary_scope'))
                store.save_snapshot({**context,'dataset':'daily_orders','date_basis':'order_date'},
                                    orders,complete=complete)
                economic=dict(rows=data['rows'],summary=data.get('summary'),sources=data.get('sources'))
                econ_complete=complete and data.get('economics_status')=='ok'
                store.save_snapshot({**context,'dataset':'daily_economics','date_basis':'see_sources'},
                                    economic,complete=econ_complete)
                if not econ_complete:
                    result['partial_economics_days']+=1
                saved=True
                result['days'].append(dict(day=str(day),market=name,status='saved',
                                          economics_complete=econ_complete,rows_complete=complete))
            result['saved_days' if saved else 'failed_days']+=1
        except (ValueError,KeyError,TypeError,OSError):
            result['failed_days']+=1
            result['days'].append(dict(day=str(day),status='failed'))
        day+=timedelta(days=1)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--market',choices=['all','wb','ozon'],default='all')
    parser.add_argument('--date-from',type=date.fromisoformat,required=True)
    parser.add_argument('--date-to',type=date.fromisoformat,required=True)
    parser.add_argument('--database',help='Local SQLite path; default ~/.marketplace-mcp/business.sqlite3')
    args=parser.parse_args()
    today=datetime.now(timezone(timedelta(hours=3))).date()
    end,start=args.date_to,args.date_from
    if start>end or end>=today:
        parser.error('Specify an ordered period of completed days')
    result=asyncio.run(collect_days(BusinessStore(args.database),args.market,start,end))
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(1 if result['failed_days'] or result['partial_economics_days'] else 0)


if __name__=='__main__':
    main()
