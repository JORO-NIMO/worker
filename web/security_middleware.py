import http.cookies
import ipaddress
from core.database import (
    is_ip_allowed, validate_session, log_event
)

def extract_client_ip(headers, client_address) -> str:
    # 1. Cloudflare Connecting IP header
    cf_ip = headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()

    # 2. X-Forwarded-For (take the first/original client IP)
    x_forwarded = headers.get("X-Forwarded-For")
    if x_forwarded:
        first_ip = x_forwarded.split(",")[0].strip()
        if first_ip:
            return first_ip

    # 3. X-Real-IP
    real_ip = headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # 4. Socket peer address
    if client_address and isinstance(client_address, (list, tuple)) and len(client_address) > 0:
        return str(client_address[0])
    return "127.0.0.1"

def parse_session_token(cookie_header: str) -> str:
    if not cookie_header:
        return ""
    try:
        cookie = http.cookies.SimpleCookie(cookie_header)
        if "session_token" in cookie:
            return cookie["session_token"].value
    except Exception:
        pass
    return ""

def verify_request_access(headers, client_address, enforce_ip_whitelist: bool = True) -> tuple[bool, str, str]:
    """
    Validates request IP against authorized IP networks.
    Returns: (is_allowed, client_ip, reason_if_blocked)
    """
    client_ip = extract_client_ip(headers, client_address)

    if not enforce_ip_whitelist:
        return True, client_ip, "IP whitelist disabled in configuration"

    if is_ip_allowed(client_ip):
        return True, client_ip, "Authorized IP"
    else:
        log_event("SECURITY_BLOCKED_IP", f"Access rejected for untrusted IP: {client_ip}", ip_address=client_ip)
        return False, client_ip, f"Access Restricted: IP address '{client_ip}' is not in the authorized whitelist."

def get_forbidden_html(client_ip: str, domain: str = "agent.safespaceshub.com") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>403 Forbidden - Access Restricted</title>
    <style>
        :root {{
            --bg: #090d16;
            --card: #111827;
            --border: #1f2937;
            --red: #ef4444;
            --text: #f9fafb;
            --muted: #9ca3af;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }}
        .box {{
            background: var(--card);
            border: 1px solid var(--border);
            border-top: 4px solid var(--red);
            border-radius: 12px;
            max-width: 520px;
            width: 100%;
            padding: 36px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
            text-align: center;
        }}
        .icon {{
            font-size: 3rem;
            margin-bottom: 16px;
        }}
        h1 {{
            font-size: 1.5rem;
            color: var(--red);
            margin-bottom: 12px;
            font-weight: 700;
        }}
        p {{
            color: var(--muted);
            font-size: 0.95rem;
            line-height: 1.6;
            margin-bottom: 24px;
        }}
        .ip-pill {{
            background: #1f2937;
            border: 1px solid #374151;
            padding: 8px 16px;
            border-radius: 8px;
            display: inline-block;
            font-family: monospace;
            font-size: 1rem;
            color: #60a5fa;
            margin-bottom: 24px;
        }}
        .footer {{
            border-top: 1px solid var(--border);
            padding-top: 18px;
            font-size: 0.8rem;
            color: #6b7280;
        }}
    </style>
</head>
<body>
    <div class="box">
        <div class="icon">🛡️</div>
        <h1>403 Forbidden: Access Restricted</h1>
        <p>This autonomous system is restricted to authenticated and verified IP addresses. Your IP address is not authorized to access this private terminal.</p>
        <div class="ip-pill">Your IP: {client_ip}</div>
        <div class="footer">
            Protected by Cloudflare & Autonomous Security Layer &bull; {domain}
        </div>
    </div>
</body>
</html>
"""
