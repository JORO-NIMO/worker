import os
import re
from core.database import record_vulnerability, log_event

SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "EXPOSED_SECRET", "HIGH", "Hardcoded API secret or access token detected"),
    (r"ghp_[A-Za-z0-9]{36}", "GITHUB_TOKEN", "CRITICAL", "GitHub Personal Access Token hardcoded in source"),
    (r"AKIA[0-9A-Z]{16}", "AWS_ACCESS_KEY", "CRITICAL", "AWS Access Key ID hardcoded in source"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "PRIVATE_KEY_EXPOSED", "CRITICAL", "Unencrypted private cryptographic key found in file"),
    (r"(?i)password\s*[:=]\s*['\"][^'\"]{4,}['\"]", "PLAINTEXT_PASSWORD", "MEDIUM", "Plaintext password assigned in source file"),
]

CODE_FLAW_PATTERNS = [
    (r"eval\(", "DANGEROUS_EVAL", "CRITICAL", "Use of eval() detected, posing severe remote code execution risk"),
    (r"subprocess\.(?:Popen|run|call)\(.*shell\s*=\s*True.*\)", "COMMAND_INJECTION_RISK", "HIGH", "subprocess invocation with shell=True"),
    (r"(?i)f['\"]SELECT.*WHERE.*\{.*\}['\"]", "SQL_INJECTION_RISK", "HIGH", "Potential SQL injection through f-string formatting in SQL query"),
    (r"allow_origins\s*=\s*\[['\"]\s*\*['\"]\s*\]", "OVERLY_PERMISSIVE_CORS", "MEDIUM", "CORS configured with wildcard '*' allowing any origin"),
    (r"debug\s*=\s*True", "DEBUG_MODE_ENABLED", "LOW", "Debug mode explicitly enabled in code"),
]

class SecurityAuditor:
    def __init__(self, llm_router=None):
        self.llm_router = llm_router

    def scan_file(self, project_name, file_path):
        if not os.path.isfile(file_path):
            return []

        # Skip binaries, virtual environments, and node_modules
        if any(ignored in file_path for ignored in ["node_modules", "venv", ".git", ".idea", "__pycache__", ".tar.gz"]):
            return []

        findings = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            for line_no, line in enumerate(lines, start=1):
                # 1. Secret patterns
                for pattern, vuln_type, severity, desc in SECRET_PATTERNS:
                    if re.search(pattern, line):
                        proposal = "Extract credentials to an environment variable or secret manager."
                        record_vulnerability(project_name, file_path, line_no, severity, vuln_type, desc, proposal)
                        findings.append({
                            "file": file_path,
                            "line": line_no,
                            "severity": severity,
                            "type": vuln_type,
                            "description": desc
                        })

                # 2. Code flaw patterns
                for pattern, vuln_type, severity, desc in CODE_FLAW_PATTERNS:
                    if re.search(pattern, line):
                        proposal = "Refactor to use parameterized execution or safe library alternatives."
                        record_vulnerability(project_name, file_path, line_no, severity, vuln_type, desc, proposal)
                        findings.append({
                            "file": file_path,
                            "line": line_no,
                            "severity": severity,
                            "type": vuln_type,
                            "description": desc
                        })

        except Exception as e:
            log_event("AUDIT_ERROR", f"Error scanning {file_path}: {e}")

        return findings

    def scan_project(self, project_name, project_path, max_files=150):
        total_findings = []
        count = 0
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ["node_modules", "venv", ".git", "__pycache__", ".idea"]]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in [".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".env", ".sh", ".sql"]:
                    full_path = os.path.join(root, file)
                    findings = self.scan_file(project_name, full_path)
                    total_findings.extend(findings)
                    count += 1
                    if count >= max_files:
                        break
            if count >= max_files:
                break

        log_event("PROJECT_AUDIT_COMPLETE", f"Audited {project_name}: {len(total_findings)} findings across {count} files")
        return total_findings
