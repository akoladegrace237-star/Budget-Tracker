from flask import Flask, render_template, request, redirect, session, jsonify, send_from_directory, Response
import hashlib
import os
import csv
import io
from datetime import datetime
from db import get_db, init_db, is_postgres

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "budget-tracker-secret-key-change-this")

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────
# GLOBALS
# ─────────────────────────────────────────────

CURRENCIES = [
    ("£",   "£ — British Pound (GBP)"),
    ("$",   "$ — US Dollar (USD)"),
    ("€",   "€ — Euro (EUR)"),
    ("₦",   "₦ — Nigerian Naira (NGN)"),
    ("₹",  "₹ — Indian Rupee (INR)"),
    ("A$",  "A$ — Australian Dollar (AUD)"),
    ("C$",  "C$ — Canadian Dollar (CAD)"),
    ("¥",   "¥ — Japanese Yen (JPY)"),
    ("CHF", "CHF — Swiss Franc"),
    ("R",   "R — South African Rand (ZAR)"),
    ("kr",  "kr — Swedish/Norwegian Krone"),
    ("zł",  "zł — Polish Złoty"),
    ("₩",  "₩ — South Korean Won"),
]


@app.context_processor
def inject_globals():
    """Make currency (and other globals) available in every template."""
    return {'currency': session.get('currency', '£')}


# Lazy DB init — retry if startup init_db() failed (e.g. DNS not ready yet)
_db_ready = False

@app.before_request
def ensure_db():
    global _db_ready
    if not _db_ready:
        try:
            init_db()
            _db_ready = True
        except Exception:
            pass  # Will try again on next request


# Serve root-level static assets (original styles.css, icons/, etc.)
@app.route('/styles.css')
def serve_root_css():
    return send_from_directory(ROOT_DIR, 'styles.css', mimetype='text/css')

@app.route('/icons/<path:filename>')
def serve_icons(filename):
    return send_from_directory(os.path.join(ROOT_DIR, 'icons'), filename)

@app.route('/sw.js')
def serve_sw():
    return send_from_directory(os.path.join(ROOT_DIR, 'static'), 'sw.js',
                               mimetype='application/javascript')


def form_float(key, default=0.0):
    """Safely convert a form field to float, returning default for empty/missing values."""
    val = request.form.get(key, "")
    try:
        return float(val) if val.strip() else default
    except (ValueError, TypeError):
        return default


def form_int(key, default=0):
    """Safely convert a form field to int, returning default for empty/missing values."""
    val = request.form.get(key, "")
    try:
        return int(val) if val.strip() else default
    except (ValueError, TypeError):
        return default


# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────

def hash_password(password):
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def get_user_id():
    """Get the currently logged-in user's ID from session."""
    return session.get("user_id")


