"""
Multi-Tenant Subdomain Router & Preconfigured Dashboard Manager
Enables multi-user/multi-tenant automatic resolution, isolated dashboard
profiles, and preconfigured persona views based on subdomains or user profiles.
"""

import os
import json
from core.database import get_connection

PRECONFIGURED_DASHBOARDS = {
    "devops": {
        "id": "devops",
        "name": "DevOps & Infrastructure",
        "badge": "DevOps",
        "theme": "amber",
        "description": "System resources, daemon health, scaling thresholds, and service lifecycle",
        "visible_tabs": ["overview", "scaling", "services", "logs", "terminal", "ssh_keys"],
        "default_tab": "overview"
    },
    "security": {
        "id": "security",
        "name": "Security & Vulnerability Auditor",
        "badge": "SecOps",
        "theme": "rose",
        "description": "Hardcoded secrets detection, static code auditing, IP whitelisting, and SSH authorization",
        "visible_tabs": ["security", "ssh_keys", "ip_whitelist", "audit_logs"],
        "default_tab": "security"
    },
    "ai_engineer": {
        "id": "ai_engineer",
        "name": "AI & Model Self-Improvement",
        "badge": "AI Lab",
        "theme": "indigo",
        "description": "Model dispatch routing, Ollama benchmark scores, prompt templates, and reflexion iterations",
        "visible_tabs": ["models", "benchmarks", "self_improve", "tasks"],
        "default_tab": "models"
    },
    "developer": {
        "id": "developer",
        "name": "Autonomous Code & Database Engine",
        "badge": "Dev",
        "theme": "emerald",
        "description": "Interactive task dispatching, code generation, server file explorer, and SQL database studio",
        "visible_tabs": ["tasks", "code_engine", "file_explorer", "database_studio"],
        "default_tab": "tasks"
    },
    "full": {
        "id": "full",
        "name": "Unified Master Dashboard",
        "badge": "Admin",
        "theme": "cyan",
        "description": "Complete command center with all features and server administration tools",
        "visible_tabs": ["overview", "tasks", "security", "ssh_keys", "scaling", "models", "benchmarks", "self_improve", "file_explorer", "database_studio", "ip_whitelist", "audit_logs", "terminal"],
        "default_tab": "overview"
    }
}

RESERVED_SUBDOMAINS = {"www", "agent", "worker", "kokash", "api", "app", "localhost", "127", "100"}

def init_tenant_table():
    conn = get_connection()
    with conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subdomain TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            preset_dashboard TEXT DEFAULT 'full',
            allowed_paths TEXT, -- JSON array of allowed server paths
            custom_settings TEXT, -- JSON object
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

def resolve_tenant_from_request(headers: dict, query_params: dict = None) -> dict:
    init_tenant_table()
    query_params = query_params or {}
    
    # 1. Check query parameter override: ?tenant=devops
    explicit_tenant = query_params.get("tenant", [None])[0] or query_params.get("preset", [None])[0]
    
    # 2. Check Host header: e.g. devops.agent.thefluenthands.com or alice.worker.local
    host = headers.get("Host", "").split(":")[0].strip().lower()
    subdomain = None
    
    if explicit_tenant:
        subdomain = explicit_tenant.lower()
    elif host:
        parts = host.split(".")
        if len(parts) >= 3 and parts[0] not in RESERVED_SUBDOMAINS:
            subdomain = parts[0]
            
    if not subdomain:
        subdomain = "full"
        
    # Check if preset matches directly
    if subdomain in PRECONFIGURED_DASHBOARDS:
        preset = PRECONFIGURED_DASHBOARDS[subdomain]
        return {
            "subdomain": subdomain,
            "display_name": preset["name"],
            "preset": preset,
            "is_dynamic": False
        }
        
    # Check database for custom tenant or auto-provision
    conn = get_connection()
    row = conn.execute("SELECT * FROM tenants WHERE subdomain = ?", (subdomain,)).fetchone()
    if row:
        preset_id = row["preset_dashboard"]
        preset = PRECONFIGURED_DASHBOARDS.get(preset_id, PRECONFIGURED_DASHBOARDS["full"])
        return {
            "subdomain": row["subdomain"],
            "display_name": row["display_name"],
            "preset": preset,
            "allowed_paths": json.loads(row["allowed_paths"]) if row["allowed_paths"] else None,
            "is_dynamic": True
        }
        
    # Auto-provision new tenant profile
    default_preset = "developer"
    display_name = f"Workspace ({subdomain.capitalize()})"
    with conn:
        conn.execute("""
            INSERT INTO tenants (subdomain, display_name, preset_dashboard, allowed_paths)
            VALUES (?, ?, ?, ?)
        """, (subdomain, display_name, default_preset, json.dumps(["/var/www"])))
        
    return {
        "subdomain": subdomain,
        "display_name": display_name,
        "preset": PRECONFIGURED_DASHBOARDS[default_preset],
        "allowed_paths": ["/var/www"],
        "is_dynamic": True
    }
