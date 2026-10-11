"""Session, credential and form protection shared by all routes."""
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from flask import abort, request, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from finance import cents, valid_date, valid_month, fixed_decimal

def normalize_credential(value):
    stripped=value.strip()
    return stripped if stripped.isdigit() and len(stripped)==4 else value

def hash_password(value):
    return generate_password_hash(normalize_credential(value), method='scrypt')

def verify_password(stored, value):
    # Legacy registration/login stripped PIN whitespace. Retain that behaviour
    # after the same four-digit credential is upgraded to a salted hash, while
    # preserving intentional whitespace in modern passwords.
    value=normalize_credential(value)
    if len(stored) == 64 and ':' not in stored:
        return hmac.compare_digest(stored, hashlib.sha256(value.encode()).hexdigest())
    return check_password_hash(stored, value)

def strong_password(value):
    return 12 <= len(value) <= 128

def configure(app):
    secret = os.environ.get('SECRET_KEY')
    production = bool(os.environ.get('DATABASE_URL') or os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('APP_ENV') == 'production')
    if production and (not secret or len(secret) < 32):
        raise RuntimeError('Production requires SECRET_KEY with at least 32 characters.')
    if not secret:
        key_path = Path(app.root_path) / '.local-secret'
        if not key_path.exists():
            try:
                with key_path.open('x') as f:
                    f.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        secret = key_path.read_text().strip()
    app.config.update(SECRET_KEY=secret, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=production,
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=5*1024*1024)

    def csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        return session['csrf_token']
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def protect_forms():
        if request.path.startswith(('/static/','/icons/')) or request.path in ('/styles.css','/sw.js'):
            return
        if session.get('user_id'):
            from db import get_db
            with get_db() as conn:
                user=conn.execute('SELECT credential_version FROM users WHERE id=?',(session['user_id'],)).fetchone()
            if not user or user['credential_version']!=session.get('credential_version',1):
                session.clear()
                from flask import redirect
                return redirect('/login')
        if request.method in ('POST','PUT','PATCH','DELETE'):
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            expected = session.get('csrf_token','')
            if not expected or not hmac.compare_digest(supplied, expected):
                abort(400, description='Your form has expired. Reload the page and try again.')
            for key, value in request.form.items():
                if len(value) > 2000:
                    abort(400, description='A field is too long.')
                try:
                    if key in ('amount','salary','bonus','side','rental','dividends','gifts','other','utilities','groceries',
                               'dining_out','transport','shopping','healthcare','entertainment','personal_care','housing',
                               'subscriptions','investment','target','saved','balance','monthly_income','regular_bill') or key.startswith('limit_'):
                        cents(value)
                    if key=='opening_cash': cents(value,signed=True)
                    if key in ('month',) and value:
                        valid_month(value)
                    if key=='month' and not value:
                        raise ValueError('Choose a month.')
                    if key in ('date','date_bought','deadline','date_of_birth','opening_date') and value:
                        valid_date(value)
                    if key == 'due_day' and not 1 <= int(value) <= 31:
                        raise ValueError('Bill due day must be between 1 and 31.')
                    if key in ('rate','units') and value:
                        number = fixed_decimal(value,6 if key=='units' else 4)
                        if key=='rate' and number>1000: raise ValueError('APR must be 1000% or less.')
                    if key=='price_per_unit': fixed_decimal(value,4)
                    if key == 'currency' and value not in ('£','$','€','₦','₹','A$','C$','¥','CHF','R','kr','zł','₩'):
                        raise ValueError('Choose a supported currency.')
                except (ValueError, ArithmeticError):
                    abort(400, description='Check '+key.replace('_',' ')+': enter a valid value.')
            if request.path.startswith(('/recurring/add','/recurring/edit')):
                if not request.form.get('name','').strip() or request.form.get('category') not in (
                    'Housing','Utilities','Transport','Healthcare','Entertainment','Subscriptions','Insurance','Other'):
                    abort(400,description='Enter a bill name and choose a supported category.')
            if request.path.startswith(('/credit/add','/credit/edit','/loans/add','/loans/edit','/shares/add','/shares/edit','/savings/goal/')) and '/delete/' not in request.path:
                if not request.form.get('name','').strip(): abort(400,description='Enter a name for this record.')

    @app.after_request
    def secure_response(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        if not request.path.startswith(('/static/','/icons/')) and request.path != '/styles.css':
            response.headers['Cache-Control'] = 'no-store'
        return response

def throttle(conn, username):
    """Shared DB-backed limits across workers; count every authentication attempt."""
    now = int(time.time())
    keys = ['account:'+username.casefold(), 'ip:'+(request.remote_addr or 'unknown')]
    for key in keys:
        row = conn.execute('SELECT * FROM auth_attempts WHERE key=?', (key,)).fetchone()
        limit = 10 if key.startswith('account:') else 40
        if row and now-row['started'] < 900 and row['attempts'] >= limit:
            return False
    for key in keys:
        conn.execute('INSERT INTO auth_attempts (key,attempts,started) VALUES (?,1,?) '
                     'ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN auth_attempts.started<? THEN 1 ELSE auth_attempts.attempts+1 END, '
                     'started=CASE WHEN auth_attempts.started<? THEN excluded.started ELSE auth_attempts.started END',
                     (key, now, now-900, now-900))
    conn.commit()
    return True
