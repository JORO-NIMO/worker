import http.server
import socketserver
import json
import os
import urllib.parse
from core.database import (
    get_dashboard_data, create_task, authenticate_user, create_session,
    validate_session, destroy_session, get_allowed_ips, add_allowed_ip,
    remove_allowed_ip, update_user_password, list_tables, get_table_schema,
    get_table_data, execute_custom_sql, get_benchmark_history, get_self_improvements
)
from core.model_self_improvement import ModelSelfImprovementEngine
from web.security_middleware import (
    verify_request_access, parse_session_token, get_forbidden_html, extract_client_ip
)
from tools.ssh_manager import (
    list_authorized_keys, authorize_ssh_key, revoke_ssh_key, sync_to_authorized_keys_file
)
from tools.credential_guard import CredentialGuard
from web.tenant_manager import resolve_tenant_from_request, PRECONFIGURED_DASHBOARDS

PORT = 8888
CONFIG_PATH = os.environ.get("WORKER_CONFIG_PATH", "/var/www/worker/config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "security": {"enforce_ip_whitelist": True},
        "models": {"primary_coder": "qwen2.5-coder:1.5b", "reasoning": "deepseek-r1:7b"}
    }

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

def explore_server_path(target_path: str) -> dict:
    target_path = os.path.abspath(target_path)
    if not os.path.exists(target_path):
        return {"error": f"Path '{target_path}' does not exist on server", "path": target_path}

    presets = [
        {"name": "Sign Language Platform", "path": "/var/www/signlanguage"},
        {"name": "Agent Worker & Brain", "path": "/var/www/worker"},
        {"name": "Orchestrator Service", "path": "/opt/orchestrator"},
        {"name": "All Web Apps (/var/www)", "path": "/var/www"},
        {"name": "WordPress Site", "path": "/var/www/wordpress"},
        {"name": "Fastfats Repo", "path": "/var/www/Fastfats"},
        {"name": "Cloudflare Config", "path": "/etc/cloudflared"},
        {"name": "System Services (/etc/systemd/system)", "path": "/etc/systemd/system"},
        {"name": "User Home (/home/ishabarundo)", "path": "/home/ishabarundo"},
        {"name": "Root (/)", "path": "/"}
    ]
    valid_presets = [p for p in presets if os.path.exists(p["path"])]

    if os.path.isfile(target_path):
        size = os.path.getsize(target_path)
        content = ""
        is_text = False
        if size <= 500 * 1024:
            try:
                with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(25000)
                is_text = True
            except Exception:
                is_text = False
        return {
            "type": "file",
            "path": target_path,
            "name": os.path.basename(target_path),
            "parent": os.path.dirname(target_path),
            "size": size,
            "is_text": is_text,
            "preview": content,
            "presets": valid_presets
        }

    try:
        dirs = []
        files = []
        with os.scandir(target_path) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                    st = entry.stat(follow_symlinks=True)
                    item = {
                        "name": entry.name,
                        "path": os.path.join(target_path, entry.name),
                        "is_dir": is_dir,
                        "size": st.st_size if not is_dir else 0,
                        "modified": int(st.st_mtime)
                    }
                    if is_dir:
                        dirs.append(item)
                    else:
                        files.append(item)
                except (PermissionError, FileNotFoundError):
                    continue
        
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())

        parent = os.path.dirname(target_path)
        if target_path == "/":
            parent = None

        return {
            "type": "directory",
            "path": target_path,
            "parent": parent,
            "directories": dirs,
            "files": files,
            "presets": valid_presets
        }
    except PermissionError:
        return {"error": f"Permission denied accessing '{target_path}'", "path": target_path}
    except Exception as e:
        return {"error": str(e), "path": target_path}


def explore_server_path(target_path: str) -> dict:
    target_path = os.path.abspath(target_path)
    if not os.path.exists(target_path):
        return {"error": f"Path '{target_path}' does not exist on server", "path": target_path}

    presets = [
        {"name": "Sign Language Platform", "path": "/var/www/signlanguage"},
        {"name": "Agent Worker & Brain", "path": "/var/www/worker"},
        {"name": "Orchestrator Service", "path": "/opt/orchestrator"},
        {"name": "All Web Apps (/var/www)", "path": "/var/www"},
        {"name": "WordPress Site", "path": "/var/www/wordpress"},
        {"name": "Fastfats Repo", "path": "/var/www/Fastfats"},
        {"name": "Cloudflare Config", "path": "/etc/cloudflared"},
        {"name": "System Services (/etc/systemd/system)", "path": "/etc/systemd/system"},
        {"name": "User Home (/home/ishabarundo)", "path": "/home/ishabarundo"},
        {"name": "Root (/)", "path": "/"}
    ]
    valid_presets = [p for p in presets if os.path.exists(p["path"])]

    if os.path.isfile(target_path):
        size = os.path.getsize(target_path)
        content = ""
        is_text = False
        if size <= 500 * 1024:
            try:
                with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(25000)
                is_text = True
            except Exception:
                is_text = False
        return {
            "type": "file",
            "path": target_path,
            "name": os.path.basename(target_path),
            "parent": os.path.dirname(target_path),
            "size": size,
            "is_text": is_text,
            "preview": content,
            "presets": valid_presets
        }

    try:
        dirs = []
        files = []
        with os.scandir(target_path) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                    st = entry.stat(follow_symlinks=True)
                    item = {
                        "name": entry.name,
                        "path": os.path.join(target_path, entry.name),
                        "is_dir": is_dir,
                        "size": st.st_size if not is_dir else 0,
                        "modified": int(st.st_mtime)
                    }
                    if is_dir:
                        dirs.append(item)
                    else:
                        files.append(item)
                except (PermissionError, FileNotFoundError):
                    continue
        
        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())

        parent = os.path.dirname(target_path)
        if target_path == "/":
            parent = None

        return {
            "type": "directory",
            "path": target_path,
            "parent": parent,
            "directories": dirs,
            "files": files,
            "presets": valid_presets
        }
    except PermissionError:
        return {"error": f"Permission denied accessing '{target_path}'", "path": target_path}
    except Exception as e:
        return {"error": str(e), "path": target_path}


class AutonomousDashboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Concise logging to keep server quiet
        return

    def send_json(self, data, status=200, extra_headers=None):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def send_html(self, html_str, status=200, extra_headers=None):
        payload = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def check_access(self) -> tuple[bool, str, dict]:
        cfg = load_config()
        enforce_ip = cfg.get("security", {}).get("enforce_ip_whitelist", True)
        is_ip_ok, client_ip, reason = verify_request_access(self.headers, self.client_address, enforce_ip_whitelist=enforce_ip)
        
        token = parse_session_token(self.headers.get("Cookie", ""))
        session = validate_session(token) if token else None
        return is_ip_ok, client_ip, session

    def do_HEAD(self):
        # Handle HEAD requests cleanly (needed for Cloudflare and monitoring health checks)
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        is_ip_ok, client_ip, session = self.check_access()

        # 1. IP Whitelisting Check
        if not is_ip_ok:
            forbidden_page = get_forbidden_html(client_ip)
            return self.send_html(forbidden_page, status=403)

        # 2. Public Static / Auth routes
        if path == "/login":
            if session:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            return self.send_html(self.get_login_page(client_ip))

        if path == "/logout":
            token = parse_session_token(self.headers.get("Cookie", ""))
            if token:
                destroy_session(token)
            self.send_response(302)
            self.send_header("Set-Cookie", "session_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Location", "/login")
            self.end_headers()
            return

        # 3. Authentication Barrier for Protected Routes
        if not session:
            if path.startswith("/api/"):
                return self.send_json({"error": "Unauthorized", "detail": "Session required"}, status=401)
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        # 4. Protected API Endpoints
        if path == "/api/dashboard-data":
            data = get_dashboard_data()
            cfg = load_config()
            data["config"] = cfg
            data["user"] = {"username": session["username"], "role": session.get("role", "admin")}
            data["allowed_ips"] = get_allowed_ips()
            data["client_ip"] = client_ip
            return self.send_json(data)

        if path == "/api/benchmarks":
            history = get_benchmark_history()
            improvements = get_self_improvements()
            return self.send_json({"benchmarks": history, "improvements": improvements})

        if path == "/api/db/tables":
            tables = list_tables()
            return self.send_json({"tables": tables})

        if path == "/api/db/table":
            qs = urllib.parse.parse_qs(parsed.query)
            table_name = qs.get("name", ["tasks"])[0]
            limit = int(qs.get("limit", [50])[0])
            offset = int(qs.get("offset", [0])[0])
            schema = get_table_schema(table_name)
            data = get_table_data(table_name, limit, offset)
            return self.send_json({"table": table_name, "schema": schema, "data": data})

        if path == "/api/fs/explore":
            qs = urllib.parse.parse_qs(parsed.query)
            target_path = qs.get("path", ["/var/www"])[0]
            result = explore_server_path(target_path)
            return self.send_json(result)

        if path == "/api/fs/presets":
            result = explore_server_path("/var/www")
            return self.send_json({"presets": result.get("presets", [])})

        if path == "/api/fs/explore":
            qs = urllib.parse.parse_qs(parsed.query)
            target_path = qs.get("path", ["/var/www"])[0]
            result = explore_server_path(target_path)
            return self.send_json(result)

        if path == "/api/ssh/keys":
            keys = list_authorized_keys()
            return self.send_json({"keys": keys, "status": "success"})

        if path == "/api/security/guard-scan":
            guard = CredentialGuard(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
            findings = guard.scan_directory()
            return self.send_json({"findings": findings, "status": "success"})

        if path == "/api/tenant-info":
            tenant_info = resolve_tenant_from_request(dict(self.headers), urllib.parse.parse_qs(parsed.query))
            return self.send_json({"tenant": tenant_info, "available_presets": PRECONFIGURED_DASHBOARDS})

        # 5. Serve Main SPA Dashboard
        if path == "/" or path == "/index.html":
            return self.send_html(self.get_dashboard_page(session, client_ip))

        return self.send_json({"error": "Not Found"}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        is_ip_ok, client_ip, session = self.check_access()

        if not is_ip_ok:
            return self.send_html(get_forbidden_html(client_ip), status=403)

        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        
        try:
            body = json.loads(raw_body) if raw_body else {}
        except Exception:
            body = dict(urllib.parse.parse_qsl(raw_body))

        # Login Route
        if path == "/api/login":
            username = body.get("username", "").strip()
            password = body.get("password", "").strip()
            user = authenticate_user(username, password)
            if user:
                user_agent = self.headers.get("User-Agent", "")
                token = create_session(user["id"], user["username"], ip_address=client_ip, user_agent=user_agent)
                cookie = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800"
                return self.send_json({"status": "success", "username": user["username"]}, extra_headers={"Set-Cookie": cookie})
            else:
                return self.send_json({"status": "error", "message": "Invalid username or password."}, status=401)

        # Protected API Routes
        if not session:
            return self.send_json({"error": "Unauthorized"}, status=401)

        if path == "/api/tasks":
            title = body.get("title", "").strip()
            task_type = body.get("type", "general").strip()
            prompt = body.get("prompt", "").strip()
            context = body.get("context", "").strip()
            priority = int(body.get("priority", 10))

            if not title or not prompt:
                return self.send_json({"error": "Title and prompt are required"}, status=400)

            task_id = create_task(title, task_type, prompt, context, priority=priority)
            return self.send_json({"status": "created", "task_id": task_id})

        if path == "/api/run-self-improvement":
            # Direct on-demand trigger of the self-improvement cycle
            model = body.get("model") or "qwen2.5-coder:1.5b"
            engine = ModelSelfImprovementEngine()
            result = engine.run_self_improvement_cycle(model_name=model)
            return self.send_json({"status": "success", "result": result})

        if path == "/api/run-benchmark":
            model = body.get("model") or "qwen2.5-coder:1.5b"
            engine = ModelSelfImprovementEngine()
            result = engine.run_benchmark(model_name=model)
            return self.send_json({"status": "success", "result": result})

        if path == "/api/security/add-ip":
            ip_str = body.get("ip", "").strip()
            label = body.get("label", "").strip()
            try:
                add_allowed_ip(ip_str, label)
                return self.send_json({"status": "success", "message": f"IP '{ip_str}' added to whitelist."})
            except Exception as e:
                return self.send_json({"status": "error", "message": str(e)}, status=400)

        if path == "/api/security/remove-ip":
            ip_id = int(body.get("id", 0))
            remove_allowed_ip(ip_id)
            return self.send_json({"status": "success", "message": "IP removed from whitelist."})

        if path == "/api/security/toggle-whitelist":
            cfg = load_config()
            current = cfg.get("security", {}).get("enforce_ip_whitelist", True)
            cfg.setdefault("security", {})["enforce_ip_whitelist"] = not current
            save_config(cfg)
            return self.send_json({"status": "success", "enforce_ip_whitelist": not current})

        if path == "/api/security/change-password":
            new_pass = body.get("new_password", "").strip()
            if len(new_pass) < 6:
                return self.send_json({"status": "error", "message": "Password must be at least 6 characters."}, status=400)
            update_user_password(session["user_id"], new_pass)
            return self.send_json({"status": "success", "message": "Password updated. Please log in again."})

        if path == "/api/db/query":
            query = body.get("query", "").strip()
            if not query:
                return self.send_json({"error": "Empty query"}, status=400)
            try:
                res = execute_custom_sql(query)
                return self.send_json(res)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=400)

        if path == "/api/ssh/authorize":
            pub_key = body.get("public_key", "").strip()
            comment = body.get("comment", "").strip()
            days = int(body.get("expires_days", 30))
            target_user = body.get("username", session.get("username", "ishabarundo")).strip()
            if not pub_key:
                return self.send_json({"status": "error", "message": "Public key string is required."}, status=400)
            try:
                res = authorize_ssh_key(target_user, pub_key, comment=comment, expires_days=days, user_id=session.get("user_id"))
                return self.send_json(res)
            except Exception as e:
                return self.send_json({"status": "error", "message": str(e)}, status=400)

        if path == "/api/ssh/revoke":
            key_id = body.get("id") or body.get("fingerprint")
            if not key_id:
                return self.send_json({"status": "error", "message": "Key ID or fingerprint required."}, status=400)
            revoke_ssh_key(key_id)
            return self.send_json({"status": "success", "message": f"Revoked SSH key {key_id}"})

        if path == "/api/ssh/sync":
            sync_to_authorized_keys_file()
            return self.send_json({"status": "success", "message": "Synchronized ~/.ssh/authorized_keys"})

        return self.send_json({"error": "Not Found"}, status=404)

    # --- HTML Templates ---

    def get_login_page(self, client_ip: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autonomous Agent &bull; Terminal Login</title>
    <style>
        :root {{
            --bg: #090d16;
            --card: rgba(17, 24, 39, 0.85);
            --border: #1f293d;
            --primary: #38bdf8;
            --accent: #818cf8;
            --text: #f9fafb;
            --muted: #94a3b8;
            --red: #f43f5e;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: radial-gradient(circle at 50% 20%, #172554, var(--bg) 70%);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            background: var(--card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: 16px;
            width: 100%;
            max-width: 440px;
            padding: 40px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
        }}
        .logo {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 24px;
        }}
        .badge-ai {{
            background: linear-gradient(135deg, #0284c7, #6366f1);
            color: white;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 9999px;
            letter-spacing: 0.05em;
        }}
        h1 {{
            font-size: 1.6rem;
            font-weight: 700;
            color: #fff;
            margin-bottom: 8px;
        }}
        p.subtitle {{
            color: var(--muted);
            font-size: 0.9rem;
            margin-bottom: 28px;
            line-height: 1.5;
        }}
        .form-group {{
            margin-bottom: 20px;
        }}
        label {{
            display: block;
            font-size: 0.85rem;
            font-weight: 600;
            color: #cbd5e1;
            margin-bottom: 8px;
        }}
        input {{
            width: 100%;
            padding: 12px 16px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 10px;
            color: #fff;
            font-size: 0.95rem;
            outline: none;
            transition: border-color 0.2s;
        }}
        input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
        }}
        button {{
            width: 100%;
            padding: 13px;
            background: linear-gradient(135deg, #0284c7, #4f46e5);
            border: none;
            border-radius: 10px;
            color: #fff;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            margin-top: 8px;
        }}
        button:hover {{
            filter: brightness(1.1);
            transform: translateY(-1px);
        }}
        .error-msg {{
            background: rgba(244, 63, 94, 0.15);
            border: 1px solid var(--red);
            color: #fecdd3;
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 0.85rem;
            margin-bottom: 20px;
            display: none;
        }}
        .info-pill {{
            margin-top: 24px;
            padding-top: 18px;
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            color: #64748b;
        }}

        /* Modal & File Explorer Styles */
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(4, 7, 15, 0.82);
            backdrop-filter: blur(8px);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }}
        .modal-container {{
            background: #111a30;
            border: 1px solid var(--card-border);
            border-radius: 16px;
            width: 100%;
            max-width: 840px;
            max-height: 88vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.85);
            animation: fadeIn 0.2s ease;
        }}
        .modal-header {{
            padding: 18px 24px;
            border-bottom: 1px solid var(--card-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .modal-body {{
            padding: 20px 24px;
            flex: 1;
            overflow-y: auto;
        }}
        .modal-footer {{
            padding: 16px 24px;
            border-top: 1px solid var(--card-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 0 0 16px 16px;
        }}
        .btn-close {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 1.6rem;
            cursor: pointer;
            line-height: 1;
            transition: color 0.15s;
        }}
        .btn-close:hover {{ color: #fff; }}
        .chip-btn {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #cbd5e1;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .chip-btn:hover {{
            background: rgba(56, 189, 248, 0.15);
            border-color: var(--primary);
            color: #fff;
        }}
        .breadcrumb-container {{
            display: flex;
            align-items: center;
            gap: 4px;
            background: #090e1a;
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 8px 12px;
            overflow-x: auto;
            white-space: nowrap;
            font-size: 0.8rem;
        }}
        .breadcrumb-item {{
            color: var(--primary);
            cursor: pointer;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'JetBrains Mono', monospace;
        }}
        .breadcrumb-item:hover {{
            background: rgba(56, 189, 248, 0.15);
            text-decoration: underline;
        }}
        .breadcrumb-sep {{ color: var(--text-muted); opacity: 0.6; }}
        .fs-list-container {{
            background: #090e1a;
            border: 1px solid var(--card-border);
            border-radius: 10px;
            max-height: 380px;
            overflow-y: auto;
        }}
        .fs-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 9px 14px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            cursor: pointer;
            font-size: 0.85rem;
            transition: background 0.15s;
        }}
        .fs-row:hover {{
            background: rgba(56, 189, 248, 0.08);
        }}
        .fs-row.selected {{
            background: rgba(56, 189, 248, 0.18);
            border-left: 3px solid var(--primary);
        }}
        .fs-name-col {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.82rem;
        }}
        .fs-meta-col {{
            color: var(--text-muted);
            font-size: 0.75rem;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .fs-pick-btn {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 3px 8px;
            border-radius: 5px;
            font-size: 0.72rem;
            font-weight: 600;
            cursor: pointer;
        }}
        .fs-pick-btn:hover {{
            background: var(--emerald);
            color: #fff;
        }}
        .explorer-layout {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        @media (max-width: 900px) {{
            .explorer-layout {{ grid-template-columns: 1fr; }}
        }}


        /* Modal & File Explorer Styles */
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(4, 7, 15, 0.82);
            backdrop-filter: blur(8px);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }}
        .modal-container {{
            background: #111a30;
            border: 1px solid var(--card-border);
            border-radius: 16px;
            width: 100%;
            max-width: 840px;
            max-height: 88vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.85);
            animation: fadeIn 0.2s ease;
        }}
        .modal-header {{
            padding: 18px 24px;
            border-bottom: 1px solid var(--card-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .modal-body {{
            padding: 20px 24px;
            flex: 1;
            overflow-y: auto;
        }}
        .modal-footer {{
            padding: 16px 24px;
            border-top: 1px solid var(--card-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 0 0 16px 16px;
        }}
        .btn-close {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 1.6rem;
            cursor: pointer;
            line-height: 1;
            transition: color 0.15s;
        }}
        .btn-close:hover {{ color: #fff; }}
        .chip-btn {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #cbd5e1;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .chip-btn:hover {{
            background: rgba(56, 189, 248, 0.15);
            border-color: var(--primary);
            color: #fff;
        }}
        .breadcrumb-container {{
            display: flex;
            align-items: center;
            gap: 4px;
            background: #090e1a;
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 8px 12px;
            overflow-x: auto;
            white-space: nowrap;
            font-size: 0.8rem;
        }}
        .breadcrumb-item {{
            color: var(--primary);
            cursor: pointer;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'JetBrains Mono', monospace;
        }}
        .breadcrumb-item:hover {{
            background: rgba(56, 189, 248, 0.15);
            text-decoration: underline;
        }}
        .breadcrumb-sep {{ color: var(--text-muted); opacity: 0.6; }}
        .fs-list-container {{
            background: #090e1a;
            border: 1px solid var(--card-border);
            border-radius: 10px;
            max-height: 380px;
            overflow-y: auto;
        }}
        .fs-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 9px 14px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            cursor: pointer;
            font-size: 0.85rem;
            transition: background 0.15s;
        }}
        .fs-row:hover {{
            background: rgba(56, 189, 248, 0.08);
        }}
        .fs-row.selected {{
            background: rgba(56, 189, 248, 0.18);
            border-left: 3px solid var(--primary);
        }}
        .fs-name-col {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.82rem;
        }}
        .fs-meta-col {{
            color: var(--text-muted);
            font-size: 0.75rem;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .fs-pick-btn {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 3px 8px;
            border-radius: 5px;
            font-size: 0.72rem;
            font-weight: 600;
            cursor: pointer;
        }}
        .fs-pick-btn:hover {{
            background: var(--emerald);
            color: #fff;
        }}
        .explorer-layout {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        @media (max-width: 900px) {{
            .explorer-layout {{ grid-template-columns: 1fr; }}
        }}

    </style>
</head>
<body>
    <div class="card">
        <div class="logo">
            <span style="font-size: 2rem;">⚡</span>
            <div>
                <span class="badge-ai">AUTONOMOUS AGENT</span>
            </div>
        </div>
        <h1>Agent Terminal</h1>
        <p class="subtitle">Secure management portal for autonomous background execution, self-improvement, and scaling.</p>
        
        <div id="errMsg" class="error-msg"></div>

        <form id="loginForm">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autofocus placeholder="admin" />
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required placeholder="••••••••••••" />
            </div>
            <button type="submit" id="submitBtn">Authenticate & Enter</button>
        </form>

        <div class="info-pill">
            <span>Client IP: <code>{client_ip}</code></span>
            <span>Cloudflare Tunnel Verified</span>
        </div>
    </div>

    <script>
        document.getElementById("loginForm").addEventListener("submit", async (e) => {{
            e.preventDefault();
            const btn = document.getElementById("submitBtn");
            const errDiv = document.getElementById("errMsg");
            btn.disabled = true;
            btn.textContent = "Verifying...";
            errDiv.style.display = "none";

            try {{
                const res = await fetch("/api/login", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{
                        username: document.getElementById("username").value,
                        password: document.getElementById("password").value
                    }})
                }});
                const data = await res.json();
                if (res.ok && data.status === "success") {{
                    window.location.href = "/";
                }} else {{
                    errDiv.textContent = data.message || "Authentication failed.";
                    errDiv.style.display = "block";
                    btn.disabled = false;
                    btn.textContent = "Authenticate & Enter";
                }}
            }} catch (err) {{
                errDiv.textContent = "Connection error. Please try again.";
                errDiv.style.display = "block";
                btn.disabled = false;
                btn.textContent = "Authenticate & Enter";
            }}
        }});
    </script>
