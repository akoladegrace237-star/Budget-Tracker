"""Guided setup, reviewed CSV import, and complete user-owned backups."""
import csv
import io
import json
import secrets
import time
from flask import Blueprint, request, session, redirect, render_template, abort, Response, flash
from db import get_db, lock_user
from finance import cents, valid_date, today, transaction_values, insert_transaction, fixed_decimal
from security import verify_password, throttle

data_tools=Blueprint('data_tools',__name__)
TABLES={
    'recurring':['name','category','amount','due_day','notes','last_paid_month'],
    'credit_cards':['name','rate','balance'], 'loans':['name','rate','balance'],
    'foreign_shares':['name','units','price_per_unit','date_bought'],
    'savings':['month','amount','investment','type','notes'],
    'savings_goals':['name','target','saved','deadline'],
    'budget_limits':['category','monthly_limit'],
    'user_profiles':['first_name','last_name','email','phone','date_of_birth','country','bio'],
    'account_settings':['opening_cash_minor','opening_date','setup_complete'],
    'transactions':['date','type','category','description','amount_minor','source','source_id'],
    'bill_payments':['bill_id','month','transaction_id'],
    'net_worth_history':['month','total_income','total_expenses','total_savings','total_debt','net_worth','health_score'],
    'migration_notes':['note'],
}

@data_tools.before_request
def require_login():
    if not session.get('user_id'): return redirect('/login')

@data_tools.route('/setup',methods=['GET','POST'])
def setup():
    if request.method=='POST':
        uid=session['user_id']
        opening=cents(request.form.get('opening_cash','0'),signed=True)
        day=valid_date(request.form.get('opening_date',today().isoformat()))
        with get_db() as conn:
            if request.method == "POST": lock_user(conn,session["user_id"])
            old=conn.execute('SELECT setup_complete FROM account_settings WHERE user_id=?',(uid,)).fetchone()
            if old and old['setup_complete']:
                # Editing the opening balance never repeats setup transactions.
                conn.execute('UPDATE account_settings SET opening_cash_minor=?,opening_date=? WHERE user_id=?',(opening,day,uid))
            else:
                conn.execute('INSERT INTO account_settings (user_id,opening_cash_minor,opening_date,setup_complete) VALUES (?,?,?,1) '
                             'ON CONFLICT(user_id) DO UPDATE SET opening_cash_minor=excluded.opening_cash_minor,opening_date=excluded.opening_date,setup_complete=1',
                             (uid,opening,day))
                income=cents(request.form.get('monthly_income'))
                if income: insert_transaction(conn,uid,(day,'income','salary','Starting month income',income),'setup')
                rent=cents(request.form.get('regular_bill'))
                if rent:
                    conn.execute('INSERT INTO recurring (user_id,name,category,amount,due_day) VALUES (?,?,?,?,?)',
                                 (uid,'Rent / mortgage','Housing',rent/100,1))
                for category in ('housing','groceries','transport','other'):
                    limit=cents(request.form.get('limit_'+category))
                    if limit:
                        conn.execute('INSERT INTO budget_limits (user_id,category,monthly_limit) VALUES (?,?,?) '
                                     'ON CONFLICT(user_id,category) DO UPDATE SET monthly_limit=excluded.monthly_limit',(uid,category,limit/100))
            conn.commit()
        flash('Your starting balance and budget are ready.','success')
        return redirect('/dashboard')
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        settings=conn.execute('SELECT * FROM account_settings WHERE user_id=?',(session['user_id'],)).fetchone()
        count=conn.execute('SELECT COUNT(*) AS n FROM transactions WHERE user_id=?',(session['user_id'],)).fetchone()['n']
    return render_template('setup.html',settings=settings,has_history=count>0,today=today().replace(day=1).isoformat())

def fingerprint(row):
    return (row['date'],row['type'],row['category'],row.get('description','').strip(),int(row['amount_minor']))

