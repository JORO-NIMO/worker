"""
SSH Key Authorization Manager for Autonomous Worker
Allows safe, audited management and authorization of SSH public keys
exclusively through the authenticated Web Dashboard.
"""

import os
import re
import hashlib
import base64
from datetime import datetime, timedelta
from core.database import get_connection, log_event

AUTHORIZED_KEYS_PATH = os.path.expanduser("~/.ssh/authorized_keys")
MARKER_PREFIX = "# [WORKER-SSH-GUARD]"

def ensure_ssh_dir():
    ssh_dir = os.path.dirname(AUTHORIZED_KEYS_PATH)
    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
    if not os.path.exists(AUTHORIZED_KEYS_PATH):
        with open(AUTHORIZED_KEYS_PATH, "w") as f:
            f.write("# Managed by Worker SSH Authorization Guard\n")
        os.chmod(AUTHORIZED_KEYS_PATH, 0o600)

def calculate_fingerprint(public_key_str: str) -> str:
    """Calculates standard SHA256 fingerprint from SSH public key."""
    parts = public_key_str.strip().split()
    if len(parts) < 2:
        raise ValueError("Invalid SSH public key format")
    key_bytes = base64.b64decode(parts[1])
    fp = hashlib.sha256(key_bytes).digest()
    return "SHA256:" + base64.b64encode(fp).decode("utf-8").rstrip("=")

def init_ssh_table():
    conn = get_connection()
    with conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS ssh_authorized_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL,
            public_key TEXT NOT NULL,
            key_type TEXT NOT NULL,
            fingerprint TEXT UNIQUE NOT NULL,
            comment TEXT,
            status TEXT DEFAULT 'active', -- 'active', 'revoked', 'expired'
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

def list_authorized_keys() -> list:
    init_ssh_table()
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, user_id, username, public_key, key_type, fingerprint, comment, status, expires_at, created_at
        FROM ssh_authorized_keys
        ORDER BY created_at DESC
    """).fetchall()
    
    keys = []
    now = datetime.utcnow()
    for r in rows:
        item = dict(r)
        if item.get("expires_at"):
            try:
                exp = datetime.strptime(item["expires_at"], "%Y-%m-%d %H:%M:%S")
                if exp < now and item["status"] == "active":
                    item["status"] = "expired"
            except Exception:
                pass
        keys.append(item)
    return keys

def authorize_ssh_key(username: str, public_key: str, comment: str = "", expires_days: int = 30, user_id: int = None) -> dict:
    ensure_ssh_dir()
    init_ssh_table()
    
    public_key = public_key.strip()
    match = re.match(r"^(ssh-(?:ed25519|rsa|dss)|ecdsa-sha2-[a-z0-9]+)\s+([A-Za-z0-9+/=]+)(?:\s+(.*))?$", public_key)
    if not match:
        raise ValueError("Unsupported or invalid SSH public key format")
    
    key_type = match.group(1)
    extracted_comment = match.group(3) or comment or f"{username}@{datetime.utcnow().strftime('%Y%m%d')}"
    fingerprint = calculate_fingerprint(public_key)
    
    expires_at = (datetime.utcnow() + timedelta(days=expires_days)).strftime("%Y-%m-%d %H:%M:%S") if expires_days > 0 else None
    
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO ssh_authorized_keys (user_id, username, public_key, key_type, fingerprint, comment, status, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                status = 'active',
                comment = excluded.comment,
                expires_at = excluded.expires_at
        """, (user_id, username, public_key, key_type, fingerprint, extracted_comment, expires_at))
    
    sync_to_authorized_keys_file()
    log_event("SSH_KEY_AUTHORIZED", f"Authorized SSH key {fingerprint} for user '{username}'", payload=json_payload(fingerprint, username, expires_at))
    
    return {
        "status": "success",
        "fingerprint": fingerprint,
        "key_type": key_type,
        "comment": extracted_comment,
        "expires_at": expires_at
    }

def revoke_ssh_key(key_id_or_fingerprint) -> bool:
    init_ssh_table()
    conn = get_connection()
    with conn:
        if str(key_id_or_fingerprint).isdigit():
            conn.execute("UPDATE ssh_authorized_keys SET status = 'revoked' WHERE id = ?", (int(key_id_or_fingerprint),))
        else:
            conn.execute("UPDATE ssh_authorized_keys SET status = 'revoked' WHERE fingerprint = ?", (str(key_id_or_fingerprint),))
            
    sync_to_authorized_keys_file()
    log_event("SSH_KEY_REVOKED", f"Revoked SSH key {key_id_or_fingerprint}")
    return True

def sync_to_authorized_keys_file():
    ensure_ssh_dir()
    init_ssh_table()
    conn = get_connection()
    active_rows = conn.execute("""
        SELECT id, username, public_key, fingerprint, expires_at
        FROM ssh_authorized_keys
        WHERE status = 'active'
    """).fetchall()
    
    now = datetime.utcnow()
    valid_keys = []
    for r in active_rows:
        is_valid = True
        if r["expires_at"]:
            try:
                exp = datetime.strptime(r["expires_at"], "%Y-%m-%d %H:%M:%S")
                if exp < now:
                    is_valid = False
            except Exception:
                pass
        if is_valid:
            valid_keys.append(r)
            
    # Preserve manually added keys that do not have our marker
    preserved_lines = []
    if os.path.exists(AUTHORIZED_KEYS_PATH):
        with open(AUTHORIZED_KEYS_PATH, "r") as f:
            lines = f.readlines()
        for line in lines:
            if not line.startswith(MARKER_PREFIX):
                preserved_lines.append(line)
                
    # Write back preserved keys + active managed keys
    with open(AUTHORIZED_KEYS_PATH, "w") as f:
        for pl in preserved_lines:
            f.write(pl)
        if preserved_lines and not preserved_lines[-1].endswith("\n"):
            f.write("\n")
            
        for k in valid_keys:
            f.write(f"{MARKER_PREFIX} id={k['id']} user={k['username']} fp={k['fingerprint']}\n")
            f.write(f"{k['public_key'].strip()}\n")
            
    os.chmod(AUTHORIZED_KEYS_PATH, 0o600)

def json_payload(fp, user, exp):
    import json
    return json.dumps({"fingerprint": fp, "user": user, "expires": exp})
