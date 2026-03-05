import sqlite3
from datetime import datetime, timedelta
from typing import Optional


class Database:
    def __init__(self, db_path: str = "finance.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initialize database tables."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
                emoji TEXT DEFAULT '📝',
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, name, type)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
                category TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Savings goals (multiple per user) + per-goal saved wallet.
        # Migration:
        # - Older versions used savings_goals(user_id PRIMARY KEY, ...) for a single goal.
        # - New schema uses an autoincrement id and saved_amount.
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='savings_goals'")
        has_goals_table = cursor.fetchone() is not None
        if not has_goals_table:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS savings_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    target_amount REAL NOT NULL,
                    saved_amount REAL NOT NULL DEFAULT 0,
                    due_date TEXT NOT NULL,
                    name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_savings_goals_user_id ON savings_goals(user_id)")
        else:
            cursor.execute("PRAGMA table_info(savings_goals)")
            cols = cursor.fetchall()
            col_names = [c[1] for c in cols]
            has_id = "id" in col_names
            has_saved_amount = "saved_amount" in col_names

            # If this is the old single-goal table (no id), migrate to new schema.
            if not has_id:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS savings_goals_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        target_amount REAL NOT NULL,
                        saved_amount REAL NOT NULL DEFAULT 0,
                        due_date TEXT NOT NULL,
                        name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    )
                """)
                # Copy existing goals (saved_amount starts at 0).
                cursor.execute("""
                    INSERT INTO savings_goals_new (user_id, target_amount, saved_amount, due_date, name, created_at, updated_at)
                    SELECT user_id, target_amount, 0, due_date, name, created_at, updated_at
                    FROM savings_goals
                """)
                cursor.execute("DROP TABLE savings_goals")
                cursor.execute("ALTER TABLE savings_goals_new RENAME TO savings_goals")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_savings_goals_user_id ON savings_goals(user_id)")
            else:
                # Table already has id; ensure saved_amount exists.
                if not has_saved_amount:
                    cursor.execute("ALTER TABLE savings_goals ADD COLUMN saved_amount REAL NOT NULL DEFAULT 0")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_savings_goals_user_id ON savings_goals(user_id)")

        conn.commit()
        conn.close()

    @staticmethod
    def _to_sqlite_dt(dt: datetime) -> str:
        """Convert datetime to SQLite-compatible text datetime."""
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def add_user(self, user_id: int, username: Optional[str], first_name: Optional[str]):
        """Add or update user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
        """, (user_id, username, first_name))
        conn.commit()
        conn.close()

    def add_transaction(self, user_id: int, amount: float, trans_type: str,
                        category: Optional[str] = None, description: Optional[str] = None):
        """Add a new transaction (income or expense)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transactions (user_id, amount, type, category, description)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, amount, trans_type, category, description))
        conn.commit()
        trans_id = cursor.lastrowid
        conn.close()
        return trans_id

    def get_transactions(self, user_id: int, trans_type: Optional[str] = None,
                         days: Optional[int] = None, limit: int = 10):
        """Get transactions with optional filters."""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = "SELECT id, amount, type, category, description, created_at FROM transactions WHERE user_id = ?"
        params = [user_id]

        if trans_type:
            query += " AND type = ?"
            params.append(trans_type)

        if days:
            date_threshold = datetime.now() - timedelta(days=days)
            query += " AND datetime(created_at) >= datetime(?)"
            params.append(self._to_sqlite_dt(date_threshold))

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row[0],
                "amount": row[1],
                "type": row[2],
                "category": row[3],
                "description": row[4],
                "created_at": row[5]
            }
            for row in rows
        ]

    def delete_transaction(self, user_id: int, trans_id: int) -> bool:
        """Delete a transaction by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM transactions WHERE id = ? AND user_id = ?
        """, (trans_id, user_id))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_summary(self, user_id: int, days: Optional[int] = None):
        """Get financial summary (total income, expenses, balance)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        date_filter = ""
        params = [user_id]

        if days:
            date_threshold = datetime.now() - timedelta(days=days)
            date_filter = " AND datetime(created_at) >= datetime(?)"
            params.append(self._to_sqlite_dt(date_threshold))

        # Get total income
        cursor.execute(f"""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE user_id = ? AND type = 'income'{date_filter}
        """, params)
        total_income = cursor.fetchone()[0]

        # Get total expenses
        cursor.execute(f"""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE user_id = ? AND type = 'expense'{date_filter}
        """, params)
        total_expense = cursor.fetchone()[0]

        conn.close()

        return {
            "income": total_income,
            "expense": total_expense,
            "balance": total_income - total_expense
        }

    def get_category_breakdown(self, user_id: int, trans_type: str, days: Optional[int] = None):
        """Get spending/income breakdown by category."""
        conn = self._get_connection()
        cursor = conn.cursor()

        date_filter = ""
        params = [user_id, trans_type]

        if days:
            date_threshold = datetime.now() - timedelta(days=days)
            date_filter = " AND datetime(created_at) >= datetime(?)"
            params.append(self._to_sqlite_dt(date_threshold))

        cursor.execute(f"""
            SELECT COALESCE(category, 'Uncategorized'), SUM(amount), COUNT(*)
            FROM transactions
            WHERE user_id = ? AND type = ?{date_filter}
            GROUP BY category
            ORDER BY SUM(amount) DESC
        """, params)

        rows = cursor.fetchall()
        conn.close()

        return [
            {"category": row[0], "total": row[1], "count": row[2]}
            for row in rows
        ]

    def add_category(self, user_id: int, name: str, cat_type: str, emoji: str = "📝"):
        """Add a custom category."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO categories (user_id, name, type, emoji)
                VALUES (?, ?, ?, ?)
            """, (user_id, name, cat_type, emoji))
            conn.commit()
            success = True
        except sqlite3.IntegrityError:
            success = False
        conn.close()
        return success

    def get_categories(self, user_id: int, cat_type: Optional[str] = None):
        """Get user's custom categories."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if cat_type:
            cursor.execute("""
                SELECT name, type, emoji FROM categories
                WHERE user_id = ? AND type = ?
                ORDER BY name
            """, (user_id, cat_type))
        else:
            cursor.execute("""
                SELECT name, type, emoji FROM categories
                WHERE user_id = ?
                ORDER BY type, name
            """, (user_id,))

        rows = cursor.fetchall()
        conn.close()

        return [{"name": row[0], "type": row[1], "emoji": row[2]} for row in rows]

    def get_summary_range(self, user_id: int, start: datetime, end: datetime):
        """Get financial summary between [start, end)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_s = self._to_sqlite_dt(start)
        end_s = self._to_sqlite_dt(end)

        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE user_id = ? AND type = 'income'
              AND datetime(created_at) >= datetime(?)
              AND datetime(created_at) < datetime(?)
        """, (user_id, start_s, end_s))
        income = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE user_id = ? AND type = 'expense'
              AND datetime(created_at) >= datetime(?)
              AND datetime(created_at) < datetime(?)
        """, (user_id, start_s, end_s))
        expense = cursor.fetchone()[0]

        conn.close()
        return {"income": income, "expense": expense, "balance": income - expense}

    def get_category_breakdown_range(self, user_id: int, trans_type: str, start: datetime, end: datetime):
        """Get category breakdown between [start, end)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_s = self._to_sqlite_dt(start)
        end_s = self._to_sqlite_dt(end)

        cursor.execute("""
            SELECT COALESCE(category, 'Uncategorized'), SUM(amount), COUNT(*)
            FROM transactions
            WHERE user_id = ? AND type = ?
              AND datetime(created_at) >= datetime(?)
              AND datetime(created_at) < datetime(?)
            GROUP BY category
            ORDER BY SUM(amount) DESC
        """, (user_id, trans_type, start_s, end_s))

        rows = cursor.fetchall()
        conn.close()
        return [{"category": row[0], "total": row[1], "count": row[2]} for row in rows]

    def create_goal(self, user_id: int, target_amount: float, due_date: str, name: Optional[str] = None) -> int:
        """Create a new savings goal and return its id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO savings_goals (user_id, target_amount, saved_amount, due_date, name)
            VALUES (?, ?, 0, ?, ?)
        """, (user_id, target_amount, due_date, name))
        conn.commit()
        goal_id = cursor.lastrowid
        conn.close()
        return goal_id

    def list_goals(self, user_id: int):
        """List all goals for a user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, target_amount, saved_amount, due_date, name, created_at, updated_at
            FROM savings_goals
            WHERE user_id = ?
            ORDER BY datetime(due_date) ASC, id ASC
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "target_amount": r[1],
                "saved_amount": r[2],
                "due_date": r[3],
                "name": r[4],
                "created_at": r[5],
                "updated_at": r[6],
            }
            for r in rows
        ]

    def get_goal(self, user_id: int, goal_id: int):
        """Fetch a specific goal by id (scoped to user)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, target_amount, saved_amount, due_date, name, created_at, updated_at
            FROM savings_goals
            WHERE user_id = ? AND id = ?
        """, (user_id, goal_id))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "target_amount": row[1],
            "saved_amount": row[2],
            "due_date": row[3],
            "name": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }

    def delete_goal(self, user_id: int, goal_id: int) -> bool:
        """Delete a goal by id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM savings_goals WHERE user_id = ? AND id = ?", (user_id, goal_id))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_total_saved(self, user_id: int) -> float:
        """Sum of saved_amount across all goals for a user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(saved_amount), 0)
            FROM savings_goals
            WHERE user_id = ?
        """, (user_id,))
        total = cursor.fetchone()[0]
        conn.close()
        return float(total or 0)

    def adjust_goal_saved_amount(self, user_id: int, goal_id: int, delta: float) -> bool:
        """
        Add/subtract from a goal's saved wallet.
        Returns False if goal not found or would go negative.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE savings_goals
            SET saved_amount = saved_amount + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND id = ?
              AND (saved_amount + ?) >= 0
        """, (delta, user_id, goal_id, delta))
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return updated
