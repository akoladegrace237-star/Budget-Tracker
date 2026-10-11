"""All transaction writes and monthly summaries use the same cents ledger."""
from flask import Blueprint, request, session, redirect, render_template, flash, abort, jsonify
from db import get_db, lock_user
from finance import (EXPENSE_CATEGORIES, INCOME_CATEGORIES, TRANSFER_CATEGORIES, cents, today, valid_month,
                     transaction_values, insert_transaction)

ledger = Blueprint('ledger', __name__)

@ledger.before_request
def require_login():
    if not session.get('user_id'):
        return redirect('/login')

@ledger.route('/transactions')
def transactions():
    month = request.args.get('month','')
    kind = request.args.get('type','')
    search = request.args.get('q','').strip()[:100]
    query = 'SELECT * FROM transactions WHERE user_id=?'
    params = [session['user_id']]
    if month:
        try: valid_month(month)
        except ValueError: abort(400)
        query += ' AND substr(date,1,7)=?'; params.append(month)
    if kind:
        if kind not in ('income','expense','transfer'): abort(400)
        query += ' AND type=?'; params.append(kind)
    if search:
        query += ' AND LOWER(description) LIKE ?'; params.append('%'+search.lower()+'%')
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        records = conn.execute(query+' ORDER BY date DESC,id DESC', params).fetchall()
        months = [r['month'] for r in conn.execute('SELECT DISTINCT substr(date,1,7) AS month FROM transactions '
                  'WHERE user_id=? ORDER BY month DESC',(session['user_id'],)).fetchall()]
    return render_template('transactions.html', records=records, months=months, filter_month=month,
                           filter_type=kind, search=search, categories=EXPENSE_CATEGORIES+INCOME_CATEGORIES,
                           income_categories=INCOME_CATEGORIES, expense_categories=EXPENSE_CATEGORIES,
                           transfer_categories=TRANSFER_CATEGORIES,
                           total_in=sum(r['amount_minor'] for r in records if r['type']=='income')/100,
                           total_out=sum(r['amount_minor'] for r in records if r['type']=='expense')/100)

@ledger.route('/transactions/add', methods=['POST'])
def add_transaction():
    try: values = transaction_values(request.form)
    except ValueError as exc: abort(400, description=str(exc))
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        insert_transaction(conn,session['user_id'],values)
        conn.commit()
    flash('Transaction saved. Your summaries and budgets have been updated.','success')
    return redirect('/transactions')

@ledger.route('/transactions/edit/<int:record_id>', methods=['POST'])
def edit_transaction(record_id):
    try: values = transaction_values(request.form)
    except ValueError as exc: abort(400, description=str(exc))
    day,kind,category,description,minor = values
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        row = conn.execute('SELECT * FROM transactions WHERE id=? AND user_id=?',(record_id,session['user_id'])).fetchone()
        if not row: abort(404)
        if row['source'] in ('bill','debt','migration'):
            abort(400, description='This is a linked payment or legacy adjustment. Delete it to reverse it, then add a corrected transaction.')
        conn.execute('UPDATE transactions SET date=?,type=?,category=?,description=?,amount=?,amount_minor=? WHERE id=? AND user_id=?',
                     (day,kind,category,description,minor/100,minor,record_id,session['user_id']))
        conn.commit()
    flash('Transaction updated.','success')
    return redirect('/transactions')

@ledger.route('/transactions/delete/<int:record_id>', methods=['POST'])
def delete_transaction(record_id):
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        row = conn.execute('SELECT * FROM transactions WHERE id=? AND user_id=?',(record_id,session['user_id'])).fetchone()
        if not row: abort(404)
        if row['source']=='bill':
            conn.execute('DELETE FROM bill_payments WHERE user_id=? AND transaction_id=?',(session['user_id'],record_id))
            month = row['date'][:7]
            conn.execute('UPDATE recurring SET last_paid_month=NULL WHERE id=? AND user_id=? AND last_paid_month=?',
                         (row['source_id'],session['user_id'],month))
        if row['source']=='debt':
            table = 'credit_cards' if row['category']=='credit_payment' else 'loans'
            debt=conn.execute('SELECT balance FROM '+table+' WHERE id=? AND user_id=?',
                              (row['source_id'],session['user_id'])).fetchone()
            if debt:
                restored=(cents(debt['balance'])+row['amount_minor'])/100
                conn.execute('UPDATE '+table+' SET balance=? WHERE id=? AND user_id=?',
                             (restored,row['source_id'],session['user_id']))
        conn.execute('DELETE FROM transactions WHERE id=? AND user_id=?',(record_id,session['user_id']))
        conn.commit()
    flash('Transaction deleted and linked payment reversed.','success')
    return redirect('/transactions')