def login_required(f):
    """Decorator to protect routes that need login."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_user_id():
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    if get_user_id():
        return redirect("/dashboard")
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username        = request.form["username"].strip()
        pin             = request.form["pin"].strip()
        security_answer = request.form.get("security_answer", "").strip().lower()

        if not username or not pin:
            return render_template("register.html", error="All fields are required.")
        if not pin.isdigit() or len(pin) != 4:
            return render_template("register.html", error="PIN must be exactly 4 digits.")
        if not security_answer:
            return render_template("register.html", error="Security answer is required for PIN recovery.")

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (username, password, security_answer) VALUES (?, ?, ?)",
                (username, hash_password(pin), hash_password(security_answer))
            )
            conn.commit()
            return redirect("/login")
        except Exception:
            return render_template("register.html", error="Username already taken.")
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        pin      = request.form["pin"].strip()
        remember = request.form.get("remember")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password = ?",
            (username, hash_password(pin))
        ).fetchone()
        conn.close()

        if user:
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["currency"] = user["currency"] or "£"
            resp = redirect("/dashboard")
            if remember:
                resp.set_cookie("remembered_user", username, max_age=60*60*24*365)
            else:
                resp.delete_cookie("remembered_user")
            return resp
        else:
            return render_template("login.html", error="Invalid username or PIN.",
                                   remembered_user=request.cookies.get("remembered_user", ""))

    return render_template("login.html",
                           remembered_user=request.cookies.get("remembered_user", ""))


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/forgot-pin", methods=["GET", "POST"])
def forgot_pin():
    if request.method == "POST":
        username        = request.form["username"].strip()
        security_answer = request.form["security_answer"].strip().lower()
        new_pin         = request.form["new_pin"].strip()
        confirm_pin     = request.form["confirm_pin"].strip()

        if not (new_pin.isdigit() and len(new_pin) == 4):
            return render_template("forgot_pin.html", error="PIN must be exactly 4 digits.")
        if new_pin != confirm_pin:
            return render_template("forgot_pin.html", error="PINs do not match.")

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user or user["security_answer"] != hash_password(security_answer):
            conn.close()
            return render_template("forgot_pin.html", error="Username or security answer is incorrect.")

        conn.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(new_pin), user["id"]))
        conn.commit()
        conn.close()
        return redirect("/login")

    return render_template("forgot_pin.html")


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = get_user_id()
    conn    = get_db()

    # Total income (all time)
    total_income = conn.execute(
        "SELECT COALESCE(SUM(salary+bonus+side+rental+dividends+gifts+other),0) FROM income WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    # Total expenses (all time)
    total_expenses = conn.execute(
        "SELECT COALESCE(SUM(utilities+groceries+dining_out+transport+shopping+healthcare+entertainment+personal_care+other),0) FROM expenses WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    # Total savings
    total_savings = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM savings WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    # Total investments
    total_investments = conn.execute(
        "SELECT COALESCE(SUM(investment),0) FROM savings WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    # Total debt (credit + loans)
    total_credit = conn.execute(
        "SELECT COALESCE(SUM(balance),0) FROM credit_cards WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]
    total_loans = conn.execute(
        "SELECT COALESCE(SUM(balance),0) FROM loans WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]
    total_debt = total_credit + total_loans

    # Upcoming recurring bills
    upcoming_bills = conn.execute(
        "SELECT * FROM recurring WHERE user_id=? ORDER BY due_day ASC LIMIT 5",
        (user_id,)
    ).fetchall()

    conn.close()

    return render_template("dashboard.html",
        username          = session["username"],
        total_income      = total_income,
        total_expenses    = total_expenses,
        total_savings     = total_savings,
        total_investments = total_investments,
        total_debt        = total_debt,
        net_savings       = total_savings - total_investments,
        savings_rate      = round((total_savings / total_income * 100), 1) if total_income > 0 else 0,
        upcoming_bills    = upcoming_bills,
    )


# ─────────────────────────────────────────────
# INCOME ROUTES
# ─────────────────────────────────────────────

@app.route("/income")
@login_required
def income():
    user_id = get_user_id()
    conn    = get_db()
    records = conn.execute(
        "SELECT * FROM income WHERE user_id=? ORDER BY month DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return render_template("income.html", records=records)


@app.route("/income/add", methods=["POST"])
@login_required
def add_income():
    user_id = get_user_id()
    month   = request.form.get("month", datetime.now().strftime("%Y-%m"))

    conn = get_db()
    conn.execute('''
        INSERT INTO income (user_id, month, salary, bonus, side, rental, dividends, gifts, other)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, month,
        form_float("salary"),
        form_float("bonus"),
        form_float("side"),
        form_float("rental"),
        form_float("dividends"),
        form_float("gifts"),
        form_float("other"),
    ))
    conn.commit()
    conn.close()
    return redirect("/income")


@app.route("/income/delete/<int:record_id>")
@login_required
def delete_income(record_id):
    conn = get_db()
    conn.execute("DELETE FROM income WHERE id=? AND user_id=?", (record_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/income")


# ─────────────────────────────────────────────
# EXPENSES ROUTES
# ─────────────────────────────────────────────

@app.route("/expenses")
@login_required
def expenses():
    user_id   = get_user_id()
    cur_month = datetime.now().strftime("%Y-%m")
    conn      = get_db()
    records   = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? ORDER BY month DESC",
        (user_id,)
    ).fetchall()

    # Budget mini-summary for current month
    limits_raw = conn.execute(
        "SELECT category, monthly_limit FROM budget_limits WHERE user_id=?",
        (user_id,)
    ).fetchall()
    limits_map = {r["category"]: r["monthly_limit"] for r in limits_raw}

    cur_exp = conn.execute(
        "SELECT SUM(utilities) as utilities, SUM(groceries) as groceries, "
        "SUM(dining_out) as dining_out, SUM(transport) as transport, "
        "SUM(shopping) as shopping, SUM(healthcare) as healthcare, "
        "SUM(entertainment) as entertainment, SUM(personal_care) as personal_care, "
        "SUM(other) as other FROM expenses WHERE user_id=? AND month=?",
        (user_id, cur_month)
    ).fetchone()

    budget_summary = []
    any_limit = any(v > 0 for v in limits_map.values())
    if any_limit:
        for key, label in EXPENSE_CATEGORIES:
            limit = limits_map.get(key, 0.0)
            if limit <= 0:
                continue
            s   = (cur_exp[key] or 0.0) if cur_exp else 0.0
            pct = round(s / limit * 100, 1) if limit > 0 else None
            if pct is None:
                status = "no-limit"
            elif pct >= 100:
                status = "over"
            elif pct >= 70:
                status = "warning"
            else:
                status = "ok"
            budget_summary.append({
                "key": key, "label": label,
                "limit": limit, "spent": round(s, 2),
                "pct": pct, "status": status,
            })

    conn.close()
    return render_template("expenses.html", records=records,
                           budget_summary=budget_summary, cur_month=cur_month)


@app.route("/expenses/add", methods=["POST"])
@login_required
def add_expense():
    user_id = get_user_id()
    month   = request.form.get("month", datetime.now().strftime("%Y-%m"))

    conn = get_db()
    conn.execute('''
        INSERT INTO expenses (user_id, month, utilities, groceries, dining_out, transport, shopping, healthcare, entertainment, personal_care, other)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, month,
        form_float("utilities"),
        form_float("groceries"),
        form_float("dining_out"),
        form_float("transport"),
        form_float("shopping"),
        form_float("healthcare"),
        form_float("entertainment"),
        form_float("personal_care"),
        form_float("other"),
    ))
    conn.commit()
    conn.close()
    return redirect("/expenses")


@app.route("/expenses/delete/<int:record_id>")
@login_required
def delete_expense(record_id):
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (record_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/expenses")


# ─────────────────────────────────────────────
# RECURRING PAYMENTS ROUTES
# ─────────────────────────────────────────────

@app.route("/recurring")
@login_required
def recurring():
    user_id = get_user_id()
    conn    = get_db()
    records = conn.execute(
        "SELECT * FROM recurring WHERE user_id=? ORDER BY due_day ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return render_template("recurring.html", records=records)


@app.route("/recurring/add", methods=["POST"])
@login_required
def add_recurring():
    user_id = get_user_id()
    conn    = get_db()
    conn.execute('''
        INSERT INTO recurring (user_id, name, category, amount, due_day, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        request.form["name"],
        request.form["category"],
        form_float("amount"),
        form_int("due_day"),
        request.form.get("notes", ""),
    ))
    conn.commit()
    conn.close()
    return redirect("/recurring")


@app.route("/recurring/delete/<int:record_id>")
@login_required
def delete_recurring(record_id):
    conn = get_db()
    conn.execute("DELETE FROM recurring WHERE id=? AND user_id=?", (record_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/recurring")


# ─────────────────────────────────────────────
# SAVINGS ROUTES
# ─────────────────────────────────────────────

@app.route("/savings")
@login_required
def savings():
    user_id = get_user_id()
    conn    = get_db()
    records = conn.execute(
        "SELECT * FROM savings WHERE user_id=? ORDER BY month DESC",
        (user_id,)
    ).fetchall()
    goals = conn.execute(
        "SELECT * FROM savings_goals WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()
    return render_template("savings.html", records=records, goals=goals)


@app.route("/savings/add", methods=["POST"])
@login_required
def add_savings():
    user_id = get_user_id()
    conn    = get_db()
    conn.execute('''
        INSERT INTO savings (user_id, month, amount, investment, type, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        request.form.get("month", datetime.now().strftime("%Y-%m")),
        form_float("amount"),
        form_float("investment"),
        request.form.get("type", ""),
        request.form.get("notes", ""),
    ))
    conn.commit()
    conn.close()
    return redirect("/savings")


@app.route("/savings/goal/add", methods=["POST"])
@login_required
def add_savings_goal():
    user_id = get_user_id()
    conn    = get_db()
    conn.execute('''
        INSERT INTO savings_goals (user_id, name, target, saved, deadline)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        user_id,
        request.form["name"],
        form_float("target"),
        form_float("saved"),
        request.form.get("deadline", ""),
    ))
    conn.commit()
    conn.close()
    return redirect("/savings")


# ─────────────────────────────────────────────
# CREDIT CARDS ROUTES
# ─────────────────────────────────────────────

@app.route("/credit")
@login_required
def credit():
    user_id = get_user_id()
    conn    = get_db()
    cards   = conn.execute(
        "SELECT * FROM credit_cards WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()
    return render_template("credit.html", cards=cards)


@app.route("/credit/add", methods=["POST"])
@login_required
def add_credit():
    user_id = get_user_id()
    conn    = get_db()
    conn.execute('''
        INSERT INTO credit_cards (user_id, name, rate, balance)
        VALUES (?, ?, ?, ?)
    ''', (
        user_id,
        request.form["name"],
        form_float("rate"),
        form_float("balance"),
    ))
    conn.commit()
    conn.close()
    return redirect("/credit")


@app.route("/credit/pay", methods=["POST"])
@login_required
def pay_credit():
    card_id = form_int("card_id")
    amount  = form_float("amount")
    user_id = get_user_id()
    conn    = get_db()
    conn.execute(
        "UPDATE credit_cards SET balance = MAX(0, balance - ?) WHERE id=? AND user_id=?",
        (amount, card_id, user_id)
    )
    conn.commit()
    conn.close()
    return redirect("/credit")


@app.route("/credit/delete/<int:card_id>")
@login_required
def delete_credit(card_id):
    conn = get_db()
    conn.execute("DELETE FROM credit_cards WHERE id=? AND user_id=?", (card_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/credit")


# ─────────────────────────────────────────────
# LOANS ROUTES
# ─────────────────────────────────────────────

@app.route("/loans")
@login_required
def loans():
    user_id   = get_user_id()
    conn      = get_db()
    loan_list = conn.execute(
        "SELECT * FROM loans WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()
    return render_template("loans.html", loans=loan_list)


@app.route("/loans/add", methods=["POST"])
@login_required
def add_loan():
    user_id = get_user_id()
    conn    = get_db()
    conn.execute('''
        INSERT INTO loans (user_id, name, rate, balance)
        VALUES (?, ?, ?, ?)
    ''', (
        user_id,
        request.form["name"],
        form_float("rate"),
        form_float("balance"),
    ))
    conn.commit()
    conn.close()
    return redirect("/loans")


@app.route("/loans/pay", methods=["POST"])
@login_required
def pay_loan():
    loan_id = form_int("loan_id")
    amount  = form_float("amount")
    user_id = get_user_id()
    conn    = get_db()
    conn.execute(
        "UPDATE loans SET balance = MAX(0, balance - ?) WHERE id=? AND user_id=?",
        (amount, loan_id, user_id)
    )
    conn.commit()
    conn.close()
    return redirect("/loans")


@app.route("/loans/delete/<int:loan_id>")
@login_required
def delete_loan(loan_id):
    conn = get_db()
    conn.execute("DELETE FROM loans WHERE id=? AND user_id=?", (loan_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/loans")


# ─────────────────────────────────────────────
# PROJECTIONS ROUTE
# ─────────────────────────────────────────────

@app.route("/projections")
@login_required
def projections():
    user_id = get_user_id()
    conn    = get_db()

    income_data = conn.execute(
        "SELECT month, SUM(salary+bonus+side+rental+dividends+gifts+other) as total FROM income WHERE user_id=? GROUP BY month ORDER BY month DESC LIMIT 6",
        (user_id,)
    ).fetchall()

    expense_data = conn.execute(
        "SELECT month, SUM(utilities+groceries+dining_out+transport+shopping+healthcare+entertainment+personal_care+other) as total FROM expenses WHERE user_id=? GROUP BY month ORDER BY month DESC LIMIT 6",
        (user_id,)
    ).fetchall()

    conn.close()

    income_labels  = [r["month"] for r in income_data]
    income_values  = [r["total"] for r in income_data]
    expense_labels = [r["month"] for r in expense_data]
    expense_values = [r["total"] for r in expense_data]

    return render_template("projections.html",
        income_labels  = income_labels,
        income_values  = income_values,
        expense_labels = expense_labels,
        expense_values = expense_values,
    )


# ─────────────────────────────────────────────
# FOREIGN SHARES ROUTES
# ─────────────────────────────────────────────

@app.route("/shares")
@login_required
def shares():
    user_id     = get_user_id()
    conn        = get_db()
    investments = conn.execute(
        "SELECT * FROM foreign_shares WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()
    return render_template("shares.html", investments=investments)


@app.route("/shares/add", methods=["POST"])
@login_required
def add_share():
    user_id = get_user_id()
    conn    = get_db()
    conn.execute('''
        INSERT INTO foreign_shares (user_id, name, units, price_per_unit, date_bought)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        user_id,
        request.form["name"],
        form_float("units"),
        form_float("price_per_unit"),
        request.form.get("date_bought", ""),
    ))
    conn.commit()
    conn.close()
    return redirect("/shares")


@app.route("/shares/delete/<int:share_id>")
@login_required
def delete_share(share_id):
    conn = get_db()
    conn.execute("DELETE FROM foreign_shares WHERE id=? AND user_id=?", (share_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/shares")


# ─────────────────────────────────────────────
# BUDGET LIMITS ROUTES
# ─────────────────────────────────────────────

EXPENSE_CATEGORIES = [
    ("utilities",     "Utilities"),
    ("groceries",     "Groceries"),
    ("dining_out",    "Dining Out"),
    ("transport",     "Transport"),
    ("shopping",      "Shopping"),
    ("healthcare",    "Healthcare"),
    ("entertainment", "Entertainment"),
    ("personal_care", "Personal Care"),
    ("other",         "Other"),
]


@app.route("/budgets")
@login_required
def budgets():
    user_id   = get_user_id()
    cur_month = datetime.now().strftime("%Y-%m")
    conn      = get_db()

    # Load existing limits
    limits_raw = conn.execute(
        "SELECT category, monthly_limit FROM budget_limits WHERE user_id=?",
        (user_id,)
    ).fetchall()
    limits = {r["category"]: r["monthly_limit"] for r in limits_raw}

    # Current month spending per category
    exp_row = conn.execute(
        "SELECT utilities, groceries, dining_out, transport, shopping, "
        "healthcare, entertainment, personal_care, other "
        "FROM expenses WHERE user_id=? AND month=?",
        (user_id, cur_month)
    ).fetchone()

    # Aggregate if multiple rows exist for same month
    if exp_row is None:
        spent = {cat: 0.0 for cat, _ in EXPENSE_CATEGORIES}
    else:
        # Sum all rows for current month
        rows = conn.execute(
            "SELECT SUM(utilities) as utilities, SUM(groceries) as groceries, "
            "SUM(dining_out) as dining_out, SUM(transport) as transport, "
            "SUM(shopping) as shopping, SUM(healthcare) as healthcare, "
            "SUM(entertainment) as entertainment, SUM(personal_care) as personal_care, "
            "SUM(other) as other FROM expenses WHERE user_id=? AND month=?",
            (user_id, cur_month)
        ).fetchone()
        spent = {cat: (rows[cat] or 0.0) for cat, _ in EXPENSE_CATEGORIES}

    # Build comparison list
    comparison = []
    for key, label in EXPENSE_CATEGORIES:
        limit = limits.get(key, 0.0)
        amount_spent = spent.get(key, 0.0)
        pct = round(amount_spent / limit * 100, 1) if limit > 0 else None
        if pct is None:
            status = "no-limit"
        elif pct >= 100:
            status = "over"
        elif pct >= 70:
            status = "warning"
        else:
            status = "ok"
        comparison.append({
            "key":    key,
            "label":  label,
            "limit":  limit,
            "spent":  round(amount_spent, 2),
            "pct":    pct,
            "status": status,
        })

    # Cash flow forecast
    cur_income = conn.execute(
        "SELECT COALESCE(SUM(salary+bonus+side+rental+dividends+gifts+other),0) "
        "FROM income WHERE user_id=? AND month=?",
        (user_id, cur_month)
    ).fetchone()[0]

    recurring_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM recurring WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    cur_expenses_total = sum(v for v in spent.values())
    forecast_balance   = round(cur_income - recurring_total - cur_expenses_total, 2)

    conn.close()

    return render_template("budgets.html",
        comparison       = comparison,
        cur_month        = cur_month,
        cur_income       = round(cur_income, 2),
        recurring_total  = round(recurring_total, 2),
        cur_expenses     = round(cur_expenses_total, 2),
        forecast_balance = forecast_balance,
        limits           = limits,
        categories       = EXPENSE_CATEGORIES,
    )


@app.route("/budgets/save", methods=["POST"])
@login_required
def save_budgets():
    user_id = get_user_id()
    conn    = get_db()
    for key, _ in EXPENSE_CATEGORIES:
        val = form_float(key)
        conn.execute(
            "INSERT INTO budget_limits (user_id, category, monthly_limit) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, category) DO UPDATE SET monthly_limit=excluded.monthly_limit",
            (user_id, key, val)
        )
    conn.commit()
    conn.close()
    return redirect("/budgets")


# ─────────────────────────────────────────────
# API ROUTES (for Chart.js / dashboard JS)
# ─────────────────────────────────────────────

@app.route("/api/dashboard-data")
@login_required
def api_dashboard_data():
    """Returns all JSON data needed by the rich dashboard."""
    user_id = get_user_id()
    conn    = get_db()

    # --- income / expense by month (6 months) ---
    income_by_month = conn.execute(
        "SELECT month, SUM(salary+bonus+side+rental+dividends+gifts+other) as total "
        "FROM income WHERE user_id=? GROUP BY month ORDER BY month ASC LIMIT 6",
        (user_id,)
    ).fetchall()

    expense_by_month = conn.execute(
        "SELECT month, SUM(utilities+groceries+dining_out+transport+shopping+healthcare+entertainment+personal_care+other) as total "
        "FROM expenses WHERE user_id=? GROUP BY month ORDER BY month ASC LIMIT 6",
        (user_id,)
    ).fetchall()

    # --- expense breakdown (all time) ---
    expense_breakdown = conn.execute(
        "SELECT SUM(utilities) as utilities, SUM(groceries) as groceries, "
        "SUM(dining_out) as dining_out, SUM(transport) as transport, "
        "SUM(shopping) as shopping, SUM(healthcare) as healthcare, "
        "SUM(entertainment) as entertainment, SUM(personal_care) as personal_care, "
        "SUM(other) as other FROM expenses WHERE user_id=?",
        (user_id,)
    ).fetchone()

    # --- savings goals ---
    goals = conn.execute(
        "SELECT name, target, saved, deadline FROM savings_goals WHERE user_id=?",
        (user_id,)
    ).fetchall()

    # --- upcoming recurring bills (next 7 days by due_day) ---
    today_day = datetime.now().day
    upcoming  = conn.execute(
        "SELECT name, category, amount, due_day FROM recurring "
        "WHERE user_id=? AND due_day >= ? ORDER BY due_day ASC LIMIT 5",
        (user_id, today_day)
    ).fetchall()

    # --- all-time totals ---
    total_income = conn.execute(
        "SELECT COALESCE(SUM(salary+bonus+side+rental+dividends+gifts+other),0) FROM income WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    total_expenses = conn.execute(
        "SELECT COALESCE(SUM(utilities+groceries+dining_out+transport+shopping+healthcare+entertainment+personal_care+other),0) FROM expenses WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    total_savings = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM savings WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    total_investments = conn.execute(
        "SELECT COALESCE(SUM(investment),0) FROM savings WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    total_credit = conn.execute(
        "SELECT COALESCE(SUM(balance),0) FROM credit_cards WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    total_loans = conn.execute(
        "SELECT COALESCE(SUM(balance),0) FROM loans WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    total_debt = total_credit + total_loans

    # --- foreign shares portfolio value ---
    shares_raw = conn.execute(
        "SELECT name, units, price_per_unit FROM foreign_shares WHERE user_id=?",
        (user_id,)
    ).fetchall()
    portfolio_value = sum(s["units"] * s["price_per_unit"] for s in shares_raw)

    # --- current / previous month totals ---
    cur_month  = datetime.now().strftime("%Y-%m")
    prev_month = (datetime.now().replace(day=1) - __import__('datetime').timedelta(days=1)).strftime("%Y-%m")

    def month_income(m):
        r = conn.execute(
            "SELECT COALESCE(SUM(salary+bonus+side+rental+dividends+gifts+other),0) FROM income WHERE user_id=? AND month=?",
            (user_id, m)
        ).fetchone()
        return r[0] if r else 0

    def month_expense(m):
        r = conn.execute(
            "SELECT COALESCE(SUM(utilities+groceries+dining_out+transport+shopping+healthcare+entertainment+personal_care+other),0) FROM expenses WHERE user_id=? AND month=?",
            (user_id, m)
        ).fetchone()
        return r[0] if r else 0

    # Recurring bills are fixed monthly outgoings — fetch once and include in monthly totals
    recurring_monthly = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM recurring WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    cur_income   = month_income(cur_month)
    cur_expense  = month_expense(cur_month) + recurring_monthly   # variable spend + fixed bills
    prev_income  = month_income(prev_month)
    prev_expense = month_expense(prev_month) + recurring_monthly  # same bills applied to prev month

    # --- derived gross savings = income minus all expenses (auto-calculated) ---
    gross_savings_derived = max(0, total_income - total_expenses)

    # --- net worth: (income − expenses) + portfolio assets − liabilities ---
    net_worth    = gross_savings_derived + portfolio_value - total_debt
    savings_rate = round(gross_savings_derived / total_income * 100, 1) if total_income > 0 else 0
    health_score = min(100, max(0, int(savings_rate * 2 + (50 if net_worth >= 0 else 0))))

    # --- budget comparison (current month vs limits) ---
    limits_raw = conn.execute(
        "SELECT category, monthly_limit FROM budget_limits WHERE user_id=?",
        (user_id,)
    ).fetchall()
    limits_map = {r["category"]: r["monthly_limit"] for r in limits_raw}

    cur_exp_row = conn.execute(
        "SELECT SUM(utilities) as utilities, SUM(groceries) as groceries, "
        "SUM(dining_out) as dining_out, SUM(transport) as transport, "
        "SUM(shopping) as shopping, SUM(healthcare) as healthcare, "
        "SUM(entertainment) as entertainment, SUM(personal_care) as personal_care, "
        "SUM(other) as other FROM expenses WHERE user_id=? AND month=?",
        (user_id, cur_month)
    ).fetchone()

    budget_comparison = []
    for key, label in EXPENSE_CATEGORIES:
        limit  = limits_map.get(key, 0.0)
        s      = (cur_exp_row[key] or 0.0) if cur_exp_row else 0.0
        pct    = round(s / limit * 100, 1) if limit > 0 else None
        if pct is None:
            status = "no-limit"
        elif pct >= 100:
            status = "over"
        elif pct >= 70:
            status = "warning"
        else:
            status = "ok"
        budget_comparison.append({
            "key": key, "label": label,
            "limit": limit, "spent": round(s, 2),
            "pct": pct, "status": status,
        })

    # --- cash flow forecast ---
    recurring_total_cf = recurring_monthly  # already fetched above
    cur_exp_total = sum(
        (cur_exp_row[k] or 0.0) for k, _ in EXPENSE_CATEGORIES
    ) if cur_exp_row else 0.0
    forecast_balance = round(cur_income - recurring_total_cf - cur_exp_total, 2)

    conn.close()

    return jsonify({
        "username":          session.get("username", ""),
        "income_by_month":   [{"month": r["month"], "total": r["total"]} for r in income_by_month],
        "expense_by_month":  [{"month": r["month"], "total": r["total"]} for r in expense_by_month],
        "expense_breakdown": {k: (v or 0) for k, v in dict(expense_breakdown).items()} if expense_breakdown else {},
        "savings_goals":     [{"name": g["name"], "target": g["target"], "saved": g["saved"], "deadline": g["deadline"] or ""} for g in goals],
        "upcoming_bills":    [{"name": b["name"], "category": b["category"], "amount": b["amount"], "due_day": b["due_day"]} for b in upcoming],
        "totals": {
            "income":       round(total_income, 2),
            "expenses":     round(total_expenses, 2),
            "savings":      round(gross_savings_derived, 2),
            "investments":  round(total_investments, 2),
            "debt":         round(total_debt, 2),
            "net_savings":  round(gross_savings_derived - total_investments, 2),
            "savings_rate": savings_rate,
            "net_worth":    round(net_worth, 2),
            "portfolio":    round(portfolio_value, 2),
        },
        "current_month": {
            "month":   cur_month,
            "income":  round(cur_income, 2),
            "expense": round(cur_expense, 2),
            "balance": round(cur_income - cur_expense, 2),
        },
        "prev_month": {
            "month":   prev_month,
            "income":  round(prev_income, 2),
            "expense": round(prev_expense, 2),
        },
        "health_score": health_score,
        "budget_comparison": budget_comparison,
        "cash_flow_forecast": {
            "income":    round(cur_income, 2),
            "recurring": round(recurring_total_cf, 2),
            "spent":     round(cur_exp_total, 2),
            "balance":   forecast_balance,
        },
    })


# ─────────────────────────────────────────────
# SETTINGS ROUTE
# ─────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user_id = get_user_id()
    conn    = get_db()

    if request.method == "POST":
        action = request.form.get("action", "currency")

        if action == "currency":
            new_currency = request.form.get("currency", "£")
            conn.execute("UPDATE users SET currency=? WHERE id=?", (new_currency, user_id))
            conn.commit()
            session["currency"] = new_currency

        elif action == "profile":
            first_name = request.form.get("first_name", "").strip()
            last_name  = request.form.get("last_name", "").strip()
            email      = request.form.get("email", "").strip()
            phone      = request.form.get("phone", "").strip()
            dob        = request.form.get("date_of_birth", "").strip()
            country    = request.form.get("country", "").strip()
            bio        = request.form.get("bio", "").strip()

            # Check if profile exists
            existing = conn.execute(
                "SELECT id FROM user_profiles WHERE user_id=?", (user_id,)
            ).fetchone()

            if existing:
                conn.execute('''
                    UPDATE user_profiles
                    SET first_name=?, last_name=?, email=?, phone=?,
                        date_of_birth=?, country=?, bio=?, updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=?
                ''', (first_name, last_name, email, phone, dob, country, bio, user_id))
            else:
                conn.execute('''
                    INSERT INTO user_profiles
                        (user_id, first_name, last_name, email, phone, date_of_birth, country, bio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, first_name, last_name, email, phone, dob, country, bio))
            conn.commit()

        elif action == "password":
            current_pw = request.form.get("current_password", "")
            new_pw     = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")

            user_row = conn.execute("SELECT password FROM users WHERE id=?", (user_id,)).fetchone()
            if user_row["password"] != hash_password(current_pw):
                conn.close()
                return redirect("/settings?error=wrong_password")
            if new_pw != confirm_pw or not (new_pw.isdigit() and len(new_pw) == 4):
                conn.close()
                return redirect("/settings?error=password_mismatch")

            conn.execute("UPDATE users SET password=? WHERE id=?", (hash_password(new_pw), user_id))
            conn.commit()

        conn.close()
        return redirect("/settings")

    user    = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    profile = conn.execute("SELECT * FROM user_profiles WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return render_template("settings.html", user=user, profile=profile, currencies=CURRENCIES)


# ─────────────────────────────────────────────
# CSV EXPORT ROUTES
# ─────────────────────────────────────────────

@app.route("/export/<section>")
@login_required
def export_csv(section):
    """Generate and stream a CSV download for the given section."""
    user_id = get_user_id()
    conn    = get_db()
    si      = io.StringIO()
    writer  = csv.writer(si)

    if section == "income":
        writer.writerow(["Month", "Salary", "Bonus", "Side Income", "Rental",
                         "Dividends", "Gifts", "Other", "Total"])
        rows = conn.execute(
            "SELECT * FROM income WHERE user_id=? ORDER BY month DESC", (user_id,)
        ).fetchall()
        for r in rows:
            total = r["salary"]+r["bonus"]+r["side"]+r["rental"]+r["dividends"]+r["gifts"]+r["other"]
            writer.writerow([r["month"], r["salary"], r["bonus"], r["side"], r["rental"],
                             r["dividends"], r["gifts"], r["other"], round(total, 2)])

    elif section == "expenses":
        writer.writerow(["Month", "Utilities", "Groceries", "Dining Out", "Transport",
                         "Shopping", "Healthcare", "Entertainment", "Personal Care", "Other", "Total"])
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id=? ORDER BY month DESC", (user_id,)
        ).fetchall()
        for r in rows:
            total = (r["utilities"]+r["groceries"]+r["dining_out"]+r["transport"]+
                     r["shopping"]+r["healthcare"]+r["entertainment"]+r["personal_care"]+r["other"])
            writer.writerow([r["month"], r["utilities"], r["groceries"], r["dining_out"],
                             r["transport"], r["shopping"], r["healthcare"], r["entertainment"],
                             r["personal_care"], r["other"], round(total, 2)])

    elif section == "recurring":
        writer.writerow(["Name", "Category", "Amount", "Due Day", "Notes"])
        rows = conn.execute(
            "SELECT * FROM recurring WHERE user_id=? ORDER BY due_day ASC", (user_id,)
        ).fetchall()
        for r in rows:
            writer.writerow([r["name"], r["category"], r["amount"], r["due_day"], r["notes"] or ""])

    elif section == "savings":
        writer.writerow(["Month", "Saved", "Invested", "Type", "Notes"])
        rows = conn.execute(
            "SELECT * FROM savings WHERE user_id=? ORDER BY month DESC", (user_id,)
        ).fetchall()
        for r in rows:
            writer.writerow([r["month"], r["amount"], r["investment"],
                             r["type"] or "", r["notes"] or ""])

    elif section == "debt":
        writer.writerow(["Type", "Name", "Balance", "Interest Rate (%)"])
        cards = conn.execute(
            "SELECT * FROM credit_cards WHERE user_id=?", (user_id,)
        ).fetchall()
        for r in cards:
            writer.writerow(["Credit Card", r["name"], r["balance"], r["rate"]])
        loans = conn.execute(
            "SELECT * FROM loans WHERE user_id=?", (user_id,)
        ).fetchall()
        for r in loans:
            writer.writerow(["Loan", r["name"], r["balance"], r["rate"]])

    elif section == "shares":
        writer.writerow(["Name", "Units", "Price Per Unit", "Total Value", "Date Bought"])
        rows = conn.execute(
            "SELECT * FROM foreign_shares WHERE user_id=?", (user_id,)
        ).fetchall()
        for r in rows:
            writer.writerow([r["name"], r["units"], r["price_per_unit"],
                             round(r["units"]*r["price_per_unit"], 2), r["date_bought"] or ""])

    else:
        conn.close()
        return "Invalid section", 404

    conn.close()
    filename = f"budget_{section}_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ─────────────────────────────────────────────
# DEBT PAYOFF CALCULATOR
# ─────────────────────────────────────────────

@app.route("/debt-payoff")
@login_required
def debt_payoff():
    user_id = get_user_id()
    conn    = get_db()
    cards   = conn.execute(
        "SELECT * FROM credit_cards WHERE user_id=?", (user_id,)
    ).fetchall()
    loans   = conn.execute(
        "SELECT * FROM loans WHERE user_id=?", (user_id,)
    ).fetchall()
    conn.close()

    debts = []
    for c in cards:
        debts.append({"type": "Credit Card", "name": c["name"],
                      "balance": c["balance"], "rate": c["rate"]})
    for ln in loans:
        debts.append({"type": "Loan", "name": ln["name"],
                      "balance": ln["balance"], "rate": ln["rate"]})

    # Sort copies for avalanche (highest rate) and snowball (lowest balance)
    avalanche = sorted(debts, key=lambda d: -d["rate"])
    snowball  = sorted(debts, key=lambda d:  d["balance"])

    total_debt = sum(d["balance"] for d in debts)
    return render_template("debt_payoff.html",
                           debts=debts,
                           avalanche=avalanche,
                           snowball=snowball,
                           total_debt=round(total_debt, 2))


# ─────────────────────────────────────────────
# RUN THE APP
# ─────────────────────────────────────────────

# Always create tables on startup (works with both gunicorn and python app.py)
try:
    init_db()
except Exception as e:
    print(f"[WARN] DB init failed, will retry on first request: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