@data_tools.route('/import',methods=['GET','POST'])
def import_csv():
    if request.method=='GET': return render_template('import.html')
    upload=request.files.get('file')
    if not upload: abort(400,description='Choose a CSV file.')
    try:
        reader=csv.DictReader(io.StringIO(upload.read().decode('utf-8-sig')))
        required={'date','type','category','amount'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError('CSV needs date, type, category and amount columns. Description is optional.')
        rows=[]
        for index,raw in enumerate(reader,2):
            if index>10001: raise ValueError('Import up to 10,000 rows at a time.')
            try: day,kind,category,description,minor=transaction_values(raw)
            except ValueError as exc: raise ValueError(f'Row {index}: {exc}') from None
            rows.append(dict(date=day,type=kind,category=category,description=description,amount_minor=minor))
        if not rows: raise ValueError('The CSV is empty.')
    except (UnicodeDecodeError,csv.Error,ValueError) as exc:
        return render_template('import.html',error=str(exc)),400
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        existing={fingerprint(dict(r)) for r in conn.execute('SELECT * FROM transactions WHERE user_id=?',(session['user_id'],)).fetchall()}
        accepted=[]; duplicates=0
        for row in rows:
            key=fingerprint(row)
            if key in existing: duplicates+=1
            else: accepted.append(row); existing.add(key)
        token=secrets.token_urlsafe(24)
        conn.execute('DELETE FROM import_batches WHERE created<?',(int(time.time())-3600,))
        conn.execute('INSERT INTO import_batches (token,user_id,payload,created) VALUES (?,?,?,?)',
                     (token,session['user_id'],json.dumps(accepted),int(time.time())))
        conn.commit()
    return render_template('import.html',rows=accepted[:50],count=len(accepted),duplicates=duplicates,token=token)

@data_tools.route('/import/confirm',methods=['POST'])
def confirm_import():
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        batch=conn.execute('SELECT * FROM import_batches WHERE token=? AND user_id=?',
                          (request.form.get('token'),session['user_id'])).fetchone()
        if not batch or int(time.time())-batch['created']>3600: abort(400,description='Import preview expired. Upload the file again.')
        existing={fingerprint(dict(r)) for r in conn.execute('SELECT * FROM transactions WHERE user_id=?',(session['user_id'],)).fetchall()}
        count=0
        for row in json.loads(batch['payload']):
            if fingerprint(row) not in existing:
                insert_transaction(conn,session['user_id'],(row['date'],row['type'],row['category'],row['description'],row['amount_minor']),'import')
                existing.add(fingerprint(row)); count+=1
        conn.execute('DELETE FROM import_batches WHERE token=?',(batch['token'],))
        conn.commit()
    flash(f'Imported {count} transactions. Duplicate rows were skipped.','success')
    return redirect('/transactions')

@data_tools.route('/export/transactions')
def export_transactions():
    stream=io.StringIO(); writer=csv.writer(stream)
    writer.writerow(['date','type','category','description','amount'])
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        for row in conn.execute("SELECT * FROM transactions WHERE user_id=? AND source!='migration' AND (type IN ('income','expense') "
                                "OR category IN ('investment_purchase','investment_sale')) ORDER BY date,id",(session['user_id'],)).fetchall():
            description=row['description'] or ''
            # Spreadsheet formula protection; JSON backup preserves text exactly.
            if description.startswith(('=','+','-','@','\t','\r')): description="'"+description
            writer.writerow([row['date'],row['type'],row['category'],description,f"{abs(row['amount_minor'])/100:.2f}"])
    return Response(stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=transactions.csv'})

@data_tools.route('/backup')
def backup():
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        tables={table:[dict(r) for r in conn.execute('SELECT * FROM '+table+' WHERE user_id=?',(session['user_id'],)).fetchall()] for table in TABLES}
        currency=conn.execute('SELECT currency FROM users WHERE id=?',(session['user_id'],)).fetchone()['currency']
    payload=dict(format='budget-tracker',version=1,currency=currency,tables=tables)
    return Response(json.dumps(payload,default=str,indent=2),mimetype='application/json',
                    headers={'Content-Disposition':'attachment; filename=budget-backup.json'})

def validate_backup(payload):
    if not isinstance(payload,dict): raise ValueError('Choose a JSON backup object.')
    if payload.get('format')!='budget-tracker' or payload.get('version')!=1:
        raise ValueError('Choose a Budget Tracker version 1 backup.')
    tables=payload.get('tables')
    if not isinstance(tables,dict) or set(tables)!=set(TABLES): raise ValueError('Backup sections are incomplete.')
    if payload.get('currency') not in ('£','$','€','₦','₹','A$','C$','¥','CHF','R','kr','zł','₩'): raise ValueError('Invalid currency.')
    money={'amount','investment','target','saved','balance','monthly_limit','total_income','total_expenses','total_savings','total_debt','net_worth'}
    from decimal import Decimal
    for table,fields in TABLES.items():
        if not isinstance(tables[table],list) or len(tables[table])>20000: raise ValueError('Invalid or oversized backup section.')
        seen=set()
        for row in tables[table]:
            if not isinstance(row,dict) or not set(fields).issubset(row): raise ValueError('A backup row is incomplete.')
            if table not in ('account_settings','bill_payments','migration_notes'):
                identity=row.get('id')
                if not isinstance(identity,int) or identity in seen: raise ValueError('Duplicate or invalid record ID.')
                seen.add(identity)
            for key in fields:
                value=row[key]
                if isinstance(value,str) and len(value)>2000: raise ValueError('A backup field is too long.')
                if key in money: cents(value,signed=key in ('net_worth','total_income','total_expenses','total_savings'))
                if key=='price_per_unit': fixed_decimal(value,4)
                if key in ('date','opening_date') or (key in ('deadline','date_bought','date_of_birth') and value): valid_date(value)
                if key=='month': valid_date(value+'-01')
                if key=='due_day' and (not isinstance(value,int) or not 1<=value<=31): raise ValueError('Invalid bill due day.')
                if key in ('amount_minor','opening_cash_minor') and (not isinstance(value,int) or abs(value)>100000000000): raise ValueError('Invalid minor-unit amount.')
                if key in ('units','rate'):
                    number=Decimal(str(value))
                    if not number.is_finite() or number<0 or number>1000000000: raise ValueError('Invalid numeric field.')
            if table=='transactions':
                if row['type'] not in ('income','expense','transfer') or row['source'] not in ('manual','bulk','setup','import','migration','bill','debt'):
                    raise ValueError('Invalid transaction type or source.')
                if row['type']=='transfer' and row['category'] not in ('investment_purchase','investment_sale','credit_payment','loan_payment'):
                    raise ValueError('Invalid transfer category.')
                if row['source']!='migration' and row['amount_minor']<=0 and row['category']!='investment_sale':
                    raise ValueError('Invalid transaction amount.')
    for table in ('account_settings','user_profiles'):
        if len(tables[table])>1: raise ValueError('Duplicate settings or profile.')
    references={table:{r['id'] for r in tables[table]} for table in ('recurring','credit_cards','loans','transactions')}
    for row in tables['transactions']:
        if row['source']=='bill' and row['source_id'] is not None and row['source_id'] not in references['recurring']:
            # A deleted bill leaves its paid transaction in the ledger. Preserve
            # the financial event and detach only its inactive source reference.
            row['source_id']=None
        if row['source']=='debt':
            table='credit_cards' if row['category']=='credit_payment' else 'loans'
            if row['source_id'] not in references[table]: row['source_id']=None
    for row in tables['bill_payments']:
        if row['bill_id'] not in references['recurring'] or (row['transaction_id'] is not None and row['transaction_id'] not in references['transactions']):
            raise ValueError('A payment references a missing bill or transaction.')
    return tables

@data_tools.errorhandler(ValueError)
def invalid_data(error):
    from werkzeug.exceptions import BadRequest
    return render_template('error.html',error=BadRequest(description=str(error))),400

@data_tools.route('/restore',methods=['GET','POST'])
def restore():
    if request.method=='GET': return render_template('restore.html')
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        if not throttle(conn,session['username']): abort(429)
        user=conn.execute('SELECT password FROM users WHERE id=?',(session['user_id'],)).fetchone()
        if not verify_password(user['password'],request.form.get('current_password','')): abort(400,description='Current password is incorrect.')
    upload=request.files.get('file')
    if not upload: abort(400,description='Choose a backup file.')
    try:
        payload=json.loads(upload.read()); tables=validate_backup(payload)
    except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
        return render_template('restore.html',error=str(exc)),400
    if request.form.get('confirm')!='replace': abort(400,description='Confirm replacement of your data.')
    uid=session['user_id']
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        # Restore is atomic; all old financial records are saved in a safety backup
        # inside the same database before any replacement is attempted.
        old={table:[dict(r) for r in conn.execute('SELECT * FROM '+table+' WHERE user_id=?',(uid,)).fetchall()] for table in TABLES}
        old_currency=conn.execute('SELECT currency FROM users WHERE id=?',(uid,)).fetchone()['currency']
        conn.execute('INSERT INTO restore_backups (user_id,payload,created) VALUES (?,?,?)',
                     (uid,json.dumps(dict(format='budget-tracker',version=1,currency=old_currency,tables=old),default=str),int(time.time())))
        for table in reversed(TABLES): conn.execute('DELETE FROM '+table+' WHERE user_id=?',(uid,))
        mappings={}
        for table,fields in TABLES.items():
            mappings[table]={}
            for original in tables[table]:
                row={field:original[field] for field in fields}
                if table=='transactions':
                    row['amount']=row['amount_minor']/100
                    if row['source']=='bill': row['source_id']=mappings['recurring'].get(row['source_id'])
                    elif row['source']=='debt':
                        debt_table='credit_cards' if row['category']=='credit_payment' else 'loans'
                        row['source_id']=mappings[debt_table].get(row['source_id'])
                if table=='bill_payments':
                    row['bill_id']=mappings['recurring'].get(row['bill_id'])
                    row['transaction_id']=mappings['transactions'].get(row['transaction_id'])
                    if row['bill_id'] is None: raise ValueError('Payment references a missing bill.')
                columns=['user_id']+list(row)
                sql='INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')'
                if original.get('id') is not None: sql+=' RETURNING id'
                cursor=conn.execute(sql,[uid]+list(row.values()))
                if original.get('id') is not None:
                    new=cursor.fetchone()['id']
                    mappings[table][original['id']]=new
        conn.execute('UPDATE users SET currency=? WHERE id=?',(payload['currency'],uid))
        conn.commit()
    session['currency']=payload['currency']
    flash('Backup restored. A safety copy of your previous data is available in Settings.','success')
    return redirect('/dashboard')

@data_tools.route('/backup/previous')
def previous_backup():
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        row=conn.execute('SELECT payload FROM restore_backups WHERE user_id=? ORDER BY created DESC LIMIT 1',(session['user_id'],)).fetchone()
    if not row: abort(404,description='No restore safety backup is available yet.')
    return Response(row['payload'],mimetype='application/json',headers={'Content-Disposition':'attachment; filename=before-restore.json'})
