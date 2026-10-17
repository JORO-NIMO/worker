import sqlite3
import json
import os
import time
import hashlib
import secrets
import ipaddress
from datetime import datetime, timedelta

DB_PATH = os.environ.get("WORKER_DB_PATH", "/var/www/worker/data/worker.db")

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

# --- Security & Password Utilities ---

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return pwd_hash, salt

def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    pwd_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(pwd_hash, expected_hash)

# --- Schema Initialization ---

def init_db():
    conn = get_connection()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS allowed_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_or_cidr TEXT UNIQUE NOT NULL,
            label TEXT,
            is_active INTEGER DEFAULT 1,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            type TEXT NOT NULL, -- 'code', 'security_audit', 'database', 'scale', 'self_improve', 'general'
            priority INTEGER DEFAULT 10,
            status TEXT NOT NULL DEFAULT 'pending',
            prompt TEXT NOT NULL,
            context TEXT,
            result TEXT,
            error TEXT,
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            model_used TEXT NOT NULL,
            thought_process TEXT,
            output TEXT,
            exit_code INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS vulnerabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            line_number INTEGER,
            severity TEXT NOT NULL,
            vuln_type TEXT NOT NULL,
            description TEXT NOT NULL,
            fix_proposal TEXT,
            status TEXT DEFAULT 'open',
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS system_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cpu_load TEXT,
            ram_used_mb INTEGER,
            ram_total_mb INTEGER,
            swap_used_mb INTEGER,
            disk_used_percent REAL,
            active_model TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            ip_address TEXT,
            payload TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Self-Improvement & Benchmark Tables
        CREATE TABLE IF NOT EXISTS model_benchmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            benchmark_category TEXT NOT NULL, -- 'code_syntax', 'algorithms', 'sql_generation', 'error_reflection', 'reasoning'
            score REAL NOT NULL,
            total_tests INTEGER NOT NULL,
            pass_rate REAL NOT NULL,
            duration_ms INTEGER DEFAULT 0,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS self_improvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iteration INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            focus_area TEXT NOT NULL,
            before_score REAL,
            after_score REAL,
            optimizations_applied TEXT,
            status TEXT DEFAULT 'completed',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT UNIQUE NOT NULL,
            template_name TEXT NOT NULL,
            template_text TEXT NOT NULL,
            success_rate REAL DEFAULT 1.0,
            is_active INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks (status, priority, created_at);
        CREATE INDEX IF NOT EXISTS idx_vuln_status ON vulnerabilities (status);
        CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions (token);
        CREATE INDEX IF NOT EXISTS idx_benchmarks_model ON model_benchmarks (model_name, timestamp);
        """)

    # Run auto-migrations for existing tables
    try:
        conn.execute("ALTER TABLE audit_logs ADD COLUMN ip_address TEXT;")
    except sqlite3.OperationalError:
        pass

    # Seed default admin user if not exists
    ensure_default_admin()
    # Seed default trusted IP networks (loopback, local LAN, Tailscale)
    seed_default_allowed_ips()
    conn.close()

def ensure_default_admin(username="admin", default_pass="admin_safespaces_2026!"):
    conn = get_connection()
    with conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            pwd_hash, salt = hash_password(default_pass)
            conn.execute(
                """INSERT INTO users (username, password_hash, salt, role)
                   VALUES (?, ?, ?, 'admin')""",
                (username, pwd_hash, salt)
            )
            print(f"[Database] Initialized default admin user '{username}'.")
    conn.close()

def seed_default_allowed_ips():
    default_allowed = [
        ("127.0.0.1", "Localhost Loopback IPv4"),
        ("::1", "Localhost Loopback IPv6"),
        ("192.168.18.0/24", "Local Management LAN Subnet"),
        ("100.64.0.0/10", "Tailscale CGNAT Subnet"),
        ("172.16.0.0/12", "Docker Internal Subnets"),
        ("10.0.0.0/8", "Internal Private Subnet")
    ]
    conn = get_connection()
    with conn:
        for cidr, label in default_allowed:
            conn.execute(
                """INSERT OR IGNORE INTO allowed_ips (ip_or_cidr, label, is_active)
                   VALUES (?, ?, 1)""",
                (cidr, label)
            )
    conn.close()

# --- User & Session Authentication ---

def authenticate_user(username, password):
    conn = get_connection()
    user_data = None
    with conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row and verify_password(password, row["salt"], row["password_hash"]):
            conn.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
            user_data = dict(row)
            del user_data["password_hash"]
            del user_data["salt"]
    conn.close()
    return user_data

def create_session(user_id, username, ip_address="", user_agent=""):
    token = secrets.token_hex(32)
    expires_at = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO sessions (token, user_id, username, ip_address, user_agent, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token, user_id, username, ip_address, user_agent, expires_at)
        )
    conn.close()
    return token

def validate_session(token):
    if not token:
        return None
    conn = get_connection()
    session_data = None
    with conn:
        row = conn.execute(
            """SELECT s.*, u.role FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.token = ? AND s.expires_at > CURRENT_TIMESTAMP""",
            (token,)
        ).fetchone()
        if row:
            session_data = dict(row)
    conn.close()
    return session_data

def destroy_session(token):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.close()

def update_user_password(user_id, new_password):
    pwd_hash, salt = hash_password(new_password)
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE users SET password_hash = ?, salt = ? WHERE id = ?""",
            (pwd_hash, salt, user_id)
        )
        # Invalidate active sessions
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.close()

