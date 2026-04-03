"""
db.py — Database abstraction layer.
Supports SQLite (local dev) and PostgreSQL (Railway / production).

When DATABASE_URL env var is set, PostgreSQL is used.
Otherwise, falls back to SQLite.
"""

import os
import sqlite3

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def _get_database_url():
    """Read DATABASE_URL at call time (not import time) so Railway vars are available."""
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class PgRowWrapper:
    """Make psycopg2 RealDictRow behave like sqlite3.Row (supports both
    dict-key access and integer-index access)."""

    def __init__(self, data: dict):
        self._data = data
        self._keys = list(data.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[self._keys[key]]
        return self._data[key]

    def keys(self):
        return self._keys

    def __contains__(self, key):
        return key in self._data

    def __repr__(self):
        return repr(self._data)


class PgCursorWrapper:
    """Wraps a psycopg2 cursor so SQL written with '?' placeholders works."""

    def __init__(self, real_cursor):
        self._cur = real_cursor

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        return self._cur.execute(sql, params)

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return PgRowWrapper(row)

    def fetchall(self):
        return [PgRowWrapper(r) for r in self._cur.fetchall()]

    @property
    def lastrowid(self):
        return self._cur.fetchone()[0] if self._cur.description else None

    def close(self):
        self._cur.close()


class PgConnectionWrapper:
    """Wraps a psycopg2 connection to feel like sqlite3 connection."""

    def __init__(self, real_conn):
        self._conn = real_conn

    def cursor(self):
        return PgCursorWrapper(
            self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        )

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ─── Public API ───────────────────────────────

def get_db():
    """Return a DB connection (PostgreSQL or SQLite)."""
    url = _get_database_url()
    if url and HAS_PSYCOPG2:
        conn = psycopg2.connect(url)
        return PgConnectionWrapper(conn)
    else:
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        return conn


def is_postgres():
    return bool(_get_database_url() and HAS_PSYCOPG2)


def init_db():
    """Create all tables if they don't yet exist."""
    try:
        conn = get_db()
        c = conn.cursor()

        if is_postgres():
            print("[DB] Using PostgreSQL:", _get_database_url()[:30] + "...")
            _init_postgres(c)
        else:
            print("[DB] Using SQLite: database.db")
            _init_sqlite(c)

        conn.commit()
        conn.close()
        print("[OK] Database initialized successfully.")
    except Exception as e:
        print(f"[ERROR] Database initialization failed: {e}")
        raise


def _init_sqlite(c):
    """SQLite table definitions (AUTOINCREMENT)."""

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    UNIQUE NOT NULL,
            password        TEXT    NOT NULL,
            currency        TEXT    DEFAULT '£',
            security_answer TEXT    DEFAULT '',
            created         TEXT    DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS income (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            month      TEXT    NOT NULL,
            salary     REAL    DEFAULT 0,
            bonus      REAL    DEFAULT 0,
            side       REAL    DEFAULT 0,
            rental     REAL    DEFAULT 0,
            dividends  REAL    DEFAULT 0,
            gifts      REAL    DEFAULT 0,
            other      REAL    DEFAULT 0,
            date_added TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            month         TEXT    NOT NULL,
            utilities     REAL    DEFAULT 0,
            groceries     REAL    DEFAULT 0,
            dining_out    REAL    DEFAULT 0,
            transport     REAL    DEFAULT 0,
            shopping      REAL    DEFAULT 0,
            healthcare    REAL    DEFAULT 0,
            entertainment REAL    DEFAULT 0,
            personal_care REAL    DEFAULT 0,
            other         REAL    DEFAULT 0,
            date_added    TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS recurring (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            name       TEXT    NOT NULL,
            category   TEXT    NOT NULL,
            amount     REAL    NOT NULL,
            due_day    INTEGER NOT NULL,
            notes      TEXT,
            date_added TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS savings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            month      TEXT    NOT NULL,
            amount     REAL    DEFAULT 0,
            investment REAL    DEFAULT 0,
            type       TEXT,
            notes      TEXT,
            date_added TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS savings_goals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            name        TEXT    NOT NULL,
            target      REAL    NOT NULL,
            saved       REAL    DEFAULT 0,
            deadline    TEXT,
            date_added  TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS credit_cards (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            name       TEXT    NOT NULL,
            rate       REAL    NOT NULL,
            balance    REAL    NOT NULL,
            date_added TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS loans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            name       TEXT    NOT NULL,
            rate       REAL    NOT NULL,
            balance    REAL    NOT NULL,
            date_added TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS foreign_shares (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            name           TEXT    NOT NULL,
            units          REAL    NOT NULL,
            price_per_unit REAL    NOT NULL,
            date_bought    TEXT,
            date_added     TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS budget_limits (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            category      TEXT    NOT NULL,
            monthly_limit REAL    DEFAULT 0,
            UNIQUE(user_id, category),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER UNIQUE NOT NULL,
            first_name  TEXT    DEFAULT '',
            last_name   TEXT    DEFAULT '',
            email       TEXT    DEFAULT '',
            phone       TEXT    DEFAULT '',
            date_of_birth TEXT,
            country     TEXT    DEFAULT '',
            bio         TEXT    DEFAULT '',
            updated_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            type        TEXT    NOT NULL,
            category    TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            amount      REAL    NOT NULL,
            date_added  TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS net_worth_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            month           TEXT    NOT NULL,
            total_income    REAL    DEFAULT 0,
            total_expenses  REAL    DEFAULT 0,
            total_savings   REAL    DEFAULT 0,
            total_debt      REAL    DEFAULT 0,
            net_worth       REAL    DEFAULT 0,
            health_score    INTEGER DEFAULT 0,
            recorded_at     TEXT    DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, month),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')


def _init_postgres(c):
    """PostgreSQL table definitions (SERIAL, DOUBLE PRECISION)."""

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id              SERIAL PRIMARY KEY,
            username        TEXT   UNIQUE NOT NULL,
            password        TEXT   NOT NULL,
            currency        TEXT   DEFAULT '£',
            security_answer TEXT   DEFAULT '',
            created         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS income (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            month      TEXT    NOT NULL,
            salary     DOUBLE PRECISION DEFAULT 0,
            bonus      DOUBLE PRECISION DEFAULT 0,
            side       DOUBLE PRECISION DEFAULT 0,
            rental     DOUBLE PRECISION DEFAULT 0,
            dividends  DOUBLE PRECISION DEFAULT 0,
            gifts      DOUBLE PRECISION DEFAULT 0,
            other      DOUBLE PRECISION DEFAULT 0,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id            SERIAL PRIMARY KEY,
            user_id       INTEGER NOT NULL REFERENCES users(id),
            month         TEXT    NOT NULL,
            utilities     DOUBLE PRECISION DEFAULT 0,
            groceries     DOUBLE PRECISION DEFAULT 0,
            dining_out    DOUBLE PRECISION DEFAULT 0,
            transport     DOUBLE PRECISION DEFAULT 0,
            shopping      DOUBLE PRECISION DEFAULT 0,
            healthcare    DOUBLE PRECISION DEFAULT 0,
            entertainment DOUBLE PRECISION DEFAULT 0,
            personal_care DOUBLE PRECISION DEFAULT 0,
            other         DOUBLE PRECISION DEFAULT 0,
            date_added    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS recurring (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            name       TEXT    NOT NULL,
            category   TEXT    NOT NULL,
            amount     DOUBLE PRECISION NOT NULL,
            due_day    INTEGER NOT NULL,
            notes      TEXT,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS savings (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            month      TEXT    NOT NULL,
            amount     DOUBLE PRECISION DEFAULT 0,
            investment DOUBLE PRECISION DEFAULT 0,
            type       TEXT,
            notes      TEXT,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS savings_goals (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            name       TEXT    NOT NULL,
            target     DOUBLE PRECISION NOT NULL,
            saved      DOUBLE PRECISION DEFAULT 0,
            deadline   TEXT,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS credit_cards (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            name       TEXT    NOT NULL,
            rate       DOUBLE PRECISION NOT NULL,
            balance    DOUBLE PRECISION NOT NULL,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS loans (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            name       TEXT    NOT NULL,
            rate       DOUBLE PRECISION NOT NULL,
            balance    DOUBLE PRECISION NOT NULL,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS foreign_shares (
            id             SERIAL PRIMARY KEY,
            user_id        INTEGER NOT NULL REFERENCES users(id),
            name           TEXT    NOT NULL,
            units          DOUBLE PRECISION NOT NULL,
            price_per_unit DOUBLE PRECISION NOT NULL,
            date_bought    TEXT,
            date_added     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS budget_limits (
            id            SERIAL PRIMARY KEY,
            user_id       INTEGER NOT NULL REFERENCES users(id),
            category      TEXT    NOT NULL,
            monthly_limit DOUBLE PRECISION DEFAULT 0,
            UNIQUE(user_id, category)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER UNIQUE NOT NULL REFERENCES users(id),
            first_name  TEXT    DEFAULT '',
            last_name   TEXT    DEFAULT '',
            email       TEXT    DEFAULT '',
            phone       TEXT    DEFAULT '',
            date_of_birth TEXT,
            country     TEXT    DEFAULT '',
            bio         TEXT    DEFAULT '',
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            date        TEXT    NOT NULL,
            type        TEXT    NOT NULL,
            category    TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            amount      DOUBLE PRECISION NOT NULL,
            date_added  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS net_worth_history (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER NOT NULL REFERENCES users(id),
            month           TEXT    NOT NULL,
            total_income    DOUBLE PRECISION DEFAULT 0,
            total_expenses  DOUBLE PRECISION DEFAULT 0,
            total_savings   DOUBLE PRECISION DEFAULT 0,
            total_debt      DOUBLE PRECISION DEFAULT 0,
            net_worth       DOUBLE PRECISION DEFAULT 0,
            health_score    INTEGER DEFAULT 0,
            recorded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, month)
        )
    ''')