@ledger.route('/income')
@ledger.route('/expenses')
def monthly_summary():
    kind = 'income' if request.path=='/income' else 'expense'
    categories = INCOME_CATEGORIES if kind=='income' else EXPENSE_CATEGORIES
    month = request.args.get('month',today().strftime('%Y-%m'))
    try: valid_month(month)
    except ValueError: abort(400)
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        rows = conn.execute('SELECT category,SUM(amount_minor) AS total,COUNT(*) AS count FROM transactions '
                            'WHERE user_id=? AND type=? AND substr(date,1,7)=? GROUP BY category',
                            (session['user_id'],kind,month)).fetchall()
    amounts = {r['category']:r['total']/100 for r in rows}
    return render_template('monthly_summary.html', kind=kind, categories=categories, amounts=amounts,
                           total=sum(r['total'] for r in rows)/100, month=month)

@ledger.route('/income/add',methods=['POST'])
@ledger.route('/expenses/add',methods=['POST'])
def bulk_add():
    kind = 'income' if request.path.startswith('/income') else 'expense'
    categories = INCOME_CATEGORIES if kind=='income' else EXPENSE_CATEGORIES
    month = valid_month(request.form.get('month',today().strftime('%Y-%m')))
    day = today().isoformat() if month==today().strftime('%Y-%m') else month+'-01'
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        for key,label in categories:
            amount = cents(request.form.get(key))
            if amount:
                insert_transaction(conn,session['user_id'],(day,kind,key,label,amount),'bulk')
        conn.commit()
    return redirect('/income' if kind=='income' else '/expenses')

@ledger.route('/expenses/quick-add',methods=['POST'])
def quick_add():
    form = dict(request.form)
    month = valid_month(form.get('month',today().strftime('%Y-%m')))
    form.update(type='expense', date=today().isoformat() if month==today().strftime('%Y-%m') else month+'-01',
                description=form.get('note',''))
    try: values = transaction_values(form)
    except ValueError as exc: abort(400, description=str(exc))
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        insert_transaction(conn,session['user_id'],values)
        conn.commit()
    return redirect('/expenses')

@ledger.route('/recurring/mark-paid/<int:record_id>',methods=['POST'])
def pay_bill(record_id):
    user_id = session['user_id']; month = today().strftime('%Y-%m')
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        # Atomic insert of a unique bill/month key makes repeat and concurrent requests harmless.
        from db import is_postgres
        sql='SELECT * FROM recurring WHERE id=? AND user_id=?'
        if is_postgres(): sql+=' FOR UPDATE'
        bill = conn.execute(sql,(record_id,user_id)).fetchone()
        if not bill: abort(404)
        conn.execute('INSERT INTO bill_payments (user_id,bill_id,month) VALUES (?,?,?) ON CONFLICT DO NOTHING',
                     (user_id,record_id,month))
        payment = conn.execute('SELECT transaction_id FROM bill_payments WHERE user_id=? AND bill_id=? AND month=?',
                               (user_id,record_id,month)).fetchone()
        if payment['transaction_id'] is None and bill['last_paid_month']!=month:
            mapping = {'Housing':'housing','Utilities':'utilities','Transport':'transport','Healthcare':'healthcare',
                       'Entertainment':'entertainment','Subscriptions':'subscriptions','Insurance':'other','Other':'other'}
            transaction=insert_transaction(conn,user_id,(today().isoformat(),'expense',mapping.get(bill['category'],'other'),
                                           'Bill: '+bill['name'],cents(bill['amount'])),'bill',record_id)
            conn.execute('UPDATE bill_payments SET transaction_id=? WHERE user_id=? AND bill_id=? AND month=?',
                         (transaction,user_id,record_id,month))
            conn.execute('UPDATE recurring SET last_paid_month=? WHERE id=? AND user_id=?',(month,record_id,user_id))
        conn.commit()
    if request.headers.get('Accept')=='application/json': return jsonify(ok=True)
    return redirect('/recurring')

@ledger.route('/credit/pay',methods=['POST'])
@ledger.route('/loans/pay',methods=['POST'])
def pay_debt():
    table = 'credit_cards' if request.path.startswith('/credit') else 'loans'
    field = 'card_id' if table=='credit_cards' else 'loan_id'
    category = 'credit_payment' if table=='credit_cards' else 'loan_payment'
    amount = cents(request.form.get('amount'))
    if amount <= 0: abort(400,description='Payment must be greater than zero.')
    try: record_id=int(request.form.get(field,''))
    except ValueError: abort(400)
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        sql = 'SELECT * FROM '+table+' WHERE id=? AND user_id=?'
        from db import is_postgres
        if is_postgres(): sql += ' FOR UPDATE'
        row = conn.execute(sql,(record_id,session['user_id'])).fetchone()
        if not row: abort(404)
        balance = cents(row['balance'])
        if amount>balance: abort(400,description='Payment cannot exceed the outstanding balance.')
        conn.execute('UPDATE '+table+' SET balance=? WHERE id=? AND user_id=?',((balance-amount)/100,record_id,session['user_id']))
        insert_transaction(conn,session['user_id'],(today().isoformat(),'transfer',category,'Debt payment: '+row['name'],amount),'debt',record_id)
        conn.commit()
    return redirect('/debt')
