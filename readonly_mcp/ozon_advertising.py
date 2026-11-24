"""Verified Ozon Performance CSV contracts; attribution is not realized revenue."""
import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from readonly_mcp.analytics import _number
from readonly_mcp.rnp_economics import percent


def decimal_cell(value):
    return _number(value.replace('\u00a0','').replace(' ','').replace(',','.'),
                   'CSV amount',signed=True)


def csv_rows(text,first_column):
    lines=text.lstrip('\ufeff').splitlines()
    header=next((i for i,line in enumerate(lines) if line.startswith(first_column+';')),None)
    if header is None:
        raise ValueError('Unrecognized Ozon CSV header')
    return csv.DictReader(io.StringIO('\n'.join(lines[header:])),delimiter=';')


def parse_cpc_csv(text,campaign_id,start,end):
    products,days,seen={},[],set()
    columns={'views':'Показы','clicks':'Клики','carts':'Добавления в корзину',
        'expense_rub':'Расход, ₽, с НДС','attributed_units':'Продано товаров',
        'attributed_revenue_rub':'Продажи в продвижении, ₽'}
    for record in csv_rows(text,'День'):
        if record['День']=='Всего':
            continue
        day=datetime.strptime(record['День'],'%d.%m.%Y').date()
        sku=record['sku']
        if not sku.isdigit() or not start<=day<=end or (day,sku) in seen:
            raise ValueError('Invalid or repeated CPC row')
        seen.add((day,sku))
        values={key:decimal_cell(record[column]) for key,column in columns.items()}
        if any(values[key]<0 or values[key]!=int(values[key]) for key in ('views','clicks','carts','attributed_units')):
            raise ValueError('Invalid CPC counter')
        days.append(dict(date=str(day),sku=sku,**{k:str(v) for k,v in values.items()}))
        item=products.setdefault(sku,{key:Decimal(0) for key in columns})
        for key,value in values.items():item[key]+=value
    rows=[]
    for sku,item in products.items():
        rows.append(dict(sku=sku,**{key:str(value) for key,value in item.items()},
            ctr_percent=percent(item['clicks'],item['views']),
            cpc_rub=float(item['expense_rub']/item['clicks']) if item['clicks'] else None,
            cpo_rub=float(item['expense_rub']/item['attributed_units']) if item['attributed_units'] else None,
            drr_attributed_percent=percent(item['expense_rub'],item['attributed_revenue_rub'])))
    return dict(status='ok',campaign_id=campaign_id,products=rows,days=days,
        scope='one_CPC_campaign',expense_rub=str(sum((p['expense_rub'] for p in products.values()),Decimal(0))),
        warning='Атрибутированные рекламные продажи — не фактические выкупы и не вся выручка SKU.')


def parse_cpo_csv(text):
    rows,seen=[],set()
    for record in csv_rows(text,'SKU'):
        sku=record['SKU']
        if not sku.isdigit() or sku in seen:
            raise ValueError('Invalid or duplicate CPO SKU')
        seen.add(sku)
        rows.append(dict(sku=sku,article=record['Артикул'],
            combo_expense_rub=str(decimal_cell(record['Расход ("Комбо-модель"), ₽'])),
            cpo_expense_rub=str(decimal_cell(record['Расход ("Оплата за заказ"), ₽']))))
    return dict(status='ok',scope='selected_products_only',products=rows,
                warning='Включает только отчёт выбранных товаров, не инструмент «все товары». '
                        'Комбо-модель и CPO сохранены отдельно; пересечение с CPC не сверено.')


async def request(operation,*,query=None,body=None,path_values=None):
    from ozon_perf_mcp import server
    spec=server.catalog.get(operation)
    if spec is None or spec.safety!='read':
        raise ValueError('Only catalogued read operations are permitted')
    response=await server.client.call_spec(spec,query=query,json_body=body,path_values=path_values)
    if not response.get('ok'):
        raise ValueError('Ozon Performance report request failed: '+str(response.get('error_type','unavailable')))
    return response['data']


async def get_ozon_advertising_details(report_kind:Literal['cpc','cpo_selected'],
    date_from:date,date_to:date,campaign_id:str|None=None,report_id:UUID|None=None)->dict:
    """Детальная реклама Ozon напрямую: CPC по дням/SKU либо CPO выбранных товаров.

    CPC требует один campaign_id из Ozon Performance. CPO — весь инструмент
    выбранных товаров, не отдельная кампания и не «все товары». Не складывай
    CPC/Комбо-модель/CPO без сверки пересечений. Выручка — атрибутированная.
    Создаёт только отчёт, не меняет рекламу. При in_progress повтори с теми же
    параметрами и report_id после retry_after; не создавай новый отчёт.
    Не является полным рекламным итогом кабинета, исключает «все товары»/медиа.
    """
    msk=timezone(timedelta(hours=3))
    if date_from>date_to or (date_to-date_from).days>=31 or date_to>=datetime.now(msk).date():
        raise ValueError('Use 1..31 completed days')
    if report_kind=='cpc' and (not campaign_id or not campaign_id.isdigit()):
        raise ValueError('CPC requires a numeric campaign_id')
    if report_kind=='cpo_selected' and campaign_id:
        raise ValueError('CPO report covers selected-products instrument; omit campaign_id')
    start=datetime.combine(date_from,datetime.min.time(),msk).astimezone(timezone.utc)
    stop=(datetime.combine(date_to+timedelta(days=1),datetime.min.time(),msk)-timedelta(seconds=1)).astimezone(timezone.utc)
    if report_id is None:
        if report_kind=='cpc':
            job=await request('ozonperf_post_api_client_statistics',body=dict(
                campaigns=[campaign_id],dateFrom=str(date_from),dateTo=str(date_to),groupBy='DATE'))
        else:
            job=await request('ozonperf_post_api_client_statistic_products_generate',body={
                'from':start.isoformat().replace('+00:00','Z'),'to':stop.isoformat().replace('+00:00','Z')})
        report_id=UUID(job['UUID'])
    state=await request('ozonperf_get_api_client_statistics_uuid',path_values={'UUID':str(report_id)})
    if state['state'] in ('NOT_STARTED','IN_PROGRESS'):
        return dict(status='in_progress',report_id=str(report_id),retry_after=10)
    if state['state']!='OK':
        return dict(status='unavailable',report_id=str(report_id),message='Ozon не сформировал отчёт')
    original=state['request']
    if (datetime.fromisoformat(original['from'].replace('Z','+00:00'))!=start or
        datetime.fromisoformat(original['to'].replace('Z','+00:00'))!=stop):
        raise ValueError('Report dates do not match requested dates')
    if report_kind=='cpc' and original['campaigns']!=[campaign_id]:
        raise ValueError('Report campaign mismatch')
    expected_kind='STATS' if report_kind=='cpc' else 'SEARCH_PROMO_ORGANISATION_PRODUCTS'
    if state['kind']!=expected_kind:
        raise ValueError('Report type mismatch')
    text=await request('ozonperf_get_api_client_statistics_report',query={'UUID':str(report_id)})
    if not isinstance(text,str):
        raise ValueError('Expected a single CSV report')
    result=(parse_cpc_csv(text,campaign_id,date_from,date_to) if report_kind=='cpc' else parse_cpo_csv(text))
    return {**result,'report_id':str(report_id),'date_from':str(date_from),'date_to':str(date_to),
            'currency':'RUB','date_basis':'Ozon Performance statistics date',
            'retrieved_at':datetime.now(timezone.utc).isoformat()}
