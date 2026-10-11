"""Dashboard and monthly charts derived from the ledger and opening balance."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, session, redirect, render_template, jsonify, request
from db import get_db, lock_user
from finance import cash_flow, cents, today, due_date, EXPENSE_CATEGORIES

reports=Blueprint('reports',__name__)

@reports.before_request
def require_login():
    if not session.get('user_id'): return redirect('/login')

@reports.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@reports.route('/api/dashboard-data')
def dashboard_data():
    uid=session['user_id']; now=today(); month=now.strftime('%Y-%m')
    previous=(now.replace(day=1)-timedelta(days=1)).strftime('%Y-%m')
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        rows=conn.execute('SELECT type,category,SUM(amount_minor) AS total FROM transactions WHERE user_id=? GROUP BY type,category',(uid,)).fetchall()
        income=sum(int(r['total']) for r in rows if r['type']=='income')
        expenses=sum(int(r['total']) for r in rows if r['type']=='expense')
        settings=conn.execute('SELECT * FROM account_settings WHERE user_id=?',(uid,)).fetchone()
        opening=settings['opening_cash_minor'] if settings else 0
        opening_date=settings['opening_date'] if settings else '0001-01-01'
        movement=int(conn.execute("SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount_minor ELSE -amount_minor END),0) AS total "
                              'FROM transactions WHERE user_id=? AND date>=?',(uid,opening_date)).fetchone()['total'])
        cash=opening+movement
        cards=conn.execute('SELECT balance FROM credit_cards WHERE user_id=?',(uid,)).fetchall()
        loans=conn.execute('SELECT balance FROM loans WHERE user_id=?',(uid,)).fetchall()
        debt=sum(cents(r['balance']) for r in cards+loans)
        holdings=conn.execute('SELECT units,price_per_unit FROM foreign_shares WHERE user_id=?',(uid,)).fetchall()
        portfolio=sum(int((Decimal(str(r['units']))*Decimal(str(r['price_per_unit']))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) for r in holdings)
        savings=conn.execute('SELECT amount,investment FROM savings WHERE user_id=?',(uid,)).fetchall()
        earmarked=sum(cents(r['amount']) for r in savings)
        invested=sum(cents(r['investment']) for r in savings)
        cur=cash_flow(conn,uid,month); prev=cash_flow(conn,uid,previous)
        limits={r['category']:cents(r['monthly_limit']) for r in conn.execute('SELECT * FROM budget_limits WHERE user_id=?',(uid,)).fetchall()}
        comparison=[]
        for key,label in EXPENSE_CATEGORIES:
            limit=limits.get(key,0)/100; spent=cur['spent_by_category'].get(key,0)
            pct=round(spent/limit*100,1) if limit else None
            comparison.append(dict(key=key,label=label,limit=limit,spent=spent,pct=pct,
                                   status='no-limit' if pct is None else 'over' if pct>=100 else 'warning' if pct>=70 else 'ok'))
        # Score describes tracked monthly cash flow and budget adherence, not financial advice.
        rate=cur['balance']/cur['income'] if cur['income']>0 else 0
        limited=[c for c in comparison if c['limit']]
        adherence=sum(c['spent']<=c['limit'] for c in limited)/len(limited) if limited else 0
        score=round(max(0,min(1,rate))*60+adherence*40)
        goals=[dict(name=r['name'],target=cents(r['target'])/100,saved=cents(r['saved'])/100,deadline=r['deadline']) for r in conn.execute('SELECT name,target,saved,deadline FROM savings_goals WHERE user_id=?',(uid,)).fetchall()]
        bills=[]; alerts=[]
        for bill in conn.execute('SELECT * FROM recurring WHERE user_id=? ORDER BY due_day',(uid,)).fetchall():
            due=due_date(now.year,now.month,bill['due_day']); paid=bill['last_paid_month']==month
            diff=(due-now).days
            item=dict(id=bill['id'],name=bill['name'],category=bill['category'],amount=cents(bill['amount'])/100,
                      due_day=bill['due_day'],paid=paid,due_date=due.isoformat(),days_until=diff)
            bills.append(item)
            if not paid and diff<=5: alerts.append(item)
        months=conn.execute("SELECT substr(date,1,7) AS month,SUM(CASE WHEN type='income' THEN amount_minor ELSE 0 END)/100.0 AS income, "
                            "SUM(CASE WHEN type='expense' THEN amount_minor ELSE 0 END)/100.0 AS expense "
                            'FROM transactions WHERE user_id=? GROUP BY substr(date,1,7) ORDER BY month DESC LIMIT 6',(uid,)).fetchall()[::-1]
        history=[dict(r) for r in conn.execute('SELECT month,net_worth FROM net_worth_history WHERE user_id=? ORDER BY month',(uid,)).fetchall()]
        notes=[r['note'] for r in conn.execute('SELECT note FROM migration_notes WHERE user_id=?',(uid,)).fetchall()]
    net_worth=cash+portfolio-debt
    return jsonify(username=session['username'],setup_complete=bool(settings and settings['setup_complete']),
        income_by_month=[dict(month=r['month'],total=float(r['income'])) for r in months],
        expense_by_month=[dict(month=r['month'],total=float(r['expense'])) for r in months],
        expense_breakdown={r['category']:int(r['total'])/100 for r in rows if r['type']=='expense'},
        savings_goals=goals,upcoming_bills=bills,bill_alerts=alerts,health_score=score,budget_comparison=comparison,
        cash_flow_forecast=dict(income=cur['income'],spent=cur['spent_total'],recurring=cur['unpaid_recurring'],balance=cur['balance']),
        current_month=dict(month=month,income=cur['income'],expense=cur['spent_total'],balance=cur['balance']),
        prev_month=dict(month=previous,income=prev['income'],expense=prev['spent_total']),
        totals=dict(income=income/100,expenses=expenses/100,savings=earmarked/100,investments=invested/100,
                    debt=debt/100,net_savings=(income-expenses)/100,savings_rate=round(rate*100,1),net_worth=net_worth/100,
                    portfolio=portfolio/100,cash=cash/100),net_worth_history=history,migration_notes=notes)

@reports.route('/projections')
def projections():
    uid=session['user_id']
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        rows=conn.execute("SELECT substr(date,1,7) AS month,SUM(CASE WHEN type='income' THEN amount_minor ELSE 0 END)/100.0 AS income, "
                          "SUM(CASE WHEN type='expense' THEN amount_minor ELSE 0 END)/100.0 AS expense FROM transactions "
                          'WHERE user_id=? GROUP BY substr(date,1,7) ORDER BY month DESC LIMIT 6',(uid,)).fetchall()[::-1]
        history=conn.execute('SELECT month,net_worth FROM net_worth_history WHERE user_id=? ORDER BY month',(uid,)).fetchall()
        bills=sum(cents(r['amount']) for r in conn.execute('SELECT amount FROM recurring WHERE user_id=?',(uid,)).fetchall())/100
        variable=conn.execute("SELECT substr(date,1,7) AS month,SUM(CASE WHEN type='expense' AND source!='bill' THEN amount_minor ELSE 0 END)/100.0 AS expense "
                              'FROM transactions WHERE user_id=? GROUP BY substr(date,1,7) ORDER BY month DESC LIMIT 6',(uid,)).fetchall()
    income=[float(r['income']) for r in rows]; expense=[float(r['expense']) for r in rows]
    avg_income=sum(income)/len(income) if income else 0
    avg_expense=(sum(float(r['expense']) for r in variable)/len(variable) if variable else 0)+bills
    now=today(); forecasts=[]
    for i in range(1,13):
        index=now.year*12+now.month-1+i
        forecasts.append(dict(month=f'{index//12:04d}-{index%12+1:02d}',income=avg_income,expenses=avg_expense,
                              net=avg_income-avg_expense))
    return render_template('projections.html',income_labels=[r['month'] for r in rows],income_values=income,
                           expense_labels=[r['month'] for r in rows],expense_values=expense,
                           nw_labels=[r['month'] for r in history],nw_values=[r['net_worth'] for r in history],forecasts=forecasts)

@reports.route('/snapshot',methods=['POST'])
def snapshot():
    data=dashboard_data().get_json(); totals=data['totals']; month=today().strftime('%Y-%m')
    with get_db() as conn:
        if request.method == "POST": lock_user(conn,session["user_id"])
        conn.execute('INSERT INTO net_worth_history (user_id,month,total_income,total_expenses,total_savings,total_debt,net_worth,health_score) '
                     'VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(user_id,month) DO UPDATE SET net_worth=excluded.net_worth,health_score=excluded.health_score',
                     (session['user_id'],month,totals['income'],totals['expenses'],totals['savings'],totals['debt'],totals['net_worth'],data['health_score']))
        conn.commit()
    return redirect('/dashboard')
