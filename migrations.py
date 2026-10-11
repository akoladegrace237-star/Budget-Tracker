"""Versioned, additive migration from independent summaries to a cents ledger."""
from finance import INCOME_CATEGORIES, EXPENSE_CATEGORIES, cents

def migrate(conn, postgres=False):
    conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)')
    if conn.execute('SELECT version FROM schema_migrations WHERE version=1').fetchone():
        migrate_money(conn, postgres)
        return
    for sql in [
        'ALTER TABLE transactions ADD COLUMN amount_minor BIGINT',
        "ALTER TABLE transactions ADD COLUMN source TEXT DEFAULT 'manual'",
        'ALTER TABLE transactions ADD COLUMN source_id INTEGER',
    ]:
        conn.execute(sql)
    conn.execute('CREATE TABLE account_settings (user_id INTEGER PRIMARY KEY REFERENCES users(id), '
                 'opening_cash_minor BIGINT NOT NULL DEFAULT 0, opening_date TEXT NOT NULL, setup_complete INTEGER NOT NULL DEFAULT 0)')
    conn.execute('CREATE TABLE auth_attempts (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, started BIGINT NOT NULL)')
    conn.execute('CREATE TABLE migration_notes (user_id INTEGER NOT NULL, note TEXT NOT NULL)')
    conn.execute('CREATE TABLE import_batches (token TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),payload TEXT NOT NULL,created BIGINT NOT NULL)')
    conn.execute('CREATE TABLE restore_backups (user_id INTEGER NOT NULL REFERENCES users(id),payload TEXT NOT NULL,created BIGINT NOT NULL)')
    conn.execute('CREATE TABLE bill_payments (user_id INTEGER NOT NULL REFERENCES users(id), bill_id INTEGER NOT NULL, '
                 'month TEXT NOT NULL, transaction_id INTEGER, PRIMARY KEY(user_id,bill_id,month))')
    for row in conn.execute('SELECT * FROM transactions').fetchall():
        category = 'side' if row['category'] == 'side_income' else row['category']
        conn.execute('UPDATE transactions SET amount_minor=?,category=? WHERE id=?',
                     (cents(round(row['amount'],2), signed=True), category, row['id']))
    # Retain all original tables. Add explicit adjustments only for months/categories
    # that have legacy summaries; transaction-only months remain untouched.
    for table, kind, categories in [('income', 'income', INCOME_CATEGORIES), ('expenses', 'expense', EXPENSE_CATEGORIES)]:
        available = [key for key,_ in categories if key not in ('housing','subscriptions')]
        rows = conn.execute('SELECT user_id,month,' + ','.join('SUM('+key+') AS '+key for key in available) +
                            ' FROM '+table+' GROUP BY user_id,month').fetchall()
        for row in rows:
            for key in available:
                target = cents(round(row[key] or 0, 2), signed=True)
                actual = conn.execute('SELECT COALESCE(SUM(amount_minor),0) AS total FROM transactions '
                                      'WHERE user_id=? AND type=? AND category=? AND substr(date,1,7)=?',
                                      (row['user_id'], kind, key, row['month'])).fetchone()['total']
                delta = target-actual
                if delta:
                    conn.execute('INSERT INTO transactions (user_id,date,type,category,description,amount,amount_minor,source) '
                                 'VALUES (?,?,?,?,?,?,?,?)',
                                 (row['user_id'], row['month']+'-01', kind, key,
                                  'Legacy reconciliation: '+table, delta/100, delta, 'migration'))
            conn.execute('INSERT INTO migration_notes (user_id,note) VALUES (?,?)',
                         (row['user_id'], 'Retained '+row['month']+' '+table+' totals. Review legacy reconciliation entries before changing historical data.'))
    for table, kind, categories in [('income_summary','income',INCOME_CATEGORIES), ('expense_summary','expense',EXPENSE_CATEGORIES)]:
        fields = ','.join("SUM(CASE WHEN category='"+key+"' THEN amount_minor ELSE 0 END)/100.0 AS "+key for key,_ in categories)
        conn.execute('CREATE VIEW '+table+' AS SELECT MIN(id) AS id,user_id,substr(date,1,7) AS month,'+fields+
                     " FROM transactions WHERE type='"+kind+"' GROUP BY user_id,substr(date,1,7)")
    conn.execute('CREATE INDEX transactions_user_date ON transactions(user_id,date)')
    conn.execute('CREATE INDEX recurring_user ON recurring(user_id)')
    for row in conn.execute('SELECT DISTINCT user_id FROM net_worth_history').fetchall():
        conn.execute('INSERT INTO migration_notes (user_id,note) VALUES (?,?)',
                     (row['user_id'],'Legacy net worth snapshots used the old income-minus-spending estimate. New snapshots use starting cash, portfolio and debt balances.'))
    conn.execute('INSERT INTO schema_migrations (version) VALUES (1)')
    migrate_money(conn,postgres)

MONEY_FIELDS={
    'recurring':['amount'], 'savings':['amount','investment'],
    'savings_goals':['target','saved'], 'credit_cards':['balance'], 'loans':['balance'],
    'foreign_shares':['price_per_unit'], 'budget_limits':['monthly_limit'],
    'net_worth_history':['total_income','total_expenses','total_savings','total_debt','net_worth'],
}

def migrate_money(conn,postgres):
    if conn.execute('SELECT version FROM schema_migrations WHERE version=2').fetchone(): return
    conn.execute('ALTER TABLE users ADD COLUMN credential_version INTEGER NOT NULL DEFAULT 1')
    for table,fields in MONEY_FIELDS.items():
        if postgres:
            for field in fields:
                scale=4 if field=='price_per_unit' else 2
                conn.execute('ALTER TABLE '+table+' ALTER COLUMN '+field+' TYPE NUMERIC(20,'+str(scale)+') USING ROUND('+field+'::numeric,'+str(scale)+')')
            if table=='foreign_shares': conn.execute('ALTER TABLE foreign_shares ALTER COLUMN units TYPE NUMERIC(20,6) USING ROUND(units::numeric,6)')
        else:
            # Minor-unit columns are persisted exact values. Legacy display columns
            # remain compatible with existing templates and are never used to sum cash.
            for field in fields:
                scale=4 if field=='price_per_unit' else 2
                factor=10000 if scale==4 else 100
                conn.execute('ALTER TABLE '+table+' ADD COLUMN '+field+'_minor INTEGER NOT NULL DEFAULT 0')
                conn.execute('UPDATE '+table+' SET '+field+'=ROUND('+field+','+str(scale)+')')
                conn.execute('UPDATE '+table+' SET '+field+'_minor=CAST(ROUND('+field+'*'+str(factor)+') AS INTEGER)')
            assignments=','.join(field+'_minor=CAST(ROUND(NEW.'+field+'*'+('10000' if field=='price_per_unit' else '100')+') AS INTEGER)' for field in fields)
            conn.execute('CREATE TRIGGER '+table+'_money_insert AFTER INSERT ON '+table+' BEGIN UPDATE '+table+' SET '+assignments+' WHERE id=NEW.id; END')
            conn.execute('CREATE TRIGGER '+table+'_money_update AFTER UPDATE OF '+','.join(fields)+' ON '+table+' BEGIN UPDATE '+table+' SET '+assignments+' WHERE id=NEW.id; END')
    conn.execute('INSERT INTO schema_migrations (version) VALUES (2)')
