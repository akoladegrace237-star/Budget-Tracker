# Implemented app improvements

The app now uses one exact-money ledger for income, expenses, budgets, charts and cash flow. Transaction changes immediately affect every summary. Bills and debt payments have reversible ledger links, and financial writes are serialized per user to prevent duplicate concurrent payments or conflicting restore/import operations.

Net worth now uses a dated starting cash balance, cash movements, portfolio holdings and outstanding debt. Negative monthly cash flow remains visible. Savings contributions are tracked without counting the same asset twice. Investment transfers change cash without inflating everyday spending. Latest-month charts and the 12-month scenario align income/expense records by month; known recurring bills are included in the scenario.

Authentication now uses salted scrypt hashes, database-backed attempt limits, CSRF-protected POST actions, recovery codes, hardened cookies and session invalidation after credential changes. Existing PINs remain usable for sign-in and password upgrade. User-entered names are safely rendered; static assets are the only offline cache entries. Financial pages and APIs use no-store, and offline navigation shows a reconnect screen.

Guided setup, quick transaction entry, search, reviewed CSV import with duplicate detection, complete JSON backup/restore and before-restore safety copies are implemented. The backend is split into authentication, ledger, reporting, data tools, shared finance and migration modules. Dependencies and chart assets are pinned, production debug is off, and README/project instructions describe the actual Flask application.

## Visual review

Reviewed 14 populated financial/settings screens at 1440, 390 and 320 pixels wide, plus sign-in, registration and recovery screens at desktop/mobile sizes. Inspected screenshots of the dashboard, transactions, projections, settings, savings, debt and registration directly.

Fixed wrapping summary amounts, mobile table layout, chart sizing, field labels, contrast, touch targets and goal progress styling. Dialogs support keyboard focus, Escape, focus restoration and reduced motion. The interaction review found and fixed an immediate-Escape timing issue that could leave an overlay open. Verified edit dialogs for bills, holdings, goals and debt, the debt calculator, investment transfer entry, dashboard errors/retry, text escaping, static-only caches and offline navigation.

Local screenshots and the machine-readable report are under `.qa/screenshots/` (ignored because they are generated test artifacts). The final browser pass reports 42 page/viewport checks, no JavaScript errors and no detected overflow or unlabelled fields. Six additional authentication screenshots are included.

## Validation and deployment limits

All 28 regression tests pass. The suite covers ledger edits/deletions, exact cents, negative cash flow, payment reversals, concurrent bill payments, investment transfers, user isolation, credential upgrade/recovery, request protection, import confirmation/duplicates, backup round trips, snapshots, fractional unit prices, exports and PostgreSQL-style numeric result values.

A read-only migration review migrated a consistent copy of the existing local database twice, reconciled nine category/month totals, checked SQLite integrity/foreign keys and confirmed the original database file was unchanged. First production use migrates automatically; original summaries are retained and local pre-migration backups are saved.

Live PostgreSQL integration and deployment were not performed. Before deploying, test the migration against a production snapshot, configure a strong production SECRET_KEY and HTTPS, and configure/verify scheduled host database backups. Legacy reconciliation preserves old summary totals; it cannot establish which conflicting historic entry was correct. Portfolio values remain manually entered, currency settings change symbols without conversion, and forecasts are stated scenarios rather than predictions.
