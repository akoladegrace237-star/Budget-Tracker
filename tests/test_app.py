import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

QA_DIR=Path(__file__).resolve().parent.parent/'.qa'
QA_DIR.mkdir(exist_ok=True)

class WorkspaceTemp:
    """Default Windows ACLs; tempfile's mode=0700 conflicts with managed execution."""
    def __init__(self):
        import uuid
        self.path=QA_DIR/('test-'+uuid.uuid4().hex)
        self.path.mkdir()
        self.name=str(self.path)
    def cleanup(self):
        import shutil
        if self.path.resolve().parent != QA_DIR.resolve(): raise RuntimeError('Unsafe cleanup path')
        shutil.rmtree(self.path)
    def __enter__(self): return self.name
    def __exit__(self,*args): self.cleanup()

os.environ['SECRET_KEY']='test-only-secret-key-with-more-than-32-characters'
os.environ.pop('DATABASE_URL',None)
os.environ.pop('RAILWAY_ENVIRONMENT',None)
os.environ['APP_ENV']='test'
os.environ['BUDGET_DB_PATH']=str(Path(tempfile.gettempdir())/'unused-budget-test.db')
import app as application
import db
from finance import cents, today
from security import hash_password, verify_password

class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.folder=WorkspaceTemp()
        db.DB_PATH=Path(self.folder.name)/'test.db'
        application._db_ready=False
        application.app.config.update(TESTING=True)
        self.client=application.app.test_client()
        self.client.get('/login')
        with db.get_db() as conn:
            conn.execute('INSERT INTO users (username,password,security_answer) VALUES (?,?,?)',
                         ('tester',hash_password('secure-test-password'),hash_password('a'*32)))
            conn.execute('INSERT INTO account_settings VALUES (1,100000,?,1)',(today().replace(day=1).isoformat(),))
            conn.commit()
        with self.client.session_transaction() as s:
            s.update(user_id=1,username='tester',currency='£',csrf_token='test-csrf')
    def tearDown(self): self.folder.cleanup()
    def post(self,path,**data):
        data['csrf_token']='test-csrf'
        return self.client.post(path,data=data)
    def transaction(self,amount='25.20',kind='expense',category='groceries',day=None,description='Shop'):
        response=self.post('/transactions/add',amount=amount,type=kind,category=category,
                           date=day or today().isoformat(),description=description)
        self.assertEqual(response.status_code,302)
        with db.get_db() as conn:
            return conn.execute('SELECT MAX(id) AS id FROM transactions').fetchone()['id']
    def data(self):
        response=self.client.get('/api/dashboard-data')
        self.assertEqual(response.status_code,200)
        return response.get_json()
    def test_add_edit_delete_updates_every_summary(self):
        identity=self.transaction()
        self.assertEqual(self.data()['current_month']['expense'],25.2)
        self.assertIn('25.20',self.client.get('/expenses').get_data(as_text=True))
        self.post(f'/transactions/edit/{identity}',amount='30.10',type='expense',category='housing',date=today().isoformat(),description='Rent')
        data=self.data(); self.assertEqual(data['current_month']['expense'],30.1)
        self.assertEqual(next(c for c in data['budget_comparison'] if c['key']=='housing')['spent'],30.1)
        self.post(f'/transactions/delete/{identity}')
        self.assertEqual(self.data()['current_month']['expense'],0)
    def test_income_and_negative_cash_flow_are_preserved(self):
        self.transaction('100','income','salary'); self.transaction('150')
        data=self.data(); self.assertEqual(data['current_month']['balance'],-50)
        self.assertEqual(data['totals']['net_worth'],950)
        self.assertEqual(data['totals']['net_savings'],-50)
    def test_bill_payment_is_idempotent_and_reversible(self):
        self.post('/recurring/add',name='Rent',category='Housing',amount='500',due_day='1')
        self.assertEqual(self.data()['cash_flow_forecast']['balance'],-500)
        self.post('/recurring/mark-paid/1'); self.post('/recurring/mark-paid/1')
        data=self.data(); self.assertEqual(data['current_month']['expense'],500)
        self.assertEqual(data['cash_flow_forecast']['balance'],-500)
        self.assertEqual(data['expense_breakdown']['housing'],500)
        with db.get_db() as conn: identity=conn.execute('SELECT id FROM transactions').fetchone()['id']
        self.post(f'/transactions/delete/{identity}')
        self.assertFalse(self.data()['upcoming_bills'][0]['paid'])
        self.assertEqual(self.data()['current_month']['expense'],0)
    def test_debt_payment_reduces_cash_and_debt_without_changing_net_worth(self):
        self.post('/credit/add',name='Card',rate='20',balance='300')
        before=self.data()['totals']['net_worth']
        self.post('/credit/pay',card_id='1',amount='100')
        data=self.data(); self.assertEqual(data['totals']['net_worth'],before)
        self.assertEqual(data['totals']['cash'],900); self.assertEqual(data['totals']['debt'],200)
        self.assertEqual(self.post('/credit/pay',card_id='1',amount='201').status_code,400)
        with db.get_db() as conn: identity=conn.execute('SELECT id FROM transactions').fetchone()['id']
        self.post(f'/transactions/delete/{identity}')
        self.assertEqual(self.data()['totals']['cash'],1000); self.assertEqual(self.data()['totals']['debt'],300)
    def test_csrf_and_get_mutations(self):
        self.assertEqual(self.client.post('/transactions/add',data={}).status_code,400)
        self.assertEqual(self.client.get('/transactions/delete/1').status_code,405)
        self.assertEqual(self.client.get('/recurring/mark-paid/1').status_code,405)
        self.assertEqual(self.client.get('/logout').status_code,405)
    def test_invalid_money_and_categories(self):
        for amount in ['-1','NaN','Infinity','0.001','bad','1000000001']:
            response=self.post('/transactions/add',amount=amount,type='expense',category='groceries',date=today().isoformat())
            self.assertEqual(response.status_code,400,amount)
        self.assertEqual(self.post('/recurring/add',name='Bill',category='Other',amount='20',due_day='32').status_code,400)
        self.assertEqual(self.post('/transactions/add',amount='1',type='income',category='housing',date=today().isoformat()).status_code,400)
    def test_user_isolation(self):
        identity=self.transaction()
        with db.get_db() as conn:
            conn.execute('INSERT INTO users (username,password) VALUES (?,?)',('other',hash_password('other-password'))); conn.commit()
        with self.client.session_transaction() as s: s.update(user_id=2,username='other')
        self.assertEqual(self.post(f'/transactions/delete/{identity}').status_code,404)
        self.assertEqual(self.post(f'/transactions/edit/{identity}',amount='10',type='expense',category='other',date=today().isoformat()).status_code,404)
        self.assertEqual(self.data()['totals']['expenses'],0)
    def test_latest_months_and_aligned_projection(self):
        for m in range(1,9): self.transaction('10','income','salary',f'2026-{m:02d}-01')
        self.transaction('5','expense','groceries','2026-08-01')
        months=self.data()['income_by_month']
        self.assertEqual([r['month'] for r in months],['2026-03','2026-04','2026-05','2026-06','2026-07','2026-08'])
        html=self.client.get('/projections').get_data(as_text=True)
        self.assertIn('12-month forecast',html)
    def test_import_preview_duplicate_detection_and_confirmation(self):
        self.transaction('25.20',description='Shop')
        csv=f'date,type,category,description,amount\n{today()},expense,groceries,Shop,25.20\n{today()},income,salary,Pay,100\n'
        response=self.post('/import',file=(io.BytesIO(csv.encode()),'test.csv'))
        self.assertEqual(response.status_code,200)
        self.assertIn('1 matching rows skipped',response.get_data(as_text=True))
        self.assertEqual(self.data()['totals']['income'],0)
        with db.get_db() as conn: token=conn.execute('SELECT token FROM import_batches').fetchone()['token']
        self.assertEqual(self.post('/import/confirm',token=token).status_code,302)
        self.assertEqual(self.data()['totals']['income'],100)
        self.assertEqual(self.post('/import/confirm',token=token).status_code,400)
    def test_backup_roundtrip_with_linked_payments_and_safety_copy(self):
        self.post('/recurring/add',name='Rent',category='Housing',amount='200',due_day='1')
        self.post('/recurring/mark-paid/1')
        self.post('/credit/add',name='Card',rate='20',balance='300')
        self.post('/credit/pay',card_id='1',amount='50')
        before=self.data(); backup=self.client.get('/backup').data
        self.transaction('10')
        response=self.post('/restore',file=(io.BytesIO(backup),'backup.json'),current_password='secure-test-password',confirm='replace')
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        after=self.data(); self.assertEqual(before['totals'],after['totals'])
        self.assertEqual(self.client.get('/backup/previous').status_code,200)
        with db.get_db() as conn:
            payment=conn.execute("SELECT * FROM transactions WHERE source='bill'").fetchone()
            bill=conn.execute('SELECT id FROM recurring').fetchone()['id']
            self.assertEqual(payment['source_id'],bill)
        self.post(f"/transactions/delete/{payment['id']}")
        self.assertFalse(self.data()['upcoming_bills'][0]['paid'])
    def test_bad_backup_leaves_data_unchanged(self):
        self.transaction()
        response=self.post('/restore',file=(io.BytesIO(b'{"version":1}'),'bad.json'),current_password='secure-test-password',confirm='replace')
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.data()['totals']['expenses'],25.2)
    def test_old_pin_upgrades_hash_and_prompts_password_change(self):
        with db.get_db() as conn:
            conn.execute('UPDATE users SET password=? WHERE id=1',(hashlib.sha256(b'1234').hexdigest(),)); conn.commit()
        response=self.post('/login',username='tester',pin='1234')
        self.assertEqual(response.status_code,302)
        with db.get_db() as conn:
            value=conn.execute('SELECT password FROM users').fetchone()['password']
        self.assertTrue(value.startswith('scrypt:')); self.assertTrue(verify_password(value,'1234'))
        with self.client.session_transaction() as s: self.assertTrue(s['upgrade_password'])
    def test_throttle_is_persistent(self):
        for i in range(10):
            self.assertEqual(self.post('/login',username='tester',pin='wrong').status_code,401)
        self.assertEqual(self.post('/login',username='tester',pin='secure-test-password').status_code,429)
    def test_all_pages_render_and_private_pages_are_not_cached(self):
        for path in ['/dashboard','/income','/expenses','/transactions','/recurring','/budgets','/savings','/debt','/projections','/shares','/settings','/setup','/import','/restore']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
    def test_exact_minor_units(self):
        self.transaction('0.10'); self.transaction('0.20')
        self.assertEqual(self.data()['totals']['expenses'],0.3)
        with db.get_db() as conn: self.assertEqual(conn.execute('SELECT SUM(amount_minor) AS n FROM transactions').fetchone()['n'],30)

    def test_investment_transfers_do_not_count_as_spending(self):
        self.transaction('100','transfer','investment_purchase')
        self.post('/shares/add',name='Holding',units='2',price_per_unit='50',date_bought=today().isoformat())
        data=self.data(); self.assertEqual(data['totals']['cash'],900)
        self.assertEqual(data['totals']['net_worth'],1000)
        self.assertEqual(data['totals']['expenses'],0)
        self.transaction('20','transfer','investment_sale')
        self.assertEqual(self.data()['totals']['cash'],920)

    def test_password_change_accepts_old_pin_and_invalidates_other_sessions(self):
        with db.get_db() as conn:
            conn.execute('UPDATE users SET password=? WHERE id=1',(hash_password('1234'),)); conn.commit()
        other=application.app.test_client()
        with other.session_transaction() as s: s.update(user_id=1,username='tester',credential_version=1)
        response=self.post('/settings',action='password',current_password='1234',new_password='new-long-password',confirm_password='new-long-password')
        self.assertEqual(response.status_code,302)
        self.assertEqual(other.get('/dashboard').status_code,302)
        self.assertEqual(self.client.get('/dashboard').status_code,200)

    def test_recovery_code_rotates_and_old_security_answer_cannot_reset(self):
        response=self.post('/forgot-pin',username='tester',security_answer='a'*32,new_pin='new-test-password',confirm_pin='new-test-password')
        self.assertEqual(response.status_code,200)
        code=re.search(r'<code class="recovery-code">([^<]+)</code>',response.get_data(as_text=True))[1]
        self.assertEqual(len(code),32)
        with db.get_db() as conn:
            user=conn.execute('SELECT * FROM users WHERE id=1').fetchone()
            self.assertTrue(verify_password(user['password'],'new-test-password'))
            self.assertTrue(verify_password(user['security_answer'],code))

    def test_forecast_includes_known_unpaid_bills(self):
        self.transaction('1000','income','salary')
        self.transaction('50')
        self.post('/recurring/add',name='Rent',category='Housing',amount='200',due_day='1')
        html=self.client.get('/projections').get_data(as_text=True)
        self.assertIn('250.00',html)

    def test_decimal_debt_reversal_stays_exact(self):
        self.post('/credit/add',name='Tiny',rate='0',balance='0.30')
        self.post('/credit/pay',card_id='1',amount='0.10')
        with db.get_db() as conn: identity=conn.execute('SELECT id FROM transactions').fetchone()['id']
        self.post(f'/transactions/delete/{identity}')
        self.assertEqual(self.data()['totals']['debt'],0.3)

    def test_backup_after_bill_deletion_is_restorable(self):
        self.post('/recurring/add',name='Bill',category='Other',amount='10',due_day='1')
        self.post('/recurring/mark-paid/1'); self.post('/recurring/delete/1')
        backup=self.client.get('/backup').data
        response=self.post('/restore',file=(io.BytesIO(backup),'backup.json'),current_password='secure-test-password',confirm='replace')
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))

    def test_concurrent_bill_payment_counts_once(self):
        self.post('/recurring/add',name='Rent',category='Housing',amount='50',due_day='1')
        from concurrent.futures import ThreadPoolExecutor
        def pay(_):
            client=application.app.test_client()
            with client.session_transaction() as s: s.update(user_id=1,username='tester',csrf_token='test-csrf')
            return client.post('/recurring/mark-paid/1',data={'csrf_token':'test-csrf'}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool: statuses=list(pool.map(pay,range(4)))
        self.assertEqual(statuses,[302]*4)
        self.assertEqual(self.data()['totals']['expenses'],50)

    def test_dashboard_reads_do_not_create_snapshots(self):
        self.data();self.data()
        with db.get_db() as conn: self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM net_worth_history').fetchone()['n'],0)
        self.post('/snapshot');self.post('/snapshot')
        with db.get_db() as conn: self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM net_worth_history').fetchone()['n'],1)

    def test_fractional_unit_price_survives_backup(self):
        self.post('/shares/add',name='Fractional',units='10',price_per_unit='42.1250')
        self.assertEqual(self.data()['totals']['portfolio'],421.25)
        backup=self.client.get('/backup').data
        self.assertEqual(self.post('/restore',file=(io.BytesIO(backup),'backup.json'),current_password='secure-test-password',confirm='replace').status_code,302)
        self.assertEqual(self.data()['totals']['portfolio'],421.25)

    def test_new_credentials_and_recovery_reject_weak_values(self):
        response=self.post('/register',username='weak-account',pin='1234')
        self.assertEqual(response.status_code,400)
        with db.get_db() as conn:
            conn.execute('UPDATE users SET security_answer=? WHERE id=1',(hashlib.sha256(b'blue').hexdigest(),));conn.commit()
        response=self.post('/forgot-pin',username='tester',security_answer='blue',new_pin='a-new-long-password',confirm_pin='a-new-long-password')
        self.assertEqual(response.status_code,400)

    def test_expense_export_includes_housing_and_subscriptions(self):
        self.transaction('50',category='housing');self.transaction('10',category='subscriptions')
        csv=self.client.get('/export/expenses').get_data(as_text=True)
        self.assertIn('Housing',csv);self.assertIn('Subscriptions',csv);self.assertIn('60.0',csv)

    def test_reports_accept_postgres_numeric_result_types(self):
        from decimal import Decimal
        from unittest.mock import patch
        import reporting
        self.transaction('1000','income','salary');self.transaction('50')
        self.post('/recurring/add',name='Rent',category='Housing',amount='200',due_day='1')
        class Cursor:
            def __init__(self,cursor): self.cursor=cursor
            def convert(self,row):
                if row is None: return None
                return {key:Decimal(str(row[key])) if isinstance(row[key],float) or key=='total' else row[key] for key in row.keys()}
            def fetchone(self): return self.convert(self.cursor.fetchone())
            def fetchall(self): return [self.convert(row) for row in self.cursor.fetchall()]
        class Connection:
            def __init__(self): self.conn=db.get_db()
            def execute(self,*args): return Cursor(self.conn.execute(*args))
            def __enter__(self): return self
            def __exit__(self,*args): self.conn.__exit__(*args)
        with patch.object(reporting,'get_db',Connection):
            data=self.data()
            self.assertEqual(data['current_month']['balance'],750)
            self.assertIsInstance(data['totals']['cash'],float)
            self.assertEqual(self.client.get('/projections').status_code,200)

class MigrationTests(unittest.TestCase):
    def test_legacy_summary_reconciliation_is_once_and_retains_originals(self):
        with WorkspaceTemp() as folder:
            db.DB_PATH=Path(folder)/'legacy.db'
            conn=sqlite3.connect(str(db.DB_PATH)); conn.row_factory=sqlite3.Row
            db._init_sqlite(conn.cursor())
            conn.execute("INSERT INTO users (username,password) VALUES ('old','hash')")
            conn.execute("INSERT INTO income (user_id,month,salary) VALUES (1,'2026-01',100)")
            conn.execute("INSERT INTO expenses (user_id,month,groceries) VALUES (1,'2026-01',30)")
            conn.execute("INSERT INTO transactions (user_id,date,type,category,description,amount) VALUES (1,'2026-01-01','expense','groceries','Shop',10)")
            conn.commit(); conn.close()
            db.init_db(); db.init_db()
            with db.get_db() as conn:
                self.assertEqual(conn.execute('SELECT SUM(amount_minor) AS n FROM transactions WHERE type=\'expense\'').fetchone()['n'],3000)
                self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM expenses').fetchone()['n'],1)
                self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM transactions').fetchone()['n'],3)
            self.assertTrue(list((Path(folder)/'backups').glob('*.db')))

if __name__=='__main__': unittest.main()
