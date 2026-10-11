from flask import Flask, render_template, request, redirect, session, jsonify, send_from_directory, Response, flash, get_flashed_messages
import os
import io
from datetime import datetime
from db import get_db, init_db, is_postgres, lock_user

app = Flask(__name__)
from security import configure, hash_password, verify_password, strong_password
from finance import cash_flow, today, SafeCSVWriter

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
    if request.path.startswith(('/static/','/icons/')) or request.path in ('/styles.css','/sw.js'):
        return
    if not _db_ready:
        try:
            init_db()
            _db_ready = True
        except Exception:
            app.logger.exception("Database initialization failed")
            from flask import abort
            abort(503, description="The database is unavailable. Please try again shortly.")


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
    return redirect('/login')


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# INCOME ROUTES
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# EXPENSES ROUTES
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# RECURRING PAYMENTS ROUTES
# ─────────────────────────────────────────────

@app.route("/recurring")
@login_required
def recurring():
    user_id   = get_user_id()
    cur_month = today().strftime("%Y-%m")
    conn      = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    records   = conn.execute(
        "SELECT * FROM recurring WHERE user_id=? ORDER BY due_day ASC",
        (user_id,)
    ).fetchall()
    total_monthly = sum(r["amount"] for r in records)
    paid_count    = sum(1 for r in records if r["last_paid_month"] == cur_month)
    conn.close()
    return render_template("recurring.html", records=records,
                           cur_month=cur_month, total_monthly=total_monthly,
                           paid_count=paid_count)


@app.route("/recurring/add", methods=["POST"])
@login_required
def add_recurring():
    user_id = get_user_id()
    conn    = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
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


