"""Refresh, save and export business reports only on explicit request."""
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from readonly_mcp.business_settings import active_cabinet
from readonly_mcp.business_store import BusinessStore, encoded
from readonly_mcp.rnp import get_product_rnp


async def business_report(action:Literal['refresh','saved','export'],market:Literal['wb','ozon'],
                          date_from:date,date_to:date)->dict:
    """Отчёт своего кабинета: загрузка/сохранение либо чтение/выгрузка локальной копии.

    Работает только по запросу, без расписания. refresh читает WB/Ozon и сохраняет
    полный набор строк локально; saved читает сохранённое; export создаёт JSON
    из сохранённого отчёта. saved/export НЕ обращаются к API и не обновляют данные
    автоматически. Если копии нет — not_saved; для загрузки отдельно вызови refresh.
    Период 1..31 закрытых дней; кабинет — активный для выбранной площадки.
    Не меняет данные маркетплейсов. Пишет только локальную базу/файл экспорта.
    Неполная выгрузка не заменяет последнюю полную. Отчёт может иметь полные
    строки и неполную экономику: проверяй economics_status, sources и null.
    Экспорт включает дату получения, источник и предупреждения о полноте.
    """
    if date_from>date_to or (date_to-date_from).days>=31:
        raise ValueError('Use a period of 1..31 days')
    if action=='refresh' and date_to>=datetime.now(timezone(timedelta(hours=3))).date():
        raise ValueError('Use completed days only')
    cabinet=active_cabinet(market)
    store=BusinessStore()
    context=dict(market=market,cabinet=cabinet,dataset='period_rnp',date_from=str(date_from),
                 date_to=str(date_to),date_basis='see_sources',currency='RUB')
    if action=='refresh':
        response=await get_product_rnp(market=market,limit=1000,start_date=date_from,end_date=date_to)
        response=response.model_dump(mode='json') if hasattr(response,'model_dump') else response
        report=response['markets']['WB' if market=='wb' else 'Ozon']
        if report.get('cabinet')!=cabinet or report.get('status')!='ok':
            return dict(status='unavailable',context=context,message='Источник недоступен или кабинет изменился')
        complete=not report.get('display_truncated',True)
        snapshot=store.save_snapshot(context,report,complete=complete)
        if not complete:
            return dict(status='incomplete',context=context,snapshot_id=snapshot,
                message='Получены не все строки. Последний полный сохранённый отчёт не заменён.')
        return dict(status='saved',context=context,snapshot_id=snapshot,report=report,
                    economics_status=report.get('economics_status','unknown'))
    saved=store.latest_snapshot(context)
    if saved is None:
        return dict(status='not_saved',context=context,
                    message='За этот период нет полной локальной копии. Загрузите её отдельным запросом.')
    result=dict(status='saved',context=context,**saved,
                report=saved['payload'],economics_status=saved['payload'].get('economics_status','unknown'))
    result.pop('payload')
    if action=='saved':
        return result
    if action!='export':
        raise ValueError('Unknown report action')
    directory=store.path.parent/'exports'
    directory.mkdir(parents=True,exist_ok=True)
    fd,path=tempfile.mkstemp(prefix=f'{market}-{date_from}-{date_to}-',suffix='.json',dir=directory)
    with os.fdopen(fd,'w',encoding='utf-8') as handle:
        handle.write(encoded(result))
    return dict(status='exported',path=path,format='json',snapshot_id=saved['id'],
                context=context,retrieved_at=saved['retrieved_at'],economics_status=result['economics_status'])
