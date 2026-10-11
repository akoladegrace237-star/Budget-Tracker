# Budget Tracker

A Flask budget application with a shared transaction ledger, monthly budgets, recurring bills, savings goals, debt planning, portfolio tracking and a 12-month cash-flow scenario. Supports SQLite locally and PostgreSQL in production.

## Run locally

Use Python 3.11 or newer.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe app.py
```

Open http://127.0.0.1:5000, create an account, save your recovery code and complete setup. Existing accounts can still sign in with their old PIN; keep using it or change it to another four-digit PIN in Settings and generate a recovery code. Favourite-colour recovery has been retired.

Local development creates an ignored `.local-secret` to keep sessions valid across restarts. Debug mode is off unless `FLASK_DEBUG=1` is explicitly set. `.env.example` documents environment variables; the app reads process environment variables, not `.env` files automatically.

### Administrator-assisted account reset

The `users.password` field stores a salted hash, never a plain-text password. To repair an account whose password field was manually edited, run `.venv/Scripts/python.exe tools/password_hash.py` locally. Enter and confirm a four-digit PIN at its hidden prompts, copy the entire generated hash into that account's `users.password` field, and increment its `credential_version` by one to invalidate existing sessions. Sign in with the entered PIN, not the hash. This does not change financial records. Prefer Settings or recovery codes for normal password changes.

## Financial model

- Transactions are the source for income, expenses, budgets and charts. Money in the ledger is stored as integer hundredths; SQLite stores exact scaled fields for other monetary records, and PostgreSQL uses fixed-precision numeric fields. Unit prices support four decimals and share units support six.
- Set starting cash and its date in Setup or Settings. Starting cash is the total cash across your accounts before transactions on that date. Earlier entries remain in reports but do not change this balance.
- Tracked cash = starting cash + income − spending − outgoing investment transfers − debt payments, from the balance date. Investment sale transfers increase cash. Internal transfers between your own cash accounts do not change total cash and need no entry.
- Tracked net worth = tracked cash + entered portfolio holdings − outstanding credit-card and loan balances. Portfolio holdings are manually valued; update them when recording investment purchases or sales. This is a tracker of entered assets, not a complete bank reconciliation.
- Savings records and goals track contributions/progress. They do not add assets to net worth again, because cash savings are already part of starting cash and cash movements.
- Remaining monthly cash flow = income received − spending − unpaid recurring bills − net transfers/debt payments. It can be negative. It is a monthly surplus, not the bank balance or a guaranteed safe-to-spend amount.
- Marking a bill paid creates one expense. Paying debt creates a transfer and reduces the liability. Deleting a linked payment transaction reverses the payment while its bill/debt record exists. Deleting a bill or debt record retains its past cash transactions and detaches their source links.
- The monthly tracker score uses 60% surplus ratio after unpaid bills and payments, plus 40% category-budget adherence. Missing limits earn no budget points. It is not a credit score or financial assessment.
- The forecast uses average income/non-bill spending from the latest six recorded months plus current recurring bills. Missing historical months are not treated as zero. It assumes unchanged amounts and excludes investment returns and future debt payments.
- Net worth snapshots are saved explicitly with the dashboard button. Opening the dashboard never writes financial history.
- Currency settings change the display symbol. They do not convert balances or perform foreign exchange.

## Existing data and migration

The first request creates/migrates the database. Existing local databases are backed up under `backups/` before the first ledger migration. Production PostgreSQL deployments should take a database snapshot before upgrading.

Original income and expense tables are retained. For each legacy month/category, explicit reconciliation entries make the ledger match the old monthly summary. Transaction-only months remain intact. Old summaries were maintained separately and could disagree with transactions; reconciliation does not infer which old entry was correct. Review the dashboard migration notice and search Transactions for `Legacy` before changing old records. Legacy net worth snapshots are retained and identified as estimates made under the previous formula.

Migrations are versioned, transactional and repeatable. SQLite enables foreign-key checks. A configured PostgreSQL database never silently falls back to local storage.

## Import, export and restore

Settings provides CSV import, section exports, a complete JSON backup and restore.

CSV import requires `date,type,category,amount`; `description` is optional. Dates use YYYY-MM-DD and amounts are positive with up to two decimals. Types are `income`, `expense`, or `transfer`; investment transfer categories are `investment_purchase` and `investment_sale` (a sale adds cash). Preview shows accepted rows and duplicate counts before confirmation. Matching date, type, category, description and amount identifies a duplicate, including duplicates inside the uploaded file. Identical genuine purchases should be reviewed separately. Preview expires after one hour; limits are 5 MB and 10,000 rows.

Transaction CSV is intended for standard entries. Linked debt transfers and migration adjustments require the complete JSON backup. Spreadsheet exports escape formula-like text. JSON preserves original text and all active financial sections, profiles, settings, snapshots and payment relationships. Sign-in credentials are excluded.

Restore requires the current password and a replacement checkbox. It validates the backup, remaps record IDs, replaces only the signed-in user's data in one transaction and saves a before-restore safety copy. Download the previous safety copy from Settings if needed. Password/recovery credentials stay unchanged.

## Privacy and offline behaviour

Data is stored in the application's database, not browser LocalStorage. Browser storage is used only for UI preferences. The service worker caches an allowlist of static assets; private pages, APIs, exports and financial data are never cached. Offline navigation shows a reconnect screen. Budget editing requires a connection to the server. Logout clears the session and asks supported browsers to clear cache/storage.

PINs and recovery codes use salted scrypt hashes. Temporary authentication lockouts are disabled for this owner?s personal-use app; old attempt counters are ignored. Forms require CSRF tokens; destructive actions use POST. Sessions are invalidated after password changes/recovery. New accounts require passwords of 12–128 characters.

## Deploy

Railway configuration and `Procfile` use Gunicorn. Set:

- `APP_ENV=production`
- `SECRET_KEY`: at least 32 unpredictable characters, generated with `python -c "import secrets; print(secrets.token_hex(32))"`
- `DATABASE_URL`: production PostgreSQL connection string
- `PORT`: supplied by the host

Production requires HTTPS because session cookies are Secure. Keep the secret stable across releases. The application refuses to start with a missing/short production secret. Never commit secrets or database files. Set up scheduled database backups and verify restoration using your host's facilities; the app's exports are user-owned backups, not a substitute for host backups.

## Tests and visual review

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe tests/migration_review.py
```

