"""Local, versioned business inputs and immutable source snapshots (no API keys)."""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

REGIMES = {'income', 'income_minus_expenses', 'general', 'patent', 'manual'}
CONTEXT_FIELDS = ('market','cabinet','dataset','date_from','date_to','date_basis','currency')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decimal_input(value, *, percentage=False):
    try:
        number=Decimal(str(value).replace(',', '.').replace(' ', ''))
    except (ValueError, InvalidOperation):
        raise ValueError('Expected a nonnegative finite decimal') from None
    if not number.is_finite() or number < 0 or (percentage and number > 100):
        raise ValueError('Invalid amount or percentage')
    return str(number)


def scope(market, cabinet):
    if market not in ('wb','ozon') or not isinstance(cabinet,str) or not cabinet.strip():
        raise ValueError('Specify marketplace and cabinet')


class BusinessStore:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ.get(
            'MARKETPLACE_MCP_HOME',Path.home()/'.marketplace-mcp'))/'business.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600)
        os.close(fd)
        os.chmod(self.path,0o600)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS inputs (
                    id INTEGER PRIMARY KEY, market TEXT NOT NULL, cabinet TEXT NOT NULL,
                    kind TEXT NOT NULL, article TEXT NOT NULL, effective_from TEXT NOT NULL,
                    payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS input_scope ON inputs(market,cabinet,kind,article,effective_from);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY, context TEXT NOT NULL, digest TEXT NOT NULL,
                    payload TEXT NOT NULL, complete INTEGER NOT NULL,
                    retrieved_at TEXT NOT NULL, UNIQUE(context,digest,complete));
            ''')

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=30)
        db.row_factory=sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_settings(self,market,cabinet,*,costs=(),tax=None):
        scope(market,cabinet)
        entries=[]
        for cost in costs:
            article=cost['article'].strip()
            if not article:
                raise ValueError('Empty article')
            effective=str(date.fromisoformat(cost['effective_from']))
            value=dict(article=article,amount=decimal_input(cost['amount']),
                       currency='RUB',effective_from=effective,source='user_chat')
            entries.append(('cost',article,effective,encoded(value)))
        if tax is not None:
            if tax['regime'] not in REGIMES:
                raise ValueError('Unknown tax regime')
            effective=str(date.fromisoformat(tax['effective_from']))
            value=dict(regime=tax['regime'],effective_from=effective,source='user_chat',
                       rate_percent=None,vat_percent=None)
            for key in ('rate_percent','vat_percent'):
                if tax.get(key) is not None:
                    value[key]=decimal_input(tax[key],percentage=True)
            entries.append(('tax','',effective,encoded(value)))
        if not entries:
            raise ValueError('No settings supplied')
        now=datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            for kind,article,effective,payload in entries:
                db.execute('INSERT INTO inputs(market,cabinet,kind,article,effective_from,payload,recorded_at) '
                           'VALUES(?,?,?,?,?,?,?)',(market,cabinet,kind,article,effective,payload,now))
        return dict(status='saved',market=market,cabinet=cabinet,revisions=len(entries))

    def settings(self,market,cabinet,on_date):
        scope(market,cabinet)
        day=str(date.fromisoformat(on_date))
        with self.connection() as db:
            records=db.execute('SELECT kind,article,payload FROM inputs WHERE market=? AND cabinet=? '
                'AND effective_from<=? ORDER BY effective_from,id',(market,cabinet,day)).fetchall()
        result=dict(costs={},tax=None,market=market,cabinet=cabinet,on_date=day)
        for record in records:
            value=json.loads(record['payload'])
            if record['kind']=='tax':
                result['tax']=value
            else:
                result['costs'][record['article']]=value
        return result

    def settings_history(self,market,cabinet):
        scope(market,cabinet)
        with self.connection() as db:
            rows=db.execute('SELECT kind,article,effective_from,recorded_at,payload FROM inputs '
                            'WHERE market=? AND cabinet=? ORDER BY id',(market,cabinet)).fetchall()
        return dict(revision_count=len(rows),revisions=[dict(row) for row in rows])

    def save_snapshot(self,context,payload,*,complete):
        if set(context)!=set(CONTEXT_FIELDS) or any(not isinstance(v,str) or not v.strip() for v in context.values()):
            raise ValueError('Snapshot context must be complete and unambiguous')
        scope(context['market'],context['cabinet'])
        if date.fromisoformat(context['date_from'])>date.fromisoformat(context['date_to']):
            raise ValueError('Invalid snapshot period')
        if type(complete) is not bool:
            raise ValueError('Explicit completeness required')
        body=encoded(payload)
        digest=hashlib.sha256(body.encode()).hexdigest()
        key=encoded(context)
        with self.connection() as db:
            db.execute('INSERT INTO snapshots(context,digest,payload,complete,retrieved_at) '
                'VALUES(?,?,?,?,?) ON CONFLICT(context,digest,complete) DO UPDATE '
                'SET retrieved_at=excluded.retrieved_at',
                (key,digest,body,int(complete),datetime.now(timezone.utc).isoformat()))
            return db.execute('SELECT id FROM snapshots WHERE context=? AND digest=? AND complete=?',
                              (key,digest,int(complete))).fetchone()['id']

    def latest_snapshot(self,context):
        with self.connection() as db:
            row=db.execute('SELECT id,payload,retrieved_at FROM snapshots WHERE context=? AND complete=1 '
                           'ORDER BY retrieved_at DESC,id DESC LIMIT 1',(encoded(context),)).fetchone()
        return None if row is None else dict(id=row['id'],payload=json.loads(row['payload']),
                                            retrieved_at=row['retrieved_at'])
