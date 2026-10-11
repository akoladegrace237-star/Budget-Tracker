"""Read-only source database review: migrate a consistent SQLite copy only."""
import hashlib
import os
import sqlite3
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
os.environ.pop('DATABASE_URL',None)
import db
from finance import INCOME_CATEGORIES,EXPENSE_CATEGORIES

original=ROOT/'database.db'
before=hashlib.sha256(original.read_bytes()).digest()
copy=ROOT/'.qa'/('migration-review-'+uuid.uuid4().hex+'.db')
source=sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)
target=sqlite3.connect(str(copy))
try: source.backup(target)
finally: source.close();target.close()
db.DB_PATH=copy
db.init_db();db.init_db()
checked=0
with db.get_db() as conn:
    for table,kind,categories in [('income','income',INCOME_CATEGORIES),('expenses','expense',EXPENSE_CATEGORIES)]:
        available=[key for key,_ in categories if key not in ('housing','subscriptions')]
        rows=conn.execute('SELECT user_id,month,'+','.join('SUM('+key+') AS '+key for key in available)+' FROM '+table+' GROUP BY user_id,month').fetchall()
        for row in rows:
            for key in available:
                ledger=conn.execute('SELECT COALESCE(SUM(amount_minor),0) AS total FROM transactions WHERE user_id=? AND type=? AND category=? AND substr(date,1,7)=?',
                                    (row['user_id'],kind,key,row['month'])).fetchone()['total']
                assert ledger==round((row[key] or 0)*100),(table,key)
                checked+=1
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not conn.execute('PRAGMA foreign_key_check').fetchall()
assert hashlib.sha256(original.read_bytes()).digest()==before
print(f'Migration copy passed: {checked} category/month totals reconciled; original database unchanged.')