Unit tests use isolated databases under ignored `.qa/`. Migration review reads `database.db` in read-only mode, migrates a consistent copy and verifies the original file is unchanged.

For browser checks:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
$env:PLAYWRIGHT_BROWSERS_PATH="$PWD/.browser-cache"
.venv/Scripts/python.exe -m playwright install chromium
$env:BUDGET_DB_PATH="$PWD/.qa/visual.db"
$env:SECRET_KEY="visual-review-only-secret-key-32-characters"
$env:APP_ENV="test"
$env:PORT="5055"
.venv/Scripts/python.exe app.py
# In a second terminal:
.venv/Scripts/python.exe tests/visual_review.py
```

Browser checks create sample accounts only in the isolated preview, exercise keyboard dialogs, errors, user text escaping and offline/cache behaviour, and save desktop/mobile screenshots plus a layout report under `.qa/screenshots/`. Browser subprocesses may need permission in restricted Windows environments. PostgreSQL integration requires a separate test database; the checked-in suite uses SQLite.

## Project structure

- `app.py`: application setup, existing savings/budget/debt/portfolio/profile routes
- `auth_routes.py`, `security.py`: authentication, recovery, sessions and request protection
- `ledger_routes.py`, `finance.py`: ledger writes, validation, monthly cash flow and exact money handling
- `reporting.py`: dashboard, projections and snapshots
- `data_tools.py`: setup, imports, exports and restore
- `db.py`, `migrations.py`: database adapter and versioned migrations
- `templates/`, `static/`: server-rendered UI, charts and offline shell
- `tests/`: finance/security/data regression checks and browser review

Chart.js 3.9.1 is vendored under `static/js/vendor/` and licensed under MIT.