# --- IP Whitelist Validation ---

def get_allowed_ips():
    conn = get_connection()
    with conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM allowed_ips ORDER BY id ASC").fetchall()]
    conn.close()
    return rows

def add_allowed_ip(ip_or_cidr, label=""):
    ip_str = ip_or_cidr.strip()
    # Validate IP or CIDR format
    try:
        if "/" in ip_str:
            ipaddress.ip_network(ip_str, strict=False)
        else:
            ipaddress.ip_address(ip_str)
    except ValueError as e:
        raise ValueError(f"Invalid IP address or CIDR format: {e}")

    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO allowed_ips (ip_or_cidr, label, is_active)
               VALUES (?, ?, 1)""",
            (ip_str, label)
        )
    conn.close()

def remove_allowed_ip(ip_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM allowed_ips WHERE id = ?", (ip_id,))
    conn.close()

def is_ip_allowed(client_ip: str) -> bool:
    if not client_ip:
        return False
    try:
        target = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    allowed_list = get_allowed_ips()
    for item in allowed_list:
        if not item.get("is_active"):
            continue
        rule_str = item["ip_or_cidr"]
        try:
            if "/" in rule_str:
                net = ipaddress.ip_network(rule_str, strict=False)
                if target in net:
                    return True
            else:
                addr = ipaddress.ip_address(rule_str)
                if target == addr:
                    return True
        except ValueError:
            continue
    return False

# --- Task Execution & Logging ---

def create_task(title, task_type, prompt, context="", priority=10, max_retries=3):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO tasks (title, type, prompt, context, priority, max_retries, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (title, task_type, prompt, context, priority, max_retries)
        )
        task_id = cur.lastrowid
    conn.close()
    return task_id

def get_next_pending_task():
    conn = get_connection()
    with conn:
        row = conn.execute(
            """SELECT * FROM tasks
               WHERE status = 'pending'
               ORDER BY priority ASC, created_at ASC
               LIMIT 1"""
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE tasks SET status = 'running', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (row["id"],)
            )
    conn.close()
    return dict(row) if row else None

def complete_task(task_id, result):
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE tasks
               SET status = 'completed', result = ?, error = NULL, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (result, task_id)
        )
    conn.close()

def fail_task(task_id, error, retry=True):
    conn = get_connection()
    with conn:
        row = conn.execute("SELECT retry_count, max_retries FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row:
            retry_count = row["retry_count"] + 1
            status = "pending" if (retry and retry_count < row["max_retries"]) else "failed"
            conn.execute(
                """UPDATE tasks
                   SET status = ?, error = ?, retry_count = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (status, error, retry_count, task_id)
            )
    conn.close()

def record_task_run(task_id, model_used, thought_process, output, exit_code=0, duration_ms=0):
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO task_runs (task_id, model_used, thought_process, output, exit_code, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (task_id, model_used, thought_process, output, exit_code, duration_ms)
        )
    conn.close()

def log_event(event_type, message, payload=None, ip_address=None):
    payload_str = json.dumps(payload) if isinstance(payload, (dict, list)) else (str(payload) if payload else None)
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO audit_logs (event_type, message, ip_address, payload)
               VALUES (?, ?, ?, ?)""",
            (event_type, message, ip_address, payload_str)
        )
    conn.close()

def record_vulnerability(project_name, file_path, line_number, severity, vuln_type, description, fix_proposal=""):
    conn = get_connection()
    with conn:
        existing = conn.execute(
            """SELECT id FROM vulnerabilities
               WHERE project_name = ? AND file_path = ? AND line_number = ? AND vuln_type = ? AND status = 'open'""",
            (project_name, file_path, line_number, vuln_type)
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO vulnerabilities (project_name, file_path, line_number, severity, vuln_type, description, fix_proposal)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_name, file_path, line_number, severity, vuln_type, description, fix_proposal)
            )
    conn.close()

def record_metrics(cpu_load, ram_used_mb, ram_total_mb, swap_used_mb, disk_used_percent, active_model=""):
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO system_metrics (cpu_load, ram_used_mb, ram_total_mb, swap_used_mb, disk_used_percent, active_model)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cpu_load, ram_used_mb, ram_total_mb, swap_used_mb, disk_used_percent, active_model)
        )
    conn.close()


# --- Model Self-Improvement & Benchmarks ---

def record_benchmark_result(model_name, category, score, total_tests, pass_rate, duration_ms=0, details=None):
    details_str = json.dumps(details) if isinstance(details, (dict, list)) else (details or "")
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO model_benchmarks (model_name, benchmark_category, score, total_tests, pass_rate, duration_ms, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (model_name, category, score, total_tests, pass_rate, duration_ms, details_str)
        )
    conn.close()

def get_benchmark_history(limit=25):
    conn = get_connection()
    with conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT * FROM model_benchmarks ORDER BY id DESC LIMIT ?""",
            (limit,)
        ).fetchall()]
    conn.close()
    return rows

