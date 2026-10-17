import os
import sqlite3
import json

class DatabaseManager:
    """
    Manages SQLite databases, tables, migrations, and health checks across applications.
    """
    def __init__(self, allowed_roots=None):
        self.allowed_roots = allowed_roots or ["/var/www", "/home/ishabarundo"]

    def _is_allowed(self, db_path):
        real_path = os.path.realpath(db_path)
        for root in self.allowed_roots:
            if real_path.startswith(os.path.realpath(root)):
                return True
        return False

    def create_database(self, db_path, initial_schema_sql=None):
        if not self._is_allowed(db_path):
            return False, "Access denied: database path not permitted"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode = WAL;")
            if initial_schema_sql:
                conn.executescript(initial_schema_sql)
            conn.commit()
            conn.close()
            return True, f"Database created successfully at {db_path}"
        except Exception as e:
            return False, str(e)

    def execute_migration(self, db_path, migration_sql):
        if not self._is_allowed(db_path):
            return False, "Access denied: database path not permitted"
        if not os.path.exists(db_path):
            return False, f"Database file not found: {db_path}"
        try:
            conn = sqlite3.connect(db_path)
            with conn:
                conn.executescript(migration_sql)
            conn.close()
            return True, "Migration executed successfully"
        except Exception as e:
            return False, str(e)

    def get_schema(self, db_path):
        if not self._is_allowed(db_path) or not os.path.exists(db_path):
            return None, "Database not accessible"
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            tables = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            ).fetchall()
            schema = {row["name"]: row["sql"] for row in tables}
            conn.close()
            return schema, None
        except Exception as e:
            return None, str(e)

    def check_integrity(self, db_path):
        if not self._is_allowed(db_path) or not os.path.exists(db_path):
            return False, "Database not accessible"
        try:
            conn = sqlite3.connect(db_path)
            res = conn.execute("PRAGMA integrity_check;").fetchone()
            conn.close()
            is_ok = res and res[0] == "ok"
            return is_ok, res[0] if res else "Unknown"
        except Exception as e:
            return False, str(e)
