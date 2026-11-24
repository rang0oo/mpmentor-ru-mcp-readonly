"""Chat-entered business settings; writes only to the local business database."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from readonly_mcp.business_store import BusinessStore


class CostInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    article: str=Field(min_length=1,description='Точный артикул продавца; цена за продаваемую единицу')
    amount: str=Field(description='Себестоимость в RUB, например 42.50. Ноль только по явному указанию пользователя.')
    effective_from: date


class TaxInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    regime: Literal['income','income_minus_expenses','general','patent','manual']
    effective_from: date
    rate_percent: str|None=None
    vat_percent: str|None=None


def active_cabinet(market):
    from wb_mcp import server as wb
    from ozon_mcp import server as ozon
    config=(wb if market=='wb' else ozon).client.config
    active=config.store.list_cabinets(config.name).get('active')
    if active:
        return active
    creds,_=config.resolve_creds()
    if not all(creds.get(key) for key in config.fields):
        raise ValueError('Сначала подключите кабинет этой площадки')
    return 'environment credentials'


def save_business_settings(market:Literal['wb','ozon'],costs:list[CostInput]|None=None,
                           tax:TaxInput|None=None)->dict:
    """Запомнить указанные пользователем в чате себестоимость и налоги активного кабинета.

    Пишет ТОЛЬКО в локальную базу. Не меняет цены, налоги или настройки WB/Ozon.
    Передавай исключительно явно сообщённые пользователем значения и даты начала
    действия. Не переноси чужие/MPSTATS настройки без подтверждения пользователя.
    Ставки и НДС не угадывай. income=УСН доходы; income_minus_expenses=УСН доходы
    минус расходы; general=ОСНО; patent=патент; manual=ручной расчёт.
    Для сложных режимов хранит настройки, не обещает расчёт налоговой декларации.
    Себестоимость — RUB за продаваемую единицу, отдельно по площадке и кабинету.
    История изменений сохраняется. Для изменения передай новую запись с датой.
    """
    cabinet=active_cabinet(market)
    def unpack(model):
        value=model.model_dump(mode='json',exclude_none=True)
        return value
    return BusinessStore().save_settings(market,cabinet,
        costs=[unpack(c) for c in (costs or [])],tax=unpack(tax) if tax else None)


def get_business_settings(market:Literal['wb','ozon'],articles:list[str]|None=None,
                          on_date:str|None=None)->dict:
    """Прочитать локальные настройки и запросить у пользователя недостающие данные.

    Вызывай перед расчётом прибыли. articles — точные артикулы продавца из отчёта.
    questions — вопросы для чата; после ответа пользователя вызови
    save_business_settings. Заполненное повторно не спрашивай. Дата on_date ISO;
    по умолчанию сегодня МСК. Для периода со сменой ставок/цен проверяй каждую
    дату операции. Неполные настройки запрещено заменять нулями.
    """
    day=on_date or datetime.now(timezone(timedelta(hours=3))).date().isoformat()
    cabinet=active_cabinet(market)
    settings=BusinessStore().settings(market,cabinet,day)
    missing_costs=[a for a in dict.fromkeys(articles or []) if a not in settings['costs']]
    tax=settings['tax']
    missing_tax=['regime','rate_percent','vat_percent','effective_from'] if tax is None else [
        key for key in ('rate_percent','vat_percent') if tax[key] is None]
    questions=[]
    if missing_costs:
        questions.append('Укажите себестоимость в ₽ за продаваемую единицу для '+
                         ', '.join(missing_costs)+' и дату начала действия этих цен.')
    if missing_tax:
        labels={'regime':'налоговый режим','rate_percent':'ставка налога, %',
                'vat_percent':'ставка НДС, %','effective_from':'дата начала действия'}
        questions.append('Для кабинета '+cabinet+' ('+market+') укажите недостающие налоговые настройки: '+
                         ', '.join(labels[key] for key in missing_tax)+'. Нулевой НДС тоже нужно указать явно.')
    return dict(settings=settings,missing_cost_articles=missing_costs,
                missing_tax_fields=missing_tax,questions=questions,
                ready_for_tax_model=not missing_tax,
                warning='Налоговый режим хранится по вашему указанию. Полнота финансовых расходов проверяется отдельно.')