def record_self_improvement(iteration, model_name, focus_area, before_score, after_score, optimizations, status="completed"):
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO self_improvements (iteration, model_name, focus_area, before_score, after_score, optimizations_applied, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (iteration, model_name, focus_area, before_score, after_score, optimizations, status)
        )
    conn.close()

def get_self_improvements(limit=20):
    conn = get_connection()
    with conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT * FROM self_improvements ORDER BY id DESC LIMIT ?""",
            (limit,)
        ).fetchall()]
    conn.close()
    return rows

# --- Database Explorer Utilities ---

def list_tables():
    conn = get_connection()
    with conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC"
        ).fetchall()
        tables = [r["name"] for r in rows]
    conn.close()
    return tables

def get_table_schema(table_name):
    conn = get_connection()
    with conn:
        rows = [dict(r) for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
    conn.close()
    return rows

def get_table_data(table_name, limit=50, offset=0):
    conn = get_connection()
    with conn:
        total = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table_name} ORDER BY 1 DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()]
    conn.close()
    return {"total": total, "rows": rows}

def execute_custom_sql(query):
    query_clean = query.strip()
    # Security guard: disallow destructive database drop commands via web
    disallowed = ["DROP DATABASE", "ATTACH", "DETACH"]
    for d in disallowed:
        if d in query_clean.upper():
            raise ValueError(f"Executing '{d}' is strictly forbidden via Web Explorer.")

    conn = get_connection()
    result = None
    with conn:
        cur = conn.execute(query_clean)
        if query_clean.upper().startswith("SELECT") or query_clean.upper().startswith("PRAGMA"):
            rows = [dict(r) for r in cur.fetchall()]
            result = {"type": "read", "rows": rows, "count": len(rows)}
        else:
            affected = cur.rowcount
            result = {"type": "write", "affected_rows": affected}
    conn.close()
    return result

# --- Comprehensive Dashboard Aggregation ---

def get_dashboard_data():
    conn = get_connection()
    stats = {}
    with conn:
        stats["pending_tasks"] = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'").fetchone()[0]
        stats["running_tasks"] = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'running'").fetchone()[0]
        stats["completed_tasks"] = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'").fetchone()[0]
        stats["failed_tasks"] = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'failed'").fetchone()[0]
        stats["open_vulns"] = conn.execute("SELECT COUNT(*) FROM vulnerabilities WHERE status = 'open'").fetchone()[0]
        stats["total_evals"] = conn.execute("SELECT COUNT(*) FROM model_benchmarks").fetchone()[0]
        stats["improvements_count"] = conn.execute("SELECT COUNT(*) FROM self_improvements").fetchone()[0]
        
        recent_tasks = [dict(r) for r in conn.execute(
            "SELECT id, title, type, status, priority, created_at, updated_at FROM tasks ORDER BY id DESC LIMIT 15"
        ).fetchall()]
        
        vulns = [dict(r) for r in conn.execute(
            "SELECT * FROM vulnerabilities WHERE status = 'open' ORDER BY id DESC LIMIT 10"
        ).fetchall()]

        benchmarks = [dict(r) for r in conn.execute(
            "SELECT * FROM model_benchmarks ORDER BY id DESC LIMIT 6"
        ).fetchall()]

        improvements = [dict(r) for r in conn.execute(
            "SELECT * FROM self_improvements ORDER BY id DESC LIMIT 6"
        ).fetchall()]
        
        latest_metrics = conn.execute(
            "SELECT * FROM system_metrics ORDER BY id DESC LIMIT 1"
        ).fetchone()
        stats["metrics"] = dict(latest_metrics) if latest_metrics else {}
        
    conn.close()
    return {
        "stats": stats,
        "recent_tasks": recent_tasks,
        "vulnerabilities": vulns,
        "benchmarks": benchmarks,
        "improvements": improvements
    }