@app.route("/recurring/delete/<int:record_id>", methods=["POST"])
@login_required
def delete_recurring(record_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute("DELETE FROM bill_payments WHERE bill_id=? AND user_id=?", (record_id, get_user_id()))
    conn.execute("UPDATE transactions SET source_id=NULL WHERE source='bill' AND source_id=? AND user_id=?", (record_id, get_user_id()))
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
    if request.method == "POST": lock_user(conn,get_user_id())
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
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute('''
        INSERT INTO savings (user_id, month, amount, investment, type, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        request.form.get("month", today().strftime("%Y-%m")),
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
    if request.method == "POST": lock_user(conn,get_user_id())
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
    return redirect("/debt")


@app.route("/credit/add", methods=["POST"])
@login_required
def add_credit():
    user_id = get_user_id()
    conn    = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
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
    return redirect("/debt")


@app.route("/credit/delete/<int:card_id>", methods=["POST"])
@login_required
def delete_credit(card_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute("UPDATE transactions SET source_id=NULL WHERE source='debt' AND category='credit_payment' AND source_id=? AND user_id=?", (card_id, get_user_id()))
    conn.execute("DELETE FROM credit_cards WHERE id=? AND user_id=?", (card_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/debt")


# ─────────────────────────────────────────────
# LOANS ROUTES
# ─────────────────────────────────────────────

@app.route("/loans")
@login_required
def loans():
    return redirect("/debt")


@app.route("/loans/add", methods=["POST"])
@login_required
def add_loan():
    user_id = get_user_id()
    conn    = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
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
    return redirect("/debt")


@app.route("/loans/delete/<int:loan_id>", methods=["POST"])
@login_required
def delete_loan(loan_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute("UPDATE transactions SET source_id=NULL WHERE source='debt' AND category='loan_payment' AND source_id=? AND user_id=?", (loan_id, get_user_id()))
    conn.execute("DELETE FROM loans WHERE id=? AND user_id=?", (loan_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/debt")


# ─────────────────────────────────────────────
# PROJECTIONS ROUTE
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# FOREIGN SHARES ROUTES
# ─────────────────────────────────────────────

@app.route("/shares")
@login_required
def shares():
    user_id     = get_user_id()
    conn        = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
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
    if request.method == "POST": lock_user(conn,get_user_id())
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


@app.route("/shares/delete/<int:share_id>", methods=["POST"])
@login_required
def delete_share(share_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute("DELETE FROM foreign_shares WHERE id=? AND user_id=?", (share_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/shares")


# ─────────────────────────────────────────────
# BUDGET LIMITS ROUTES
# ─────────────────────────────────────────────

from finance import EXPENSE_CATEGORIES


def get_month_cash_flow(conn, user_id, month):
    return cash_flow(conn, user_id, month)


@app.route("/budgets")
@login_required
def budgets():
    user_id   = get_user_id()
    cur_month = today().strftime("%Y-%m")
    conn      = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())

    # Load existing limits
    limits_raw = conn.execute(
        "SELECT category, monthly_limit FROM budget_limits WHERE user_id=?",
        (user_id,)
    ).fetchall()
    limits = {r["category"]: r["monthly_limit"] for r in limits_raw}

    cash_flow = get_month_cash_flow(conn, user_id, cur_month)
    spent = cash_flow["spent_by_category"]

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

    # Cash flow forecast (same source-of-truth logic as dashboard API)
    cur_income = cash_flow["income"]
    recurring_total = cash_flow["unpaid_recurring"]
    cur_expenses_total = cash_flow["spent_total"]
    forecast_balance = cash_flow["balance"]

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
    if request.method == "POST": lock_user(conn,get_user_id())
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


# ─────────────────────────────────────────────
# SETTINGS ROUTE
# ─────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user_id = get_user_id()
    conn    = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())

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

            from security import throttle
            if not throttle(conn, session['username']):
                conn.close()
                from flask import abort
                abort(429, description='Too many attempts. Try again in 15 minutes.')
            user_row = conn.execute("SELECT password,credential_version FROM users WHERE id=?", (user_id,)).fetchone()
            if not verify_password(user_row["password"], current_pw):
                conn.close()
                return redirect("/settings?error=wrong_password")
            if new_pw != confirm_pw or not strong_password(new_pw):
                conn.close()
                return redirect("/settings?error=password_mismatch")

            conn.execute("UPDATE users SET password=?,credential_version=credential_version+1 WHERE id=?", (hash_password(new_pw), user_id))
            session['credential_version'] = user_row['credential_version']+1
            session["upgrade_password"] = False
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
    if request.method == "POST": lock_user(conn,get_user_id())
    si      = io.StringIO()
    writer  = SafeCSVWriter(si)

    if section == "income":
        writer.writerow(["Month", "Salary", "Bonus", "Side Income", "Rental",
                         "Dividends", "Gifts", "Other", "Total"])
        rows = conn.execute(
            "SELECT * FROM income_summary WHERE user_id=? ORDER BY month DESC", (user_id,)
        ).fetchall()
        for r in rows:
            total = r["salary"]+r["bonus"]+r["side"]+r["rental"]+r["dividends"]+r["gifts"]+r["other"]
            writer.writerow([r["month"], r["salary"], r["bonus"], r["side"], r["rental"],
                             r["dividends"], r["gifts"], r["other"], round(total, 2)])

    elif section == "expenses":
        writer.writerow(["Month"]+[label for key,label in EXPENSE_CATEGORIES]+["Total"])
        rows = conn.execute(
            "SELECT * FROM expense_summary WHERE user_id=? ORDER BY month DESC", (user_id,)
        ).fetchall()
        for r in rows:
            values=[r[key] for key,label in EXPENSE_CATEGORIES]
            writer.writerow([r['month']]+values+[round(sum(values),2)])

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

@app.route("/debt")
@login_required
def debt_payoff():
    user_id = get_user_id()
    conn    = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
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
                      "balance": float(c["balance"]), "rate": float(c["rate"])})
    for ln in loans:
        debts.append({"type": "Loan", "name": ln["name"],
                      "balance": float(ln["balance"]), "rate": float(ln["rate"])})

    # Sort copies for avalanche (highest rate) and snowball (lowest balance)
    avalanche = sorted(debts, key=lambda d: -d["rate"])
    snowball  = sorted(debts, key=lambda d:  d["balance"])

    total_debt = sum(d["balance"] for d in debts)
    return render_template("debt_payoff.html",
                           debts=debts,
                           cards=cards,
                           loans=loans,
                           avalanche=avalanche,
                           snowball=snowball,
                           total_debt=round(total_debt, 2))


@app.route("/debt-payoff")
@login_required
def debt_payoff_legacy_redirect():
    return redirect("/debt")


# ─────────────────────────────────────────────
# TRANSACTIONS LOG
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# EDIT ROUTES (all sections)
# ─────────────────────────────────────────────


@app.route("/recurring/edit/<int:record_id>", methods=["POST"])
@login_required
def edit_recurring(record_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute('''
        UPDATE recurring SET name=?, category=?, amount=?, due_day=?, notes=?
        WHERE id=? AND user_id=?
    ''', (request.form["name"], request.form["category"], form_float("amount"),
          form_int("due_day"), request.form.get("notes", ""), record_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/recurring")


@app.route("/savings/delete/<int:record_id>", methods=["POST"])
@login_required
def delete_savings(record_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute("DELETE FROM savings WHERE id=? AND user_id=?", (record_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/savings")


@app.route("/savings/edit/<int:record_id>", methods=["POST"])
@login_required
def edit_savings(record_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute('''
        UPDATE savings SET month=?, amount=?, investment=?, type=?, notes=?
        WHERE id=? AND user_id=?
    ''', (request.form.get("month"), form_float("amount"), form_float("investment"),
          request.form.get("type", ""), request.form.get("notes", ""),
          record_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/savings")


@app.route("/savings/goal/edit/<int:goal_id>", methods=["POST"])
@login_required
def edit_savings_goal(goal_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute('''
        UPDATE savings_goals SET name=?, target=?, saved=?, deadline=?
        WHERE id=? AND user_id=?
    ''', (request.form["name"], form_float("target"), form_float("saved"),
          request.form.get("deadline", ""), goal_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/savings")


@app.route("/savings/goal/delete/<int:goal_id>", methods=["POST"])
@login_required
def delete_savings_goal(goal_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute("DELETE FROM savings_goals WHERE id=? AND user_id=?", (goal_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/savings")


@app.route("/credit/edit/<int:card_id>", methods=["POST"])
@login_required
def edit_credit(card_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute('''
        UPDATE credit_cards SET name=?, rate=?, balance=?
        WHERE id=? AND user_id=?
    ''', (request.form["name"], form_float("rate"), form_float("balance"),
          card_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/debt")


@app.route("/loans/edit/<int:loan_id>", methods=["POST"])
@login_required
def edit_loan(loan_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute('''
        UPDATE loans SET name=?, rate=?, balance=?
        WHERE id=? AND user_id=?
    ''', (request.form["name"], form_float("rate"), form_float("balance"),
          loan_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/debt")


@app.route("/shares/edit/<int:share_id>", methods=["POST"])
@login_required
def edit_share(share_id):
    conn = get_db()
    if request.method == "POST": lock_user(conn,get_user_id())
    conn.execute('''
        UPDATE foreign_shares SET name=?, units=?, price_per_unit=?, date_bought=?
        WHERE id=? AND user_id=?
    ''', (request.form["name"], form_float("units"), form_float("price_per_unit"),
          request.form.get("date_bought", ""), share_id, get_user_id()))
    conn.commit()
    conn.close()
    return redirect("/shares")


# ─────────────────────────────────────────────
# RUN THE APP
# ─────────────────────────────────────────────

configure(app)

@app.teardown_request
def close_request_connections(error):
    from flask import g
    for conn in g.pop('db_connections',[]):
        conn.close()

from auth_routes import auth
from ledger_routes import ledger
from reporting import reports
from data_tools import data_tools
app.register_blueprint(auth)
app.register_blueprint(ledger)
app.register_blueprint(reports)
app.register_blueprint(data_tools)

from werkzeug.exceptions import HTTPException

@app.errorhandler(HTTPException)
def show_http_error(error):
    if request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
        return jsonify(error=error.description), error.code
    return render_template('error.html', error=error), error.code

@app.errorhandler(Exception)
def show_unexpected_error(error):
    app.logger.exception('Unhandled request error')
    from werkzeug.exceptions import InternalServerError
    return show_http_error(InternalServerError(description='Something went wrong. Your changes may not have been saved. Please try again.'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
