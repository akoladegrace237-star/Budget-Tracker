"""Shared ledger validation and cash-flow calculations. Money is stored in cents."""
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

INCOME_CATEGORIES = [('salary', 'Salary'), ('bonus', 'Bonus'), ('side', 'Side income'),
                     ('rental', 'Rental'), ('dividends', 'Dividends'), ('gifts', 'Gifts'), ('other', 'Other')]
EXPENSE_CATEGORIES = [('housing', 'Housing'), ('utilities', 'Utilities'), ('groceries', 'Groceries'),
                      ('dining_out', 'Dining out'), ('transport', 'Transport'), ('shopping', 'Shopping'),
                      ('healthcare', 'Healthcare'), ('entertainment', 'Entertainment'),
                      ('personal_care', 'Personal care'), ('subscriptions', 'Subscriptions'), ('other', 'Other')]
TRANSFER_CATEGORIES = [('investment_purchase','Investment purchase'),('investment_sale','Investment sale')]

def today():
    return datetime.now(ZoneInfo('Europe/London')).date()

def cents(value, *, signed=False):
    try:
        amount = Decimal(str(value or '0'))
        if not amount.is_finite() or abs(amount) > Decimal('1000000000') or (not signed and amount < 0):
            raise ValueError('Enter a valid non-negative amount below 1 billion.')
        if amount != amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP):
            raise ValueError('Money amounts must have no more than two decimal places.')
        return int(amount * 100)
    except (InvalidOperation, TypeError):
        raise ValueError('Enter a valid money amount.') from None

def valid_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError('Enter a valid date.') from None

def fixed_decimal(value, places=4):
    try:
        number=Decimal(str(value or '0'))
        if not number.is_finite() or number<0 or number>1000000000 or number!=number.quantize(Decimal(1).scaleb(-places)):
            raise ValueError('Enter a non-negative number with up to '+str(places)+' decimal places.')
        return number
    except (InvalidOperation,TypeError):
        raise ValueError('Enter a valid number.') from None

def valid_month(value):
    valid_date(value + '-01')
    return value

def transaction_values(form):
    kind = form.get('type', 'expense')
    category = form.get('category', 'other')
    allowed = dict(INCOME_CATEGORIES if kind == 'income' else TRANSFER_CATEGORIES if kind=='transfer' else EXPENSE_CATEGORIES)
    if kind not in ('income', 'expense','transfer') or category not in allowed:
        raise ValueError('Choose a category for this transaction type.')
    amount = cents(form.get('amount'))
    if amount <= 0:
        raise ValueError('Amount must be greater than zero.')
    description = form.get('description', '').strip()
    if len(description) > 500:
        raise ValueError('Description must be 500 characters or fewer.')
    return valid_date(form.get('date', '')), kind, category, description, -amount if category=='investment_sale' else amount

def insert_transaction(conn, user_id, values, source='manual', source_id=None):
    day, kind, category, description, minor = values
    row=conn.execute('INSERT INTO transactions (user_id,date,type,category,description,amount,amount_minor,source,source_id) '
                 'VALUES (?,?,?,?,?,?,?,?,?) RETURNING id',
                 (user_id, day, kind, category, description, minor / 100, minor, source, source_id)).fetchone()
    return row['id']

def cash_flow(conn, user_id, month):
    rows = conn.execute('SELECT type,category,SUM(amount_minor) AS total FROM transactions '
                        'WHERE user_id=? AND substr(date,1,7)=? GROUP BY type,category', (user_id, month)).fetchall()
    spent = {key: 0 for key, _ in EXPENSE_CATEGORIES}
    income = transfers = 0
    for row in rows:
        minor=int(row['total'])
        if row['type'] == 'income':
            income += minor
        elif row['type'] == 'expense':
            spent[row['category']] = spent.get(row['category'], 0) + minor
        elif row['type'] == 'transfer':
            transfers += minor
    unpaid = sum(cents(r['amount']) for r in conn.execute(
        'SELECT amount FROM recurring WHERE user_id=? AND (last_paid_month IS NULL OR last_paid_month!=?)',
        (user_id, month)).fetchall())
    total = sum(spent.values())
    return {'income': income / 100, 'spent_by_category': {k:v/100 for k,v in spent.items()},
            'spent_total': total/100, 'unpaid_recurring': unpaid/100, 'transfers': transfers/100,
            'balance': (income-total-unpaid-transfers)/100}

def due_date(year, month, day):
    return date(year, month, min(day, monthrange(year, month)[1]))

class SafeCSVWriter:
    def __init__(self,stream):
        import csv
        self.writer=csv.writer(stream)
    def writerow(self,values):
        self.writer.writerow(["'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value for value in values])