</body>
</html>
"""

    def get_dashboard_page(self, session: dict, client_ip: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autonomous Agent &bull; Command Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0b0f19;
            --sidebar-bg: #0f172a;
            --card-bg: #131d35;
            --card-border: #1e2d4d;
            --primary: #38bdf8;
            --primary-glow: rgba(56, 189, 248, 0.25);
            --accent: #818cf8;
            --emerald: #10b981;
            --rose: #f43f5e;
            --amber: #f59e0b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --sidebar-width: 260px;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            overflow-x: hidden;
        }}
        /* Sidebar Navigation */
        .sidebar {{
            width: var(--sidebar-width);
            background: var(--sidebar-bg);
            border-right: 1px solid var(--card-border);
            height: 100vh;
            position: fixed;
            top: 0;
            left: 0;
            display: flex;
            flex-direction: column;
            z-index: 50;
        }}
        .brand {{
            padding: 24px;
            display: flex;
            align-items: center;
            gap: 12px;
            border-bottom: 1px solid var(--card-border);
        }}
        .brand h2 {{
            font-size: 1.1rem;
            font-weight: 700;
            color: #fff;
            letter-spacing: -0.02em;
        }}
        .brand span.tag {{
            background: #0369a1;
            color: #e0f2fe;
            font-size: 0.65rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 6px;
        }}
        .nav-menu {{
            list-style: none;
            padding: 20px 12px;
            flex: 1;
            overflow-y: auto;
        }}
        .nav-item {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 11px 16px;
            border-radius: 8px;
            color: var(--text-muted);
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s ease;
            margin-bottom: 4px;
        }}
        .nav-item:hover {{
            background: rgba(255, 255, 255, 0.05);
            color: #fff;
        }}
        .nav-item.active {{
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.15), rgba(99, 102, 241, 0.15));
            border-left: 3px solid var(--primary);
            color: #fff;
            font-weight: 600;
        }}
        .nav-item .icon {{ font-size: 1.15rem; }}
        .user-panel {{
            padding: 16px 20px;
            border-top: 1px solid var(--card-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(0, 0, 0, 0.2);
        }}
        .user-info {{
            font-size: 0.85rem;
        }}
        .user-info .uname {{ font-weight: 600; color: #fff; }}
        .user-info .role {{ color: var(--text-muted); font-size: 0.75rem; }}
        .btn-logout {{
            background: transparent;
            border: 1px solid #334155;
            color: var(--rose);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn-logout:hover {{
            background: rgba(244, 63, 94, 0.15);
        }}

        /* Main Content Container */
        .main-content {{
            margin-left: var(--sidebar-width);
            flex: 1;
            padding: 32px 40px;
            min-height: 100vh;
        }}
        .top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 28px;
        }}
        .top-bar h1 {{
            font-size: 1.5rem;
            font-weight: 700;
        }}
        .quick-actions {{
            display: flex;
            gap: 12px;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #1e293b;
            color: #f1f5f9;
            border: 1px solid var(--card-border);
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn:hover {{
            background: #334155;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #0284c7, #4f46e5);
            border: none;
            color: #fff;
            box-shadow: 0 4px 14px rgba(2, 132, 199, 0.3);
        }}
        .btn-primary:hover {{
            filter: brightness(1.1);
        }}
        .btn-emerald {{
            background: linear-gradient(135deg, #059669, #10b981);
            border: none;
            color: #fff;
        }}

        /* Metrics Grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}
        .stat-card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .stat-card .label {{
            font-size: 0.8rem;
            font-weight: 500;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .stat-card .value {{
            font-size: 1.8rem;
            font-weight: 700;
            color: #fff;
        }}
        .stat-card.green .value {{ color: var(--emerald); }}
        .stat-card.amber .value {{ color: var(--amber); }}
        .stat-card.blue .value {{ color: var(--primary); }}
        .stat-card.rose .value {{ color: var(--rose); }}

        /* Panels Container */
        .panel-view {{
            display: none;
        }}
        .panel-view.active {{
            display: block;
            animation: fadeIn 0.2s ease;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(4px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        /* Cards & Tables */
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .card h3 {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            margin-top: 12px;
        }}
        th, td {{
            padding: 12px 14px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }}
        th {{
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }}
        tr:hover td {{
            background: rgba(255, 255, 255, 0.02);
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .badge-completed {{ background: rgba(16, 185, 129, 0.15); color: var(--emerald); }}
        .badge-pending {{ background: rgba(245, 158, 11, 0.15); color: var(--amber); }}
        .badge-running {{ background: rgba(56, 189, 248, 0.15); color: var(--primary); }}
        .badge-failed {{ background: rgba(244, 63, 94, 0.15); color: var(--rose); }}

        /* Forms & Inputs */
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        .input-group {{
            margin-bottom: 16px;
        }}
        .input-group label {{
            display: block;
            font-size: 0.8rem;
            font-weight: 600;
            color: #cbd5e1;
            margin-bottom: 6px;
        }}
        input, select, textarea {{
            width: 100%;
            background: #0b1120;
            border: 1px solid var(--card-border);
            padding: 10px 14px;
            border-radius: 8px;
            color: #fff;
            font-family: inherit;
            font-size: 0.85rem;
            outline: none;
        }}
        input:focus, select:focus, textarea:focus {{
            border-color: var(--primary);
        }}
        textarea {{ resize: vertical; min-height: 80px; font-family: 'JetBrains Mono', monospace; }}

        /* Live Log Stream / Terminal Box */
        .terminal-box {{
            background: #060911;
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: #38bdf8;
            max-height: 340px;
            overflow-y: auto;
            white-space: pre-wrap;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <!-- Sidebar Navigation -->
    <aside class="sidebar">
        <div class="brand">
            <span style="font-size: 1.6rem;">⚡</span>
            <div>
                <h2>SafeSpaces AGY <span class="tag">DAEMON</span></h2>
            </div>
        </div>
        <ul class="nav-menu">
            <li class="nav-item active" onclick="switchPanel('overview')">
                <span class="icon">📊</span> Overview
            </li>
            <li class="nav-item" onclick="switchPanel('tasks')">
                <span class="icon">📋</span> Agent Tasks
            </li>
            <li class="nav-item" onclick="switchPanel('explorer')">
                <span class="icon">📂</span> File Explorer
            </li>
            <li class="nav-item" onclick="switchPanel('self_improvement')">
                <span class="icon">🧠</span> Self-Improvement
            </li>
            <li class="nav-item" onclick="switchPanel('database')">
                <span class="icon">🗄️</span> Database Explorer
            </li>
            <li class="nav-item" onclick="switchPanel('security')">
                <span class="icon">🛡️</span> Security & Whitelist
            </li>
            <li class="nav-item" onclick="switchPanel('ssh')">
                <span class="icon">🔑</span> SSH Authorization
            </li>
            <li class="nav-item" onclick="switchPanel('guard')">
                <span class="icon">🔍</span> Credential Guard
            </li>
            <li class="nav-item" onclick="switchPanel('settings')">
                <span class="icon">⚙️</span> Settings
            </li>
        </ul>
        <div class="user-panel">
            <div class="user-info">
                <div class="uname">{session.get('username', 'admin')}</div>
                <div class="role">{session.get('role', 'admin').upper()} &bull; IP: {client_ip}</div>
            </div>
            <button class="btn-logout" onclick="location.href='/logout'">Logout</button>
        </div>
    </aside>

    <!-- Main Workspace -->
    <main class="main-content">
        <header class="top-bar">
            <div>
                <h1 id="panelTitle">Dashboard Overview</h1>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 4px;">Public endpoint: <strong style="color: var(--primary);">agent.safespaceshub.com</strong> &bull; Cloudflare Tunnel Protected</p>
            </div>
            <div class="quick-actions" style="display: flex; gap: 10px; align-items: center;">
                <div style="display: flex; align-items: center; gap: 6px; background: rgba(17,24,39,0.8); border: 1px solid var(--border); padding: 4px 10px; border-radius: 8px;">
                    <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600;">Workspace View:</span>
                    <select id="tenantPresetSelect" onchange="switchTenantPreset(this.value)" style="background: transparent; color: var(--primary); border: none; font-size: 0.8rem; font-weight: 600; cursor: pointer; outline: none;">
                        <option value="full">Unified Master</option>
                        <option value="devops">DevOps & Infra</option>
                        <option value="security">Security & Auditor</option>
                        <option value="ai_engineer">AI & Models</option>
                        <option value="developer">Developer & Code</option>
                    </select>
                </div>
                <button class="btn btn-emerald" onclick="triggerSelfImprovement()">🧠 Run Self-Improvement</button>
                <button class="btn btn-primary" onclick="switchPanel('tasks')">+ New Task</button>
            </div>
        </header>

        <!-- Metrics Overview Row -->
        <div class="stats-grid">
            <div class="stat-card blue">
                <span class="label">Pending Tasks</span>
                <span class="value" id="statPending">-</span>
            </div>
            <div class="stat-card green">
                <span class="label">Completed</span>
                <span class="value" id="statCompleted">-</span>
            </div>
            <div class="stat-card amber">
                <span class="label">Active Model</span>
                <span class="value" style="font-size: 1.1rem; line-height: 2.2rem;" id="statModel">qwen2.5-coder</span>
            </div>
            <div class="stat-card green">
                <span class="label">Self-Improvements</span>
                <span class="value" id="statImprovements">-</span>
            </div>
            <div class="stat-card rose">
                <span class="label">Vulnerabilities</span>
                <span class="value" id="statVulns">-</span>
            </div>
        </div>

        <!-- PANEL 1: OVERVIEW -->
        <div id="panel_overview" class="panel-view active">
            <div class="grid-2">
                <div class="card">
                    <h3>Recent Tasks Queue</h3>
                    <table id="tableRecentTasks">
                        <thead>
                            <tr><th>ID</th><th>Title</th><th>Type</th><th>Status</th></tr>
                        </thead>
                        <tbody><tr><td colspan="4">Loading tasks...</td></tr></tbody>
                    </table>
                </div>
                <div class="card">
                    <h3>System Resources & Scale</h3>
                    <div style="display: flex; flex-direction: column; gap: 14px; margin-top: 8px;">
                        <div>
                            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 6px;">
                                <span>CPU Load</span><span id="meterCpu">-</span>
                            </div>
                            <div style="background: #1e293b; height: 8px; border-radius: 4px; overflow: hidden;">
                                <div id="barCpu" style="width: 45%; height: 100%; background: var(--primary);"></div>
                            </div>
                        </div>
                        <div>
                            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 6px;">
                                <span>Memory Usage</span><span id="meterRam">-</span>
                            </div>
                            <div style="background: #1e293b; height: 8px; border-radius: 4px; overflow: hidden;">
                                <div id="barRam" style="width: 70%; height: 100%; background: var(--emerald);"></div>
                            </div>
                        </div>
                        <div>
                            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 6px;">
                                <span>Swap Headroom</span><span id="meterSwap">-</span>
                            </div>
                            <div style="background: #1e293b; height: 8px; border-radius: 4px; overflow: hidden;">
                                <div id="barSwap" style="width: 90%; height: 100%; background: var(--amber);"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card">
                <h3>Latest Self-Improvement & Benchmark Cycles</h3>
                <table id="tableBenchmarkPreview">
                    <thead>
                        <tr><th>Timestamp</th><th>Model</th><th>Focus Area</th><th>Before Score</th><th>After Score</th><th>Status</th></tr>
                    </thead>
                    <tbody><tr><td colspan="6">Loading improvements...</td></tr></tbody>
                </table>
            </div>
        </div>

        <!-- PANEL 2: AGENT TASKS -->
        <div id="panel_tasks" class="panel-view">
            <div class="card">
                <h3>Submit Autonomous Task</h3>
                <form id="createTaskForm">
                    <div class="grid-2">
                        <div class="input-group">
                            <label>Task Title</label>
                            <input type="text" id="taskTitle" required placeholder="e.g. Audit /var/www/signlanguage for SQL injections">
                        </div>
                        <div class="input-group">
                            <label>Task Type</label>
                            <select id="taskType">
                                <option value="code">Code Generation & Refactor</option>
                                <option value="security_audit">Security Vulnerability Audit</option>
                                <option value="self_improve">Model Self-Improvement Cycle</option>
                                <option value="benchmark">Model Benchmark Test</option>
                                <option value="database">Database Operations</option>
                                <option value="scale">Resource Scale Check</option>
                                <option value="general">General Autonomous Plan</option>
                            </select>
                        </div>
                    </div>
                    <div class="input-group">
                        <label>Instructions / Prompt</label>
                        <textarea id="taskPrompt" required placeholder="Detailed instructions for the autonomous agent..."></textarea>
                    </div>
                    <div class="input-group">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <label style="margin-bottom: 0;">Target Location / Directory Context</label>
                            <span style="font-size: 0.8rem; color: var(--primary); cursor: pointer; text-decoration: underline;" onclick="openFolderPickerModal()">📂 Open Server Explorer</span>
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <select id="selectTargetLocation" onchange="onTargetDropdownChange(this.value)" style="flex: 1.2; max-width: 320px;">
                                <option value="">-- Quick Select from Server --</option>
                            </select>
                            <input type="text" id="taskContext" placeholder="/var/www/signlanguage" style="flex: 2;">
                            <button type="button" class="btn" onclick="openFolderPickerModal()" title="Browse Server Filesystem" style="white-space: nowrap;">
                                📂 Browse...
                            </button>
                        </div>
                        <div id="targetDirInfo" style="display: none; margin-top: 6px; font-size: 0.78rem; color: var(--emerald);">
                            <span>✓ Verified Location: <code id="targetDirInfoPath"></code> (<span id="targetDirInfoCount"></span> items)</span>
                        </div>
                        <small style="color: var(--text-muted); font-size: 0.75rem; margin-top: 4px; display: block;">
                            Select a target repository/folder from the dropdown, browse server explorer, or enter a custom path.
                        </small>
                    </div>
                    <button type="submit" class="btn btn-primary">Dispatch Task to Worker</button>
                </form>
            </div>

            <div class="card">
                <h3>All Worker Tasks</h3>
                <table id="tableAllTasks">
                    <thead>
                        <tr><th>ID</th><th>Title</th><th>Type</th><th>Priority</th><th>Status</th><th>Updated</th></tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>

        <!-- PANEL: FILE EXPLORER (SERVER DIRECTORIES & PREVIEW) -->
        <div id="panel_explorer" class="panel-view">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <div>
                        <h3 style="margin-bottom: 4px;">Server Filesystem & Repository Explorer</h3>
                        <p style="color: var(--text-muted); font-size: 0.85rem;">Browse project directories, inspect codebase files, and dispatch autonomous agent operations.</p>
                    </div>
                    <button class="btn btn-primary" onclick="dispatchTaskFromExplorer()">🚀 Dispatch Agent Task on This Folder</button>
                </div>

                <!-- Quick Presets -->
                <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; align-items: center;">
                    <span style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted);">Quick Roots:</span>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/var/www')">🌐 /var/www</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/var/www/signlanguage')">🤟 /var/www/signlanguage</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/var/www/worker')">⚡ /var/www/worker</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/opt/orchestrator')">⚙️ /opt/orchestrator</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/etc/cloudflared')">☁️ /etc/cloudflared</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/home/ishabarundo')">🏠 User Home</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/')">Root (/)</button>
                </div>

                <!-- Navigation Bar -->
                <div style="display: flex; gap: 8px; margin-bottom: 14px; align-items: center;">
                    <button type="button" class="btn" onclick="navigateExplorerUp()" title="Go up one folder">⬆ Up</button>
                    <div id="explorerBreadcrumbs" class="breadcrumb-container" style="flex: 1;"></div>
                    <button type="button" class="btn" onclick="loadExplorerPath(currentExplorerPath)" title="Reload">🔄</button>
                </div>

                <div class="explorer-layout">
                    <!-- Left: Directory & File Listing -->
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-size: 0.8rem; color: var(--text-muted); font-weight: 600;" id="explorerItemsCount">Items</span>
                            <input type="text" id="explorerFilterInput" onkeyup="filterExplorerListing(this.value)" placeholder="Filter items..." style="max-width: 180px; padding: 4px 8px; font-size: 0.75rem;">
                        </div>
                        <div id="explorerFsList" class="fs-list-container" style="max-height: 480px;">
                            <div style="padding: 24px; text-align: center; color: var(--text-muted);">Loading server filesystem...</div>
                        </div>
                    </div>

                    <!-- Right: File & Code Inspector -->
                    <div class="card" style="margin-bottom: 0; background: #090e1a; padding: 18px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--card-border); padding-bottom: 10px;">
                            <h4 id="previewFileName" style="font-size: 0.95rem; font-family: 'JetBrains Mono', monospace; color: var(--primary);">Inspection Preview</h4>
                            <span id="previewFileSize" style="font-size: 0.75rem; color: var(--text-muted);">Select file or folder</span>
                        </div>
                        <div id="previewMetaBox" style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 10px;">
                            Path: <code id="previewFilePath" style="color: #cbd5e1;">-</code>
                        </div>
                        <div id="previewCodeBox" class="terminal-box" style="max-height: 380px; color: #e2e8f0; font-size: 0.78rem;">// Click on any file on the left to preview its source code here...</div>
                        <div style="margin-top: 14px; display: flex; gap: 8px;">
                            <button type="button" class="btn btn-emerald" onclick="selectForTaskContext(currentPreviewPath || currentExplorerPath)">✓ Use in Agent Task Form</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <!-- PANEL: FILE EXPLORER (SERVER DIRECTORIES & PREVIEW) -->
        <div id="panel_explorer" class="panel-view">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <div>
                        <h3 style="margin-bottom: 4px;">Server Filesystem & Repository Explorer</h3>
                        <p style="color: var(--text-muted); font-size: 0.85rem;">Browse project directories, inspect codebase files, and dispatch autonomous agent operations.</p>
                    </div>
                    <button class="btn btn-primary" onclick="dispatchTaskFromExplorer()">🚀 Dispatch Agent Task on This Folder</button>
                </div>

                <!-- Quick Presets -->
                <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; align-items: center;">
                    <span style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted);">Quick Roots:</span>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/var/www')">🌐 /var/www</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/var/www/signlanguage')">🤟 /var/www/signlanguage</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/var/www/worker')">⚡ /var/www/worker</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/opt/orchestrator')">⚙️ /opt/orchestrator</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/etc/cloudflared')">☁️ /etc/cloudflared</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/home/ishabarundo')">🏠 User Home</button>
                    <button type="button" class="chip-btn" onclick="loadExplorerPath('/')">Root (/)</button>
                </div>

                <!-- Navigation Bar -->
                <div style="display: flex; gap: 8px; margin-bottom: 14px; align-items: center;">
                    <button type="button" class="btn" onclick="navigateExplorerUp()" title="Go up one folder">⬆ Up</button>
                    <div id="explorerBreadcrumbs" class="breadcrumb-container" style="flex: 1;"></div>
                    <button type="button" class="btn" onclick="loadExplorerPath(currentExplorerPath)" title="Reload">🔄</button>
                </div>

                <div class="explorer-layout">
                    <!-- Left: Directory & File Listing -->
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-size: 0.8rem; color: var(--text-muted); font-weight: 600;" id="explorerItemsCount">Items</span>
                            <input type="text" id="explorerFilterInput" onkeyup="filterExplorerListing(this.value)" placeholder="Filter items..." style="max-width: 180px; padding: 4px 8px; font-size: 0.75rem;">
                        </div>
                        <div id="explorerFsList" class="fs-list-container" style="max-height: 480px;">
                            <div style="padding: 24px; text-align: center; color: var(--text-muted);">Loading server filesystem...</div>
                        </div>
                    </div>

                    <!-- Right: File & Code Inspector -->
                    <div class="card" style="margin-bottom: 0; background: #090e1a; padding: 18px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--card-border); padding-bottom: 10px;">
                            <h4 id="previewFileName" style="font-size: 0.95rem; font-family: 'JetBrains Mono', monospace; color: var(--primary);">Inspection Preview</h4>
                            <span id="previewFileSize" style="font-size: 0.75rem; color: var(--text-muted);">Select file or folder</span>
                        </div>
                        <div id="previewMetaBox" style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 10px;">
                            Path: <code id="previewFilePath" style="color: #cbd5e1;">-</code>
                        </div>
                        <div id="previewCodeBox" class="terminal-box" style="max-height: 380px; color: #e2e8f0; font-size: 0.78rem;">// Click on any file on the left to preview its source code here...</div>
                        <div style="margin-top: 14px; display: flex; gap: 8px;">
                            <button type="button" class="btn btn-emerald" onclick="selectForTaskContext(currentPreviewPath || currentExplorerPath)">✓ Use in Agent Task Form</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <!-- PANEL 3: SELF-IMPROVEMENT -->
        <div id="panel_self_improvement" class="panel-view">
            <div class="card">
                <h3>Model Self-Improvement Battery</h3>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 16px;">
                    Executes automated coding verification harnesses, measures algorithm accuracy, and runs reflexion self-correction cycles to continuously improve local models.
                </p>
                <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 20px;">
                    <select id="selectImproveModel" style="max-width: 240px;">
                        <option value="qwen2.5-coder:1.5b">qwen2.5-coder:1.5b</option>
                        <option value="llama3.2:1b">llama3.2:1b</option>
                        <option value="deepseek-r1:7b">deepseek-r1:7b</option>
                    </select>
                    <button class="btn btn-emerald" onclick="triggerSelfImprovement()">Run Full Improvement Cycle</button>
                    <button class="btn" onclick="triggerBenchmarkOnly()">Run Benchmark Only</button>
                </div>
                <div id="selfImproveStatus" style="font-size: 0.85rem; color: var(--emerald); margin-bottom: 12px; display: none;"></div>
                <div class="terminal-box" id="selfImproveTerminal">// Improvement log outputs will appear here...</div>
            </div>

            <div class="card">
                <h3>Improvement History & Gains</h3>
                <table id="tableFullImprovements">
                    <thead>
                        <tr><th>ID</th><th>Timestamp</th><th>Model</th><th>Before</th><th>After</th><th>Gain</th><th>Optimizations</th></tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>

        <!-- PANEL 4: DATABASE EXPLORER -->
        <div id="panel_database" class="panel-view">
            <div class="card">
                <h3>Database Table Viewer</h3>
                <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 16px;">
                    <select id="selectDbTable" onchange="loadTableData(this.value)" style="max-width: 260px;"></select>
                    <button class="btn" onclick="loadTableData(document.getElementById('selectDbTable').value)">Refresh Table</button>
                </div>
                <div style="overflow-x: auto;">
                    <table id="tableDbRows">
                        <thead id="theadDb"></thead>
                        <tbody id="tbodyDb"></tbody>
                    </table>
                </div>
            </div>

            <div class="card">
                <h3>Execute Safe SQL Query</h3>
                <div class="input-group">
                    <textarea id="sqlQueryInput" placeholder="SELECT * FROM tasks WHERE status = 'completed' LIMIT 10;"></textarea>
                </div>
                <button class="btn btn-primary" onclick="runCustomSql()">Execute Query</button>
                <div class="terminal-box" id="sqlQueryResult" style="margin-top: 16px; display: none;"></div>
            </div>
        </div>

        <!-- PANEL 5: SECURITY & WHITELIST -->
        <div id="panel_security" class="panel-view">
            <div class="card">
                <h3>IP Whitelist & Access Control</h3>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 16px;">
                    Only requests originating from these IP addresses or subnets can access this terminal. Tailscale, Localhost, and local LAN subnets are enabled by default.
                </p>
                <div style="margin-bottom: 20px;">
                    <button class="btn btn-primary" id="btnToggleWhitelist" onclick="toggleWhitelistEnforcement()">Toggle Whitelist Enforcement</button>
                    <span id="whitelistStatusText" style="margin-left: 12px; font-size: 0.85rem; font-weight: 600;"></span>
                </div>
                
                <form id="addIpForm" style="display: flex; gap: 12px; margin-bottom: 20px;">
                    <input type="text" id="newIpAddress" placeholder="IP or CIDR (e.g. 197.239.5.165 or 100.64.0.0/10)" required style="max-width: 320px;">
                    <input type="text" id="newIpLabel" placeholder="Label / Owner Description" style="max-width: 240px;">
                    <button type="submit" class="btn btn-emerald">+ Whitelist IP</button>
                </form>

                <table id="tableAllowedIps">
                    <thead>
                        <tr><th>ID</th><th>IP / CIDR Network</th><th>Description</th><th>Added At</th><th>Action</th></tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>

            <div class="card">
                <h3>Security Settings</h3>
                <div class="input-group" style="max-width: 380px;">
                    <label>Change Administrator Password</label>
                    <input type="password" id="newAdminPass" placeholder="Enter new password">
                </div>
                <button class="btn" onclick="changeAdminPassword()">Update Password</button>
            </div>
        </div>

        <!-- PANEL 6: SETTINGS -->
        <div id="panel_settings" class="panel-view">
            <div class="card">
                <h3>Daemon & Model Routing Configuration</h3>
                <div class="grid-2">
                    <div class="input-group">
                        <label>Fast Coder Model (Ollama)</label>
                        <input type="text" id="cfgCoder" value="qwen2.5-coder:1.5b" disabled>
                    </div>
                    <div class="input-group">
                        <label>Reasoning & Planning Model</label>
                        <input type="text" id="cfgReasoning" value="deepseek-r1:7b" disabled>
                    </div>
                </div>
                <div class="input-group">
                    <label>Public Ingress Endpoint</label>
                    <input type="text" value="agent.safespaceshub.com" disabled>
                </div>
            </div>
        </div>

        <!-- PANEL: SSH AUTHORIZATION -->
        <div id="panel_ssh" class="panel-view">
            <div class="card">
                <h3>SSH Key Authorization Manager</h3>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 16px;">
                    Only public keys registered through this authenticated dashboard are permitted to access the server shell. Keys are synced securely to <code>~/.ssh/authorized_keys</code> with automatic SHA256 fingerprinting.
                </p>

                <div style="background: rgba(15,23,42,0.6); border: 1px solid var(--border); border-radius: 10px; padding: 18px; margin-bottom: 24px;">
                    <h4 style="font-size: 0.95rem; margin-bottom: 12px; color: var(--primary);">Authorize New SSH Public Key</h4>
                    <form id="addSshKeyForm" onsubmit="handleAuthorizeSsh(event)">
                        <div class="grid-2" style="margin-bottom: 12px;">
                            <div>
                                <label style="font-size: 0.8rem; color: var(--text-muted);">Key Label / Developer Name</label>
                                <input type="text" id="sshKeyLabel" placeholder="e.g. John Doe (MacBook Pro)" required style="width: 100%;">
                            </div>
                            <div>
                                <label style="font-size: 0.8rem; color: var(--text-muted);">Access Level</label>
                                <select id="sshKeyAccessLevel" style="width: 100%; padding: 10px; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #fff;">
                                    <option value="admin">Administrator (Full Shell)</option>
                                    <option value="developer">Developer (Repo & Docker)</option>
                                    <option value="readonly">Read-Only Audit</option>
                                </select>
                            </div>
                        </div>
                        <div style="margin-bottom: 12px;">
                            <label style="font-size: 0.8rem; color: var(--text-muted);">Public Key String (ssh-ed25519, ssh-rsa, or ecdsa)</label>
                            <textarea id="sshPublicKeyInput" placeholder="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... user@machine" rows="3" required style="width: 100%; padding: 10px; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #fff; font-family: 'JetBrains Mono', monospace; font-size: 0.8rem;"></textarea>
                        </div>
                        <div style="display: flex; gap: 10px; align-items: center;">
                            <button type="submit" class="btn btn-emerald" style="width: auto;">🔑 Authorize & Install Key</button>
                            <button type="button" class="btn" style="width: auto;" onclick="syncSshKeys()">🔄 Force Sync to ~/.ssh/authorized_keys</button>
                        </div>
                    </form>
                </div>

                <h4>Active Authorized SSH Keys</h4>
                <div style="overflow-x: auto;">
                    <table id="tableSshKeys" style="width: 100%; margin-top: 12px;">
                        <thead>
                            <tr>
                                <th>Label</th>
                                <th>Type</th>
                                <th>Fingerprint (SHA256)</th>
                                <th>Access</th>
                                <th>Authorized By</th>
                                <th>Added At</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody id="sshKeysTableBody">
                            <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 16px;">Loading authorized SSH keys...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- PANEL: CREDENTIAL GUARD -->
        <div id="panel_guard" class="panel-view">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <div>
                        <h3 style="margin-bottom: 4px;">Credential Guard & Leak Prevention</h3>
                        <p style="color: var(--text-muted); font-size: 0.85rem;">Scans server directories and staged commits for accidental API tokens, secret keys, passwords, and private certificates before Git sync.</p>
                    </div>
                    <button class="btn btn-primary" onclick="runGuardScan()">🛡️ Run Live Security Scan</button>
                </div>

                <div class="grid-2" style="margin-bottom: 20px;">
                    <div style="background: rgba(15,23,42,0.6); border: 1px solid var(--border); border-radius: 10px; padding: 16px;">
                        <h4 style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">Git Protection Hooks</h4>
                        <p style="font-size: 0.82rem; margin-bottom: 10px;">Pre-commit and Pre-push hooks prevent secrets from being published to GitHub repositories.</p>
                        <span class="badge" style="background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid #059669;">Active & Enforcing</span>
                    </div>
                    <div style="background: rgba(15,23,42,0.6); border: 1px solid var(--border); border-radius: 10px; padding: 16px;">
                        <h4 style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">Sanitized Public Cloning</h4>
                        <p style="font-size: 0.82rem; margin-bottom: 10px;">Public contributors receive <code>.env.example</code> and <code>config.example.json</code> without host credentials.</p>
                        <span class="badge" style="background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid #0284c7;">Zero-Credential Clone Mode</span>
                    </div>
                </div>

                <h4>Security Scanner Findings</h4>
                <div id="guardFindingsContainer" style="margin-top: 12px;">
                    <div style="padding: 24px; text-align: center; color: var(--text-muted); background: rgba(15,23,42,0.5); border-radius: 8px;">
                        Click "Run Live Security Scan" to scan repository files for secret patterns.
                    </div>
                </div>
            </div>
        </div>

        <!-- FOLDER / FILE PICKER MODAL -->
        <div id="folderPickerModal" class="modal-overlay" style="display: none;">
            <div class="modal-container">
                <div class="modal-header">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 1.3rem;">📂</span>
                        <h3 style="margin: 0; font-size: 1.1rem; color: #fff;">Server Filesystem Explorer</h3>
                    </div>
                    <button type="button" class="btn-close" onclick="closeFolderPickerModal()">&times;</button>
                </div>
                
                <div class="modal-body">
                    <!-- Quick Jump Chips -->
                    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; align-items: center;">
                        <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600;">Quick Jump:</span>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/var/www')">🌐 /var/www</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/var/www/signlanguage')">🤟 signlanguage</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/var/www/worker')">⚡ worker</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/opt/orchestrator')">⚙️ orchestrator</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/etc/cloudflared')">☁️ cloudflared</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/home/ishabarundo')">🏠 home</button>
                    </div>

                    <!-- Navigation & Breadcrumb bar -->
                    <div style="display: flex; gap: 8px; margin-bottom: 10px; align-items: center;">
                        <button type="button" class="btn" onclick="navigateModalUp()" title="Go up one folder">⬆ Up</button>
                        <div id="modalBreadcrumbs" class="breadcrumb-container" style="flex: 1;"></div>
                        <button type="button" class="btn" onclick="browseModalTo(modalCurrentPath)" title="Refresh">🔄</button>
                    </div>

                    <!-- Current path input & filter -->
                    <div style="display: flex; gap: 8px; margin-bottom: 12px;">
                        <input type="text" id="modalCurrentPathInput" placeholder="/var/www/..." style="font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; flex: 2;">
                        <button type="button" class="btn" onclick="browseModalTo(document.getElementById('modalCurrentPathInput').value)">Go</button>
                        <input type="text" id="modalFilterInput" onkeyup="filterModalListing(this.value)" placeholder="Filter items..." style="flex: 1; font-size: 0.8rem;">
                    </div>

                    <!-- Filesystem list container -->
                    <div id="modalFsList" class="fs-list-container">
                        <div style="padding: 20px; text-align: center; color: var(--text-muted);">Loading server filesystem...</div>
                    </div>
                </div>

                <div class="modal-footer">
                    <div style="display: flex; align-items: center; gap: 8px; flex: 1; overflow: hidden; margin-right: 12px;">
                        <span style="font-size: 0.8rem; color: var(--text-muted); white-space: nowrap;">Selected:</span>
                        <code id="modalSelectedPathText" style="color: var(--primary); font-size: 0.82rem; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">None</code>
                    </div>
                    <button type="button" class="btn" onclick="closeFolderPickerModal()">Cancel</button>
                    <button type="button" class="btn btn-primary" onclick="confirmModalSelection()">✓ Select This Location</button>
                </div>
            </div>
        </div>
        <!-- FOLDER / FILE PICKER MODAL -->
        <div id="folderPickerModal" class="modal-overlay" style="display: none;">
            <div class="modal-container">
                <div class="modal-header">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 1.3rem;">📂</span>
                        <h3 style="margin: 0; font-size: 1.1rem; color: #fff;">Server Filesystem Explorer</h3>
                    </div>
                    <button type="button" class="btn-close" onclick="closeFolderPickerModal()">&times;</button>
                </div>
                
                <div class="modal-body">
                    <!-- Quick Jump Chips -->
                    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; align-items: center;">
                        <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600;">Quick Jump:</span>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/var/www')">🌐 /var/www</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/var/www/signlanguage')">🤟 signlanguage</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/var/www/worker')">⚡ worker</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/opt/orchestrator')">⚙️ orchestrator</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/etc/cloudflared')">☁️ cloudflared</button>
                        <button type="button" class="chip-btn" onclick="browseModalTo('/home/ishabarundo')">🏠 home</button>
                    </div>

                    <!-- Navigation & Breadcrumb bar -->
                    <div style="display: flex; gap: 8px; margin-bottom: 10px; align-items: center;">
                        <button type="button" class="btn" onclick="navigateModalUp()" title="Go up one folder">⬆ Up</button>
                        <div id="modalBreadcrumbs" class="breadcrumb-container" style="flex: 1;"></div>
                        <button type="button" class="btn" onclick="browseModalTo(modalCurrentPath)" title="Refresh">🔄</button>
                    </div>

                    <!-- Current path input & filter -->
                    <div style="display: flex; gap: 8px; margin-bottom: 12px;">
                        <input type="text" id="modalCurrentPathInput" placeholder="/var/www/..." style="font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; flex: 2;">
                        <button type="button" class="btn" onclick="browseModalTo(document.getElementById('modalCurrentPathInput').value)">Go</button>
                        <input type="text" id="modalFilterInput" onkeyup="filterModalListing(this.value)" placeholder="Filter items..." style="flex: 1; font-size: 0.8rem;">
                    </div>

                    <!-- Filesystem list container -->
                    <div id="modalFsList" class="fs-list-container">
                        <div style="padding: 20px; text-align: center; color: var(--text-muted);">Loading server filesystem...</div>
                    </div>
                </div>

                <div class="modal-footer">
                    <div style="display: flex; align-items: center; gap: 8px; flex: 1; overflow: hidden; margin-right: 12px;">
                        <span style="font-size: 0.8rem; color: var(--text-muted); white-space: nowrap;">Selected:</span>
                        <code id="modalSelectedPathText" style="color: var(--primary); font-size: 0.82rem; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">None</code>
                    </div>
                    <button type="button" class="btn" onclick="closeFolderPickerModal()">Cancel</button>
                    <button type="button" class="btn btn-primary" onclick="confirmModalSelection()">✓ Select This Location</button>
                </div>
            </div>
        </div>
    </main>

    <script>
        // State
        let currentPanel = 'overview';

        function switchPanel(name) {{
            document.querySelectorAll('.panel-view').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            
            const targetPanel = document.getElementById('panel_' + name);
            if (targetPanel) targetPanel.classList.add('active');

            const navItems = document.querySelectorAll('.nav-item');
            const panelNames = ['overview', 'tasks', 'explorer', 'self_improvement', 'database', 'security', 'ssh', 'guard', 'settings'];
            const idx = panelNames.indexOf(name);
            if (idx >= 0 && navItems[idx]) navItems[idx].classList.add('active');

            const titles = {{
                overview: 'Dashboard Overview',
                tasks: 'Autonomous Agent Tasks',
                explorer: 'Server Filesystem & Repository Explorer',
                self_improvement: 'Model Self-Improvement & Benchmarks',
                database: 'Database Explorer & Operations',
                security: 'Security, Firewall & IP Whitelist',
                ssh: 'SSH Key Authorization Manager',
                guard: 'Credential Guard & Secret Scanner',
                settings: 'Daemon Configuration'
            }};
            document.getElementById('panelTitle').textContent = titles[name] || 'Dashboard';
            currentPanel = name;

            if (name === 'database') loadDbTables();
            if (name === 'explorer') loadExplorerPath(currentExplorerPath || '/var/www');
            if (name === 'ssh') loadSshKeys();
            if (name === 'guard') runGuardScan();
        }}

        async function fetchDashboard() {{
            try {{
                const res = await fetch('/api/dashboard-data');
                if (res.status === 401) {{ window.location.href = '/login'; return; }}
                const data = await res.json();
                renderDashboard(data);
            }} catch (err) {{
                console.error('Fetch error:', err);
            }}
        }}

        function renderDashboard(data) {{
            const stats = data.stats || {{}};
            document.getElementById('statPending').textContent = stats.pending_tasks || 0;
            document.getElementById('statCompleted').textContent = stats.completed_tasks || 0;
            document.getElementById('statImprovements').textContent = stats.improvements_count || 0;
            document.getElementById('statVulns').textContent = stats.open_vulns || 0;

            // Metrics
            const metrics = stats.metrics || {{}};
            if (metrics.ram_used_mb && metrics.ram_total_mb) {{
                const ramPct = Math.round((metrics.ram_used_mb / metrics.ram_total_mb) * 100);
                document.getElementById('meterRam').textContent = `${{metrics.ram_used_mb}} MB / ${{metrics.ram_total_mb}} MB (${{ramPct}}%)`;
                document.getElementById('barRam').style.width = `${{ramPct}}%`;
            }}
            if (metrics.cpu_load) {{
                document.getElementById('meterCpu').textContent = metrics.cpu_load;
            }}
            if (metrics.swap_used_mb !== undefined) {{
                document.getElementById('meterSwap').textContent = `${{metrics.swap_used_mb}} MB used`;
            }}

            // Whitelist status
            const enforce = data.config?.security?.enforce_ip_whitelist;
            const wText = document.getElementById('whitelistStatusText');
            if (wText) {{
                wText.textContent = enforce ? 'Active (Strict Access)' : 'Disabled (Open Access)';
                wText.style.color = enforce ? 'var(--emerald)' : 'var(--amber)';
            }}

            // Render Recent Tasks Table
            const recentTasks = data.recent_tasks || [];
            const tbRecent = document.querySelector('#tableRecentTasks tbody');
            tbRecent.innerHTML = recentTasks.map(t => `
                <tr>
                    <td>#${{t.id}}</td>
                    <td>${{t.title}}</td>
                    <td><code>${{t.type}}</code></td>
                    <td><span class="badge badge-${{t.status}}">${{t.status}}</span></td>
                </tr>
            `).join('') || '<tr><td colspan="4">No tasks in queue.</td></tr>';

            // Render All Tasks
            const tbAll = document.querySelector('#tableAllTasks tbody');
            if (tbAll) {{
                tbAll.innerHTML = recentTasks.map(t => `
                    <tr>
                        <td>#${{t.id}}</td>
                        <td><strong>${{t.title}}</strong></td>
                        <td><code>${{t.type}}</code></td>
                        <td>${{t.priority}}</td>
                        <td><span class="badge badge-${{t.status}}">${{t.status}}</span></td>
                        <td>${{t.updated_at}}</td>
                    </tr>
                `).join('');
            }}

            // Render Benchmark preview
            const tbBench = document.querySelector('#tableBenchmarkPreview tbody');
            const improvements = data.improvements || [];
            if (tbBench) {{
                tbBench.innerHTML = improvements.map(imp => `
                    <tr>
                        <td>${{imp.timestamp}}</td>
                        <td><code>${{imp.model_name}}</code></td>
                        <td>${{imp.focus_area}}</td>
                        <td>${{imp.before_score}}%</td>
                        <td style="color: var(--emerald); font-weight: 700;">${{imp.after_score}}%</td>
                        <td><span class="badge badge-completed">${{imp.status}}</span></td>
                    </tr>
                `).join('') || '<tr><td colspan="6">No improvement cycles recorded yet.</td></tr>';
            }}

            // Render Full improvements in Self-Improvement panel
            const tbFull = document.querySelector('#tableFullImprovements tbody');
            if (tbFull) {{
                tbFull.innerHTML = improvements.map(imp => `
                    <tr>
                        <td>#${{imp.id}}</td>
                        <td>${{imp.timestamp}}</td>
                        <td><code>${{imp.model_name}}</code></td>
                        <td>${{imp.before_score}}%</td>
                        <td style="color: var(--emerald); font-weight: 700;">${{imp.after_score}}%</td>
                        <td>+${{Math.round((imp.after_score - imp.before_score) * 10) / 10}}%</td>
                        <td style="font-size: 0.75rem;">${{imp.optimizations_applied || '-'}}</td>
                    </tr>
                `).join('');
            }}

            // Render Allowed IPs
            const allowedIps = data.allowed_ips || [];
            const tbIps = document.querySelector('#tableAllowedIps tbody');
            if (tbIps) {{
                tbIps.innerHTML = allowedIps.map(ip => `
                    <tr>
                        <td>#${{ip.id}}</td>
                        <td><code style="color: var(--primary);">${{ip.ip_or_cidr}}</code></td>
                        <td>${{ip.label || '-'}}</td>
                        <td>${{ip.added_at}}</td>
                        <td><button class="btn btn-logout" onclick="removeIp(${{ip.id}})">Remove</button></td>
                    </tr>
                `).join('') || '<tr><td colspan="5">No IP whitelist rules set.</td></tr>';
            }}
        }}

        // Task submission
        document.getElementById('createTaskForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const payload = {{
                title: document.getElementById('taskTitle').value,
                type: document.getElementById('taskType').value,
                prompt: document.getElementById('taskPrompt').value,
                context: document.getElementById('taskContext').value
            }};
            const res = await fetch('/api/tasks', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }});
            if (res.ok) {{
                alert('Task successfully dispatched to autonomous worker queue!');
                document.getElementById('createTaskForm').reset();
                fetchDashboard();
            }}
        }});

        // Self-Improvement Trigger
        async function triggerSelfImprovement() {{
            const term = document.getElementById('selfImproveTerminal');
            const status = document.getElementById('selfImproveStatus');
            switchPanel('self_improvement');
            term.textContent = '>> Initiating autonomous model self-improvement battery...\\n>> Model: qwen2.5-coder:1.5b\\n>> Testing syntax, algorithms, SQL queries, and error reflexion...\\n';
            status.style.display = 'block';
            status.textContent = 'Self-improvement cycle is executing on the server...';

            const res = await fetch('/api/run-self-improvement', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ model: document.getElementById('selectImproveModel').value }})
            }});
            const data = await res.json();
            if (res.ok && data.status === 'success') {{
                const r = data.result;
                term.textContent += `\\n[CYCLE COMPLETE]\\nBaseline Pass Rate: ${{r.before_score}}%\\nPost-Reflexion Pass Rate: ${{r.after_score}}%\\nNet Accuracy Gain: +${{r.gain}}%\\n\\nOptimizations Applied:\\n${{r.fixes_applied.join('\\n')}}\\n\\nSynthetic training data persisted to data/fine_tuning_dataset.jsonl`;
                status.textContent = 'Cycle completed successfully!';
                fetchDashboard();
            }} else {{
                term.textContent += `\\n[ERROR] ${{data.message || 'Execution error.'}}`;
            }}
        }}

        async function triggerBenchmarkOnly() {{
            const term = document.getElementById('selfImproveTerminal');
            term.textContent = '>> Executing benchmark suite...\\n';
            const res = await fetch('/api/run-benchmark', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ model: document.getElementById('selectImproveModel').value }})
            }});
            const data = await res.json();
            if (res.ok) {{
                term.textContent += JSON.stringify(data.result, null, 2);
                fetchDashboard();
            }}
        }}

        // Database Explorer Functions
        async function loadDbTables() {{
            const res = await fetch('/api/db/tables');
            const data = await res.json();
            const sel = document.getElementById('selectDbTable');
            sel.innerHTML = (data.tables || []).map(t => `<option value="${{t}}">${{t}}</option>`).join('');
            if (data.tables && data.tables.length > 0) loadTableData(data.tables[0]);
        }}

        async function loadTableData(tableName) {{
            if (!tableName) return;
            const res = await fetch(`/api/db/table?name=${{tableName}}`);
            const data = await res.json();
            const schema = data.schema || [];
            const rows = data.data?.rows || [];

            document.getElementById('theadDb').innerHTML = '<tr>' + schema.map(col => `<th>${{col.name}} <small style="color: #64748b;">(${{col.type}})</small></th>`).join('') + '</tr>';
            document.getElementById('tbodyDb').innerHTML = rows.map(r => '<tr>' + schema.map(col => `<td>${{r[col.name] !== null ? String(r[col.name]).substring(0, 60) : '<em style="color:#64748b">null</em>'}}</td>`).join('') + '</tr>').join('') || '<tr><td colspan="10">No rows in table.</td></tr>';
        }}

        async function runCustomSql() {{
            const q = document.getElementById('sqlQueryInput').value;
            const resDiv = document.getElementById('sqlQueryResult');
            resDiv.style.display = 'block';
            resDiv.textContent = 'Executing query...';
            const res = await fetch('/api/db/query', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ query: q }})
            }});
            const data = await res.json();
            resDiv.textContent = JSON.stringify(data, null, 2);
        }}

        // Security Form Handlers
        document.getElementById('addIpForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const ip = document.getElementById('newIpAddress').value;
            const label = document.getElementById('newIpLabel').value;
            const res = await fetch('/api/security/add-ip', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ ip, label }})
            }});
            const data = await res.json();
            if (res.ok) {{
                document.getElementById('addIpForm').reset();
                fetchDashboard();
            }} else {{
                alert(data.message || 'Error adding IP.');
            }}
        }});

        async function removeIp(id) {{
            if (!confirm('Remove this IP rule?')) return;
            await fetch('/api/security/remove-ip', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ id }})
            }});
            fetchDashboard();
        }}

        async function toggleWhitelistEnforcement() {{
            await fetch('/api/security/toggle-whitelist', {{ method: 'POST' }});
            fetchDashboard();
        }}

        async function changeAdminPassword() {{
            const p = document.getElementById('newAdminPass').value;
            if (!p) return;
            const res = await fetch('/api/security/change-password', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ new_password: p }})
            }});
            const data = await res.json();
            alert(data.message);
            if (res.ok) window.location.href = '/login';
        }}


        // --- Filesystem Explorer & Target Dropdown Logic ---
        let serverPresets = [];
        let modalCurrentPath = '/var/www';
        let modalParentPath = '/';
        let modalSelectedPath = '/var/www';
        let modalItemsCache = {{ directories: [], files: [] }};

        let currentExplorerPath = '/var/www';
        let currentExplorerParent = '/';
        let currentPreviewPath = '';
        let explorerItemsCache = {{ directories: [], files: [] }};

        async function loadPresets() {{
            try {{
                const res = await fetch('/api/fs/presets');
                const data = await res.json();
                serverPresets = data.presets || [];
                populateTargetDropdown();
            }} catch (err) {{
                console.error('Failed to load presets:', err);
            }}
        }}

        function populateTargetDropdown(selectedPath) {{
            const sel = document.getElementById('selectTargetLocation');
            if (!sel) return;
            const currentVal = selectedPath !== undefined ? selectedPath : sel.value;
            
            let html = '<option value="">-- Quick Select from Server --</option>';
            html += '<optgroup label="Server Projects & Roots">';
            serverPresets.forEach(p => {{
                html += `<option value="${{p.path}}">${{p.name}} (${{p.path}})</option>`;
            }});
            html += '</optgroup>';
            html += '<option value="__browse__">📂 Browse File Explorer...</option>';
            sel.innerHTML = html;

            if (currentVal && currentVal !== '__browse__') {{
                let exists = false;
                for (let i = 0; i < sel.options.length; i++) {{
                    if (sel.options[i].value === currentVal) {{
                        sel.selectedIndex = i;
                        exists = true;
                        break;
                    }}
                }}
                if (!exists) {{
                    const opt = document.createElement('option');
                    opt.value = currentVal;
                    opt.textContent = `📁 ${{currentVal}}`;
                    sel.insertBefore(opt, sel.options[1]);
                    sel.selectedIndex = 1;
                }}
            }}
        }}

        function onTargetDropdownChange(val) {{
            if (!val) return;
            if (val === '__browse__') {{
                openFolderPickerModal();
                return;
            }}
            document.getElementById('taskContext').value = val;
            verifyTargetLocation(val);
        }}

        async function verifyTargetLocation(path) {{
            const infoDiv = document.getElementById('targetDirInfo');
            if (!path) {{
                if (infoDiv) infoDiv.style.display = 'none';
                return;
            }}
            try {{
                const res = await fetch(`/api/fs/explore?path=${{encodeURIComponent(path)}}`);
                const data = await res.json();
                if (res.ok && !data.error) {{
                    const count = (data.directories?.length || 0) + (data.files?.length || 0);
                    document.getElementById('targetDirInfoPath').textContent = data.path;
                    document.getElementById('targetDirInfoCount').textContent = count;
                    infoDiv.style.display = 'block';
                }} else {{
                    infoDiv.style.display = 'none';
                }}
            }} catch (e) {{
                if (infoDiv) infoDiv.style.display = 'none';
            }}
        }}

        function openFolderPickerModal() {{
            const current = document.getElementById('taskContext').value.trim() || '/var/www';
            const modal = document.getElementById('folderPickerModal');
            modal.style.display = 'flex';
            browseModalTo(current);
        }}

        function closeFolderPickerModal() {{
            document.getElementById('folderPickerModal').style.display = 'none';
        }}

        async function browseModalTo(path) {{
            if (!path) path = '/var/www';
            const listDiv = document.getElementById('modalFsList');
            listDiv.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted);">Scanning directory...</div>';
            document.getElementById('modalCurrentPathInput').value = path;
            
            try {{
                const res = await fetch(`/api/fs/explore?path=${{encodeURIComponent(path)}}`);
                const data = await res.json();
                if (data.error) {{
                    listDiv.innerHTML = `<div style="padding: 20px; color: var(--rose);">Error: ${{data.error}}</div>`;
                    return;
                }}
                
                modalCurrentPath = data.path;
                modalParentPath = data.parent;
                modalSelectedPath = data.path;
                document.getElementById('modalSelectedPathText').textContent = data.path;
                document.getElementById('modalCurrentPathInput').value = data.path;

                renderModalBreadcrumbs(data.path);

                if (data.type === 'file') {{
                    modalItemsCache = {{ directories: [], files: [data] }};
                    renderModalListing([{{ name: data.name, path: data.path, is_dir: false, size: data.size }}], []);
                }} else {{
                    modalItemsCache = {{ directories: data.directories || [], files: data.files || [] }};
                    renderModalListing(data.directories || [], data.files || []);
                }}
            }} catch (err) {{
                listDiv.innerHTML = `<div style="padding: 20px; color: var(--rose);">Failed to explore path: ${{err.message}}</div>`;
            }}
        }}

        function navigateModalUp() {{
            if (modalParentPath) {{
                browseModalTo(modalParentPath);
            }}
        }}

        function renderModalBreadcrumbs(path) {{
            const bc = document.getElementById('modalBreadcrumbs');
            const parts = path.split('/').filter(Boolean);
            let html = `<span class="breadcrumb-item" onclick="browseModalTo('/')">/</span>`;
            let accum = '';
            parts.forEach((p, idx) => {{
                accum += '/' + p;
                const thisPath = accum;
                html += `<span class="breadcrumb-sep">/</span>`;
                html += `<span class="breadcrumb-item" onclick="browseModalTo('${{thisPath}}')">${{p}}</span>`;
            }});
            bc.innerHTML = html;
        }}

        function renderModalListing(dirs, files) {{
            const listDiv = document.getElementById('modalFsList');
            if (dirs.length === 0 && files.length === 0) {{
                listDiv.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Empty folder.</div>';
                return;
            }}

            let html = '';
            dirs.forEach(d => {{
                const isSel = modalSelectedPath === d.path;
                html += `
                    <div class="fs-row ${{isSel ? 'selected' : ''}}" onclick="setModalSelected('${{d.path}}', true, this)">
                        <div class="fs-name-col">
                            <span>📁</span>
                            <strong style="color: #f1f5f9;">${{d.name}}</strong>
                        </div>
                        <div class="fs-meta-col">
                            <button type="button" class="btn" style="padding: 2px 8px; font-size: 0.72rem;" onclick="event.stopPropagation(); browseModalTo('${{d.path}}')">Open ➔</button>
                            <button type="button" class="fs-pick-btn" onclick="event.stopPropagation(); pickModalLocation('${{d.path}}')">Select</button>
                        </div>
                    </div>
                `;
            }});

            files.forEach(f => {{
                const isSel = modalSelectedPath === f.path;
                const sizeKb = Math.round((f.size || 0) / 1024 * 10) / 10;
                html += `
                    <div class="fs-row ${{isSel ? 'selected' : ''}}" onclick="setModalSelected('${{f.path}}', false, this)">
                        <div class="fs-name-col">
                            <span>📄</span>
                            <span style="color: #cbd5e1;">${{f.name}}</span>
                        </div>
                        <div class="fs-meta-col">
                            <span>${{sizeKb}} KB</span>
                            <button type="button" class="fs-pick-btn" onclick="event.stopPropagation(); pickModalLocation('${{f.path}}')">Select</button>
                        </div>
                    </div>
                `;
            }});

            listDiv.innerHTML = html;
        }}

        function filterModalListing(query) {{
            const q = query.toLowerCase().trim();
            const filteredDirs = modalItemsCache.directories.filter(d => d.name.toLowerCase().includes(q));
            const filteredFiles = modalItemsCache.files.filter(f => f.name.toLowerCase().includes(q));
            renderModalListing(filteredDirs, filteredFiles);
        }}

        function setModalSelected(path, isDir, element) {{
            modalSelectedPath = path;
            document.getElementById('modalSelectedPathText').textContent = path;
            document.querySelectorAll('#modalFsList .fs-row').forEach(el => el.classList.remove('selected'));
            if (element) element.classList.add('selected');
        }}

        function pickModalLocation(path) {{
            modalSelectedPath = path;
            confirmModalSelection();
        }}

        function confirmModalSelection() {{
            const path = modalSelectedPath || modalCurrentPath;
            document.getElementById('taskContext').value = path;
            populateTargetDropdown(path);
            verifyTargetLocation(path);
            closeFolderPickerModal();
        }}

        // --- Full File Explorer Panel Logic ---
        async function loadExplorerPath(path) {{
            if (!path) path = '/var/www';
            const listDiv = document.getElementById('explorerFsList');
            listDiv.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted);">Reading server folder...</div>';
            
            try {{
                const res = await fetch(`/api/fs/explore?path=${{encodeURIComponent(path)}}`);
                const data = await res.json();
                if (data.error) {{
                    listDiv.innerHTML = `<div style="padding: 20px; color: var(--rose);">Error: ${{data.error}}</div>`;
                    return;
                }}

                currentExplorerPath = data.path;
                currentExplorerParent = data.parent;
                renderExplorerBreadcrumbs(data.path);

                if (data.type === 'file') {{
                    previewFileContent(data);
                    explorerItemsCache = {{ directories: [], files: [data] }};
                    renderExplorerListing([], [data]);
                }} else {{
                    explorerItemsCache = {{ directories: data.directories || [], files: data.files || [] }};
                    renderExplorerListing(data.directories || [], data.files || []);
                    document.getElementById('explorerItemsCount').textContent = `${{data.directories.length}} folders, ${{data.files.length}} files`;
                }}
            }} catch (err) {{
                listDiv.innerHTML = `<div style="padding: 20px; color: var(--rose);">Error: ${{err.message}}</div>`;
            }}
        }}

        function navigateExplorerUp() {{
            if (currentExplorerParent) {{
                loadExplorerPath(currentExplorerParent);
            }}
        }}

        function renderExplorerBreadcrumbs(path) {{
            const bc = document.getElementById('explorerBreadcrumbs');
            const parts = path.split('/').filter(Boolean);
            let html = `<span class="breadcrumb-item" onclick="loadExplorerPath('/')">/</span>`;
            let accum = '';
            parts.forEach((p, idx) => {{
                accum += '/' + p;
                const thisPath = accum;
                html += `<span class="breadcrumb-sep">/</span>`;
                html += `<span class="breadcrumb-item" onclick="loadExplorerPath('${{thisPath}}')">${{p}}</span>`;
            }});
            bc.innerHTML = html;
        }}

        function renderExplorerListing(dirs, files) {{
            const listDiv = document.getElementById('explorerFsList');
            if (dirs.length === 0 && files.length === 0) {{
                listDiv.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">No items in this directory.</div>';
                return;
            }}

            let html = '';
            dirs.forEach(d => {{
                html += `
                    <div class="fs-row" onclick="loadExplorerPath('${{d.path}}')">
                        <div class="fs-name-col">
                            <span>📁</span>
                            <strong style="color: #f1f5f9;">${{d.name}}</strong>
                        </div>
                        <div class="fs-meta-col">
                            <span style="font-size: 0.72rem; color: var(--text-muted);">DIR</span>
                            <button type="button" class="btn" style="padding: 2px 8px; font-size: 0.72rem;" onclick="event.stopPropagation(); loadExplorerPath('${{d.path}}')">Open ➔</button>
                        </div>
                    </div>
                `;
            }});

            files.forEach(f => {{
                const sizeKb = Math.round((f.size || 0) / 1024 * 10) / 10;
                html += `
                    <div class="fs-row" onclick="inspectFile('${{f.path}}')">
                        <div class="fs-name-col">
                            <span>📄</span>
                            <span style="color: #cbd5e1;">${{f.name}}</span>
                        </div>
                        <div class="fs-meta-col">
                            <span>${{sizeKb}} KB</span>
                            <button type="button" class="btn" style="padding: 2px 8px; font-size: 0.72rem;" onclick="event.stopPropagation(); inspectFile('${{f.path}}')">View</button>
                        </div>
                    </div>
                `;
            }});

            listDiv.innerHTML = html;
        }}

        function filterExplorerListing(query) {{
            const q = query.toLowerCase().trim();
            const filteredDirs = explorerItemsCache.directories.filter(d => d.name.toLowerCase().includes(q));
            const filteredFiles = explorerItemsCache.files.filter(f => f.name.toLowerCase().includes(q));
            renderExplorerListing(filteredDirs, filteredFiles);
        }}

        async function inspectFile(path) {{
            currentPreviewPath = path;
            const codeBox = document.getElementById('previewCodeBox');
            codeBox.textContent = '// Reading file content...';
            try {{
                const res = await fetch(`/api/fs/explore?path=${{encodeURIComponent(path)}}`);
                const data = await res.json();
                previewFileContent(data);
            }} catch (err) {{
                codeBox.textContent = '// Failed to inspect file: ' + err.message;
            }}
        }}

        function previewFileContent(fileData) {{
            document.getElementById('previewFileName').textContent = fileData.name || 'File';
            document.getElementById('previewFilePath').textContent = fileData.path || '-';
            const sizeKb = Math.round((fileData.size || 0) / 1024 * 10) / 10;
            document.getElementById('previewFileSize').textContent = `${{sizeKb}} KB`;
            currentPreviewPath = fileData.path;

            const codeBox = document.getElementById('previewCodeBox');
            if (fileData.is_text) {{
                codeBox.textContent = fileData.preview || '// (Empty file)';
            }} else {{
                codeBox.textContent = `// Binary or non-text file (${{sizeKb}} KB).\n// Preview is disabled for safety.`;
            }}
        }}

        function selectForTaskContext(path) {{
            if (!path) path = currentExplorerPath;
            document.getElementById('taskContext').value = path;
            populateTargetDropdown(path);
            verifyTargetLocation(path);
            switchPanel('tasks');
        }}

        function dispatchTaskFromExplorer() {{
            const path = currentPreviewPath || currentExplorerPath;
            document.getElementById('taskContext').value = path;
            populateTargetDropdown(path);
            verifyTargetLocation(path);
            switchPanel('tasks');
            document.getElementById('taskPrompt').focus();
        }}

        // --- SSH & Credential Guard & Tenant Management ---
        async function loadSshKeys() {{
            try {{
                const res = await fetch('/api/ssh/keys');
                const data = await res.json();
                const tbody = document.getElementById('sshKeysTableBody');
                if (!tbody) return;
                tbody.innerHTML = '';
                const keys = data.keys || [];
                if (keys.length === 0) {{
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 16px;">No authorized SSH keys configured. Add one above.</td></tr>';
                    return;
                }}
                keys.forEach(k => {{
                    const tr = document.createElement('tr');
                    const isRevoked = k.status === 'revoked';
                    const fpShort = k.fingerprint ? k.fingerprint.substring(0, 18) + '...' : '-';
                    tr.innerHTML = `
                        <td><strong>${{k.label || 'Default'}}</strong></td>
                        <td><code style="font-size: 0.75rem;">${{k.key_type || 'ssh-rsa'}}</code></td>
                        <td><code style="font-size: 0.75rem;" title="${{k.fingerprint || ''}}">${{fpShort}}</code></td>
                        <td><span class="badge" style="background: rgba(14,165,233,0.15); color: #38bdf8;">${{k.access_level || 'admin'}}</span></td>
                        <td><span style="font-size: 0.8rem; color: var(--text-muted);">${{k.authorized_by || 'system'}}</span></td>
                        <td><span style="font-size: 0.8rem; color: var(--text-muted);">${{k.created_at || '-'}}</span></td>
                        <td>
                            ${{isRevoked 
                                ? '<span style="color: var(--rose); font-size: 0.8rem;">Revoked</span>' 
                                : `<button class="btn btn-rose" style="padding: 4px 8px; font-size: 0.75rem;" onclick="revokeSshKey('${{k.fingerprint}}')">Revoke</button>`
                            }}
                        </td>
                    `;
                    tbody.appendChild(tr);
                }});
            }} catch (err) {{
                console.error('Error loading SSH keys:', err);
            }}
        }}

        async function handleAuthorizeSsh(e) {{
            e.preventDefault();
            const label = document.getElementById('sshKeyLabel').value.trim();
            const accessLevel = document.getElementById('sshKeyAccessLevel').value;
            const publicKey = document.getElementById('sshPublicKeyInput').value.trim();
            if (!publicKey) return;

            try {{
                const res = await fetch('/api/ssh/authorize', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ label, access_level: accessLevel, public_key: publicKey }})
                }});
                const data = await res.json();
                if (data.status === 'success') {{
                    alert('✓ SSH Public Key authorized successfully and synced to ~/.ssh/authorized_keys');
                    document.getElementById('sshPublicKeyInput').value = '';
                    document.getElementById('sshKeyLabel').value = '';
                    loadSshKeys();
                }} else {{
                    alert('Error: ' + (data.error || 'Failed to authorize SSH key'));
                }}
            }} catch (err) {{
                alert('Request failed: ' + err.message);
            }}
        }}

        async function revokeSshKey(fingerprint) {{
            if (!confirm('Are you sure you want to revoke this SSH key? The user will immediately lose shell access.')) return;
            try {{
                const res = await fetch('/api/ssh/revoke', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ fingerprint }})
                }});
                const data = await res.json();
                if (data.status === 'success') {{
                    loadSshKeys();
                }} else {{
                    alert('Error revoking key: ' + (data.error || 'Unknown error'));
                }}
            }} catch (err) {{
                alert('Revocation request failed: ' + err.message);
            }}
        }}

        async function syncSshKeys() {{
            try {{
                const res = await fetch('/api/ssh/sync', {{ method: 'POST' }});
                const data = await res.json();
                if (data.status === 'success') {{
                    alert(`✓ Synced ${{data.synced_count}} authorized key(s) to ~/.ssh/authorized_keys`);
                    loadSshKeys();
                }} else {{
                    alert('Sync error: ' + (data.error || 'Unknown'));
                }}
            }} catch (err) {{
                alert('Sync request failed: ' + err.message);
            }}
        }}

        async function runGuardScan() {{
            const container = document.getElementById('guardFindingsContainer');
            if (!container) return;
            container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--primary);">🛡️ Scanning repository for credentials and secrets...</div>';
            try {{
                const res = await fetch('/api/security/guard-scan');
                const data = await res.json();
                const findings = data.findings || [];
                if (findings.length === 0) {{
                    container.innerHTML = `
                        <div style="padding: 20px; background: rgba(16,185,129,0.1); border: 1px solid #059669; border-radius: 8px; text-align: center;">
                            <span style="font-size: 1.4rem;">✅</span>
                            <h4 style="color: #34d399; margin: 8px 0 4px 0;">All Clear! No Credentials Detected</h4>
                            <p style="color: var(--text-muted); font-size: 0.85rem; margin: 0;">No API tokens, private keys, or passwords were discovered in active repository code.</p>
                        </div>
                    `;
                    return;
                }}
                let html = `
                    <div style="padding: 16px; background: rgba(244,63,94,0.1); border: 1px solid var(--rose); border-radius: 8px; margin-bottom: 16px;">
                        <h4 style="color: #fda4af; margin: 0 0 6px 0;">⚠️ Security Notice: ${{findings.length}} Potential Secret(s) Found</h4>
                        <p style="color: #fecdd3; font-size: 0.82rem; margin: 0;">These patterns will block git commit/push operations until sanitized.</p>
                    </div>
                    <table style="width: 100%;">
                        <thead>
                            <tr><th>File</th><th>Line</th><th>Pattern Rule</th><th>Matched Preview</th></tr>
                        </thead>
                        <tbody>
                `;
                findings.forEach(f => {{
                    html += `
                        <tr>
                            <td><code>${{f.file}}</code></td>
                            <td>${{f.line}}</td>
                            <td><span class="badge" style="background: rgba(244,63,94,0.15); color: #fda4af;">${{f.rule}}</span></td>
                            <td><code style="font-size: 0.75rem; color: #cbd5e1;">${{f.match}}</code></td>
                        </tr>
                    `;
                }});
                html += '</tbody></table>';
                container.innerHTML = html;
            }} catch (err) {{
                container.innerHTML = `<div style="padding: 16px; color: var(--rose);">Scan failed: ${{err.message}}</div>`;
            }}
        }}

        async function switchTenantPreset(presetKey) {{
            try {{
                const res = await fetch('/api/tenant-info?preset=' + encodeURIComponent(presetKey));
                const data = await res.json();
                const tenant = data.tenant || {{}};
                const allowedPanels = tenant.allowed_panels || ['overview'];

                // Filter visible sidebar items
                const panelNames = ['overview', 'tasks', 'explorer', 'self_improvement', 'database', 'security', 'ssh', 'guard', 'settings'];
                const navItems = document.querySelectorAll('.nav-item');
                panelNames.forEach((name, idx) => {{
                    if (navItems[idx]) {{
                        if (allowedPanels.includes(name)) {{
                            navItems[idx].style.display = 'flex';
                        }} else {{
                            navItems[idx].style.display = 'none';
                        }}
                    }}
                }});

                if (!allowedPanels.includes(currentPanel)) {{
                    switchPanel(tenant.default_panel || 'overview');
                }}
            }} catch (err) {{
                console.error('Failed to switch tenant preset:', err);
            }}
        }}

        async function loadTenantConfiguration() {{
            try {{
                const res = await fetch('/api/tenant-info');
                const data = await res.json();
                const tenant = data.tenant;
                if (tenant && tenant.role) {{
                    const sel = document.getElementById('tenantPresetSelect');
                    if (sel) sel.value = tenant.role;
                    switchTenantPreset(tenant.role);
                }}
            }} catch (err) {{
                console.error('Error loading tenant config:', err);
            }}
        }}

        // Initialize presets & poll
        loadPresets();
        fetchDashboard();
        loadTenantConfiguration();
        setInterval(fetchDashboard, 8000);
    </script>
</body>
</html>
"""

def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), AutonomousDashboardHandler) as httpd:
        print(f"[DashboardServer] Serving securely on 0.0.0.0:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run_server()
