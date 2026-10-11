# Budget Tracker project instructions

This is a Flask web application, not an Excel generator or a browser-only static app. Read README.md for setup, financial definitions and migration behaviour.

## Architecture

- `app.py` creates/configures Flask and retains savings, debt, budget, profile and portfolio screens.
- `auth_routes.py` and `security.py` handle sign-in, recovery, session security and CSRF.
- `ledger_routes.py` owns all transaction writes. Income/expense pages are derived summaries.
- `finance.py` contains shared validation and exact-money helpers.
- `reporting.py` derives dashboard values, recent-month charts and forecasts.
- `data_tools.py` handles setup, reviewed CSV import and complete backup/restore.
- `db.py` supports SQLite and PostgreSQL; `migrations.py` makes additive, versioned changes.
- UI uses Jinja templates, shared CSS, vanilla JavaScript and vendored Chart.js.

## Financial invariants

- Transactions are canonical. Do not write new records to legacy `income` or `expenses` tables.
- Store transaction money as integer minor units; use `finance.cents`, not floating-point accumulation. Keep the compatibility display amount consistent with `amount_minor`.
- Unit prices use four decimals, share units six; round valuations only at the resulting money amount.
- Retain negative cash flow. Never clamp losses to zero.
- Bills count once when paid. Debt payments reduce both cash and debt; investment transfers change cash without counting as everyday spending.
- Net worth derives from starting cash plus dated cash movements, portfolio holdings and liabilities. Savings contributions/goals are not additional assets.
- Join monthly income/expense data by month, never by list position. Charts show the latest six recorded months chronologically.
- Keep all reads/writes scoped to `session['user_id']`. Backup restore must remap IDs and remain atomic.

## Security and data

- Use salted scrypt hashes. Preserve the one-time upgrade path for old SHA-256 PINs; never introduce new unsalted credentials.
- New passwords require 12–128 characters. Recovery uses random codes, not security questions.
- All changing actions use POST and CSRF. Forms include a server-rendered token; fetch calls send X-CSRF-Token.
- Authenticate sensitive credential changes. Password changes/recovery invalidate other sessions.
- Do not put user-entered text directly into innerHTML or inline JavaScript. Use textContent, DOM APIs, escaped text and Jinja tojson.
- Validate money, category, date and due day on the server. Browser validation is supplementary.
- Cache static assets only. Private HTML, APIs, exports and financial values use no-store.
- Require an unpredictable production SECRET_KEY. Never log credentials/database connection URLs or silently fall back from a configured PostgreSQL database.
- Preserve original records during migrations. Test on isolated copies; never use database.db for regression/browser tests.

## UI and validation

Preserve the blue/slate styling and prioritise monthly cash flow and quick transaction entry. Verify desktop and narrow mobile screens. Dialogs need labelled headings, keyboard focus handling, Escape-to-close and focus restoration. Associate every field with a label; use accessible status/error feedback and respect reduced motion.

Run `.venv/Scripts/python.exe -m unittest discover -s tests -v` for financial/security/data changes. Run the isolated browser review when UI behaviour changes; see README.md. Add meaningful tests for new financial edge cases rather than tests that repeat implementation details. Update README.md when behaviour or deployment requirements change.
