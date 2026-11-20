"""Conservative metric interpretation and explicit, decimal financial checks.

No credentials, network calls or inferred accounting inputs.
"""
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import Literal


CONTRACTS = {
    ('ozon', 'ozon_analytics_data'): {
        'source': 'https://dev.ozon.ru/news/252-Izmeneniia-v-rabote-metoda-v1-analytics-data/',
        'fields': {
            'revenue': ('Заказано на сумму', 'RUB', 'Не фактические продажи, не выплата и не прибыль.'),
            'ordered_units': ('Заказано товаров', 'шт', 'Не количество оплаченных или выкупленных товаров.'),
        },
    },
    ('ozon', 'ozon_finance_accrual_by_day'): {
        'source': 'https://docs.ozon.ru/api/seller/',
        'fields': {
            'total_amount.amount': ('Итоговая сумма начисления', 'валюта total_amount.currency', 'Сохраняй знак. Не прибавляй повторно компоненты этой операции.'),
        },
    },
    ('wb', 'wb_analytics_funnel'): {
        'source': 'https://dev.wildberries.ru/openapi/analytics',
        'fields': {
            'orderCount': ('Количество заказанных товаров', 'шт', 'Не выкупы.'),
            'orderSum': ('Сумма заказанных товаров', 'RUB', 'Не сумма к выплате и не прибыль.'),
            'openCount': ('Переходы в карточку', 'шт', 'Не показы карточки; нельзя использовать как показы для CTR.'),
        },
    },
}

RULES = [
    'Сначала укажи кабинет, площадку, endpoint, период, поле даты, валюту и время получения данных.',
    'Одинаковое имя поля в разных endpoint не доказывает одинаковый смысл.',
    'Незнакомое поле: запроси describe_method и официальную документацию; не угадывай смысл.',
    'Заказы, выкупы, начисления, выплаты и прибыль — разные показатели с разными датами.',
    'Текущий день неполный. Завершённый день не гарантирует окончательность финансовых начислений.',
    'Проверь все страницы, truncated и total; неизвестная полнота не означает полную выгрузку.',
    'Не заменяй null нулём. Сохраняй знаки операций, валюту и единицы.',
    'Не складывай итог и его компоненты. Не вычитай рекламу повторно, если она уже в расходах.',
    'Возврат по заказу другого периода нельзя механически вычитать из конверсии текущей когорты.',
    'Проценты считай из сумм числителей и знаменателей, не средним процентов строк; при нуле база не определена.',
    'Для сверки отчётов сначала выровняй кабинет, даты, статусы, FBO/FBS, валюту и охват товаров.',
    'Прогноз маркируй отдельно от факта; расчёт по неполным затратам не называй чистой прибылью.',
]


def explain_marketplace_metrics(market: Literal['wb', 'ozon'], operation_id: str,
                                fields: list[str] | None = None) -> dict:
    """Explain endpoint-specific metrics BEFORE interpreting a seller report.

    Unknown fields are explicitly unknown; this is a verified subset, not all API fields.
    Returns meanings, units, pitfalls and mandatory data-quality rules.
    """
    contract = CONTRACTS.get((market, operation_id), {})
    known = contract.get('fields', {})
    requested = fields if fields is not None else list(known)
    return {
        'market': market, 'operation_id': operation_id,
        'source': contract.get('source'), 'coverage': 'partial',
        'metrics': {key: dict(zip(('meaning', 'unit', 'warning'), known[key]))
                    for key in requested if key in known},
        'unknown_fields': [key for key in requested if key not in known],
        'rules': RULES,
    }


def _number(value: str, name: str, signed: bool = False) -> Decimal:
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'{name}: expected a finite decimal number') from None
    if not number.is_finite() or (not signed and number < 0):
        raise ValueError(f'{name}: expected a finite {"signed" if signed else "nonnegative"} number')
    return number


def check_financial_summary(
    realized_revenue: str, marketplace_expenses: str,
    cost_of_goods: str | None = None, advertising: str | None = None,
    taxes: str | None = None, other_expenses: str | None = None,
    adjustments: str | None = None, complete: bool = False,
) -> dict:
    """Check an ALREADY reconciled realized-sales summary in one currency and period.

    Decimal amounts as strings. Expenses are positive, adjustments signed.
    Every expense must occur exactly once: marketplace_expenses EXCLUDES advertising,
    taxes, cost_of_goods and other_expenses. Pass explicit '0' only for known zero.
    Never pass ordered revenue from analytics. complete=True only after checking
    pagination, cabinet, currency, date basis and expense coverage. This tool does
    not fetch data or certify supplied values; result is a calculation, not audit.
    """
    revenue = _number(realized_revenue, 'realized_revenue')
    fees = _number(marketplace_expenses, 'marketplace_expenses')
    raw = dict(cost_of_goods=cost_of_goods, advertising=advertising, taxes=taxes,
               other_expenses=other_expenses, adjustments=adjustments)
    missing = [key for key, value in raw.items() if value is None]
    values = {key: _number(value, key, signed=key == 'adjustments')
              for key, value in raw.items() if value is not None}
    profit = None
    if complete and not missing:
        profit = revenue - fees - sum(values[key] for key in raw if key != 'adjustments') + values['adjustments']
    return {
        'status': 'calculated' if profit is not None else 'incomplete',
        'after_marketplace': str(revenue - fees),
        'profit': str(profit) if profit is not None else None,
        'profit_margin_percent': str(profit / revenue * 100) if profit is not None and revenue else None,
        'missing_inputs': missing, 'complete_asserted_by_caller': complete,
        'formula': 'realized_revenue - marketplace_expenses - cost_of_goods - advertising - taxes - other_expenses + adjustments',
        'warning': 'Расчёт по переданным данным; не подтверждает их полноту. Остаток после удержаний площадки не является прибылью.',
    }


def reconcile_marketplace_totals(left_amount: str, right_amount: str,
                                 left_context: dict[str, str], right_context: dict[str, str],
                                 tolerance: str = '0.01') -> dict:
    """Compare two complete report totals ONLY with matching accounting contexts.

    Both contexts must specify market, cabinet, currency, date_from, date_to,
    date_basis (e.g. operation_date) and metric_kind (e.g. signed_accruals).
    Add filters/status/scheme/coverage keys when applicable: every supplied key
    must match. Normalize units and align periods before calling. Caller must
    independently verify pagination and source freshness. This checks numerical
    agreement, not upstream truth. Signed amounts and decimal strings supported.
    """
    required = {'market', 'cabinet', 'currency', 'date_from', 'date_to', 'date_basis', 'metric_kind'}
    for context in (left_context, right_context):
        if any(not context.get(key, '').strip() for key in required):
            raise ValueError('Both contexts require: ' + ', '.join(sorted(required)))
        if date.fromisoformat(context['date_from']) > date.fromisoformat(context['date_to']):
            raise ValueError('Invalid date range')
    mismatched = [key for key in sorted(left_context.keys() | right_context.keys())
                  if left_context.get(key) != right_context.get(key)]
    if mismatched:
        return {'status': 'not_comparable', 'mismatched_context': mismatched, 'difference': None}
    left = _number(left_amount, 'left_amount', signed=True)
    right = _number(right_amount, 'right_amount', signed=True)
    threshold = _number(tolerance, 'tolerance')
    difference = left - right
    return {'status': 'matched' if abs(difference) <= threshold else 'mismatch',
            'difference': str(difference), 'tolerance': str(threshold),
            'context': left_context,
            'warning': 'Совпадение сумм не доказывает полноту и корректность исходных отчётов.'}
