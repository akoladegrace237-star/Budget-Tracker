"""Credential migration, recovery codes and authenticated session lifecycle."""
import secrets
from flask import Blueprint, request, session, render_template, redirect, abort, flash, current_app
from db import get_db, is_postgres
from security import hash_password, verify_password, valid_pin, throttle, normalize_credential

auth = Blueprint('auth', __name__)

@auth.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=normalize_credential(request.form.get('pin',''))
        if not 3<=len(username)<=60 or not valid_pin(password):
            return render_template('register.html',error='Use a username of 3–60 characters and a PIN of exactly 4 digits.'),400
        code=secrets.token_hex(16)
        with get_db() as conn:
            if not throttle(conn,username): abort(429,description='Too many attempts. Try again in 15 minutes.')
            if conn.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone():
                return render_template('register.html',error='Choose another username.'),400
            conn.execute('INSERT INTO users (username,password,security_answer) VALUES (?,?,?)',
                         (username,hash_password(password),hash_password(code)))
            conn.commit()
        return render_template('recovery_code.html',code=code)
    return render_template('register.html')

@auth.route('/login',methods=['GET','POST'])
def login():
    remembered=request.cookies.get('remembered_user','')
    if request.method=='POST':
        username=request.form.get('username','').strip()
        # Older cached forms used "password"; current forms retain "pin" so
        # existing PIN users and saved browser credentials continue to work.
        password=request.form.get('pin')
        if password is None:
            password=request.form.get('password','')
        password=normalize_credential(password)
        with get_db() as conn:
            if not throttle(conn,username): abort(429,description='Too many sign-in attempts. Try again in 15 minutes.')
            user=conn.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            valid=verify_password(user['password'],password) if user else verify_password(hash_password('dummy-credential'),password)
            if not user or not valid:
                current_app.logger.warning('Sign-in rejected: %s; database=%s',
                    'account not found' if not user else 'credential mismatch',
                    'PostgreSQL' if is_postgres() else 'SQLite')
                return render_template('login.html',error='Invalid username or password.',remembered_user=remembered),401
            if len(user['password'])==64:
                conn.execute('UPDATE users SET password=? WHERE id=?',(hash_password(password),user['id']))
                conn.commit()
            session.clear()
            session.update(user_id=user['id'],username=user['username'],currency=user['currency'] or '£',
                           upgrade_password=not valid_pin(password),credential_version=user['credential_version'])
            session.permanent=True
            setup=conn.execute('SELECT setup_complete FROM account_settings WHERE user_id=?',(user['id'],)).fetchone()
        response=redirect('/dashboard' if setup and setup['setup_complete'] else '/setup')
        if request.form.get('remember'):
            response.set_cookie('remembered_user',username,max_age=31536000,httponly=True,samesite='Lax',secure=request.is_secure)
        else: response.delete_cookie('remembered_user')
        return response
    return render_template('login.html',remembered_user=remembered)

@auth.route('/logout',methods=['POST'])
def logout():
    session.clear()
    response=redirect('/login')
    response.headers['Clear-Site-Data']='"cache", "storage"'
    return response

@auth.route('/forgot-pin',methods=['GET','POST'])
def recover():
    if request.method=='POST':
        username=request.form.get('username','').strip()
        code=request.form.get('security_answer','').strip().lower()
        password=normalize_credential(request.form.get('new_pin',''))
        if not valid_pin(password) or password!=normalize_credential(request.form.get('confirm_pin','')):
            return render_template('forgot_pin.html',error='Use matching PINs of exactly 4 digits.'),400
        with get_db() as conn:
            if not throttle(conn,username): abort(429,description='Too many attempts. Try again in 15 minutes.')
            user=conn.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            # Old favourite-colour answers cannot reset credentials. Existing users
            # can generate a strong recovery code after signing in.
            if not user or len(code)!=32 or len(user['security_answer'])==64 or not verify_password(user['security_answer'],code):
                return render_template('forgot_pin.html',error='Username or recovery code is incorrect.'),400
            new_code=secrets.token_hex(16)
            conn.execute('UPDATE users SET password=?,security_answer=?,credential_version=credential_version+1 WHERE id=?',
                         (hash_password(password),hash_password(new_code),user['id']))
            conn.commit()
        session.clear()
        return render_template('recovery_code.html',code=new_code)
    return render_template('forgot_pin.html')

@auth.route('/recovery-code',methods=['POST'])
def recovery_code():
    if not session.get('user_id'): return redirect('/login')
    with get_db() as conn:
        user=conn.execute('SELECT password FROM users WHERE id=?',(session['user_id'],)).fetchone()
        if not throttle(conn,session['username']): abort(429)
        if not verify_password(user['password'],request.form.get('current_password','')):
            abort(400,description='Current password is incorrect.')
        code=secrets.token_hex(16)
        conn.execute('UPDATE users SET security_answer=? WHERE id=?',(hash_password(code),session['user_id']))
        conn.commit()
    return render_template('recovery_code.html',code=code)
