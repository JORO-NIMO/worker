"""
Credential & Secret Guard for Autonomous Worker
Detects hardcoded secrets, API keys, private cryptographic keys, and prevents
unauthorized pushes or commits containing sensitive credentials.
"""

import os
import re
import sys
import subprocess

CREDENTIAL_PATTERNS = [
    # Private Cryptographic Keys
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----", "PRIVATE_KEY", "CRITICAL", "Unencrypted private cryptographic key"),
    (r"-----BEGIN ENCRYPTED PRIVATE KEY-----", "ENCRYPTED_PRIVATE_KEY", "HIGH", "Encrypted private key file"),
    
    # Cloud & Git Tokens
    (r"ghp_[A-Za-z0-9]{36}", "GITHUB_PERSONAL_ACCESS_TOKEN", "CRITICAL", "GitHub Personal Access Token"),
    (r"github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}", "GITHUB_FINE_GRAINED_PAT", "CRITICAL", "GitHub Fine-Grained Personal Access Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS_ACCESS_KEY_ID", "CRITICAL", "AWS Access Key ID"),
    (r"(?i)aws_secret_access_key\s*[:=]\s*['\"][A-Za-z0-9/+=]{40}['\"]", "AWS_SECRET_KEY", "CRITICAL", "AWS Secret Access Key"),
    
    # AI & API Providers
    (r"sk-proj-[A-Za-z0-9_\-]{40,}", "OPENAI_PROJECT_API_KEY", "CRITICAL", "OpenAI Project API Key"),
    (r"sk-[A-Za-z0-9]{48}", "OPENAI_API_KEY", "CRITICAL", "OpenAI Legacy API Key"),
    (r"sk-ant-[A-Za-z0-9_\-]{40,}", "ANTHROPIC_API_KEY", "CRITICAL", "Anthropic API Key"),
    (r"AIzaSy[A-Za-z0-9_\-]{33}", "GOOGLE_API_KEY", "CRITICAL", "Google Gemini / API Key"),
    (r"hf_[A-Za-z0-9]{34,}", "HUGGINGFACE_TOKEN", "CRITICAL", "Hugging Face Access Token"),
    
    # Generic & DB Secrets
    (r"(?i)(?:postgres|mysql|mongodb|redis)://[^:]+:[^@]+@[^/]+", "DB_URI_WITH_PASSWORD", "HIGH", "Database connection URI with embedded password"),
    (r"(?i)(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]", "GENERIC_API_SECRET", "HIGH", "Generic high-entropy API key or secret"),
    (r"(?i)bearer\s+ey[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}", "JWT_BEARER_TOKEN", "HIGH", "Exposed JWT Bearer Token"),
]

BLOCKED_FILENAMES = [
    r"^.*\.pem$",
    r"^.*\.key$",
    r"^id_rsa$",
    r"^id_ed25519$",
    r"^id_ecdsa$",
    r"^\.env$",
    r"^\.env\.local$",
    r"^.*\.db$",
    r"^.*\.sqlite3?$",
]

class CredentialGuard:
    def __init__(self, repo_root=None):
        self.repo_root = repo_root or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def check_filename(self, filename: str) -> list:
        basename = os.path.basename(filename)
        findings = []
        for pattern in BLOCKED_FILENAMES:
            if re.match(pattern, basename, re.IGNORECASE):
                findings.append({
                    "file": filename,
                    "rule": "BLOCKED_FILE_EXTENSION",
                    "severity": "CRITICAL",
                    "description": f"Sensitive file '{basename}' must not be committed to version control"
                })
        return findings

    def scan_content(self, filename: str, content: str) -> list:
        if filename.endswith("credential_guard.py"):
            return []
        findings = []
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            if any(marker in line for marker in ["credential_guard.py", "CREDENTIAL_PATTERNS", "EXAMPLE_"]):
                continue
            for pattern, rule_id, severity, desc in CREDENTIAL_PATTERNS:
                if re.search(pattern, line):
                    findings.append({
                        "file": filename,
                        "line": idx,
                        "rule": rule_id,
                        "severity": severity,
                        "description": desc,
                        "preview": line.strip()[:80]
                    })
        return findings

    def scan_staged_git(self) -> list:
        findings = []
        try:
            res = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=self.repo_root, capture_output=True, text=True)
            files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
        except Exception:
            return []

        for f in files:
            full_path = os.path.join(self.repo_root, f)
            findings.extend(self.check_filename(f))
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()
                    findings.extend(self.scan_content(f, content))
                except Exception:
                    pass
        return findings

    def is_git_ignored(self, rel_path: str) -> bool:
        norm = rel_path.replace("\\", "/")
        try:
            res = subprocess.run(
                ["git", "check-ignore", "-q", norm],
                cwd=self.repo_root,
                capture_output=True
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

        # Fallback heuristic for uninitialized repo or standard ignore rules
        if (norm.startswith("data/") or norm.startswith("logs/") or 
            norm.endswith(".db") or norm.endswith(".sqlite") or 
            norm.endswith(".sqlite3") or norm.endswith(".log") or
            norm == "config.json" or (norm.startswith(".env") and norm != ".env.example")):
            return True
        return False

    def scan_directory(self, target_dir: str = None) -> list:
        target = target_dir or self.repo_root
        findings = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in [".git", "node_modules", "venv", "__pycache__"]]
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.repo_root)
                if self.is_git_ignored(rel_path):
                    continue
                findings.extend(self.check_filename(rel_path))
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
                        findings.extend(self.scan_content(rel_path, fp.read()))
                except Exception:
                    pass
        return findings

def main():
    guard = CredentialGuard()
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan-git"

    if mode == "scan-git":
        findings = guard.scan_staged_git()
    elif mode == "scan-all":
        findings = guard.scan_directory()
    else:
        target = sys.argv[1]
        findings = guard.scan_directory(target)

    if findings:
        print("\n\033[91m=====================================================\033[0m")
        print("\033[91m[SECURITY ALERT] CREDENTIAL / SECRET LEAK DETECTED!\033[0m")
        print("\033[91mCommit/Push aborted to protect server & personal keys.\033[0m")
        print("\033[91m=====================================================\033[0m\n")
        for item in findings:
            loc = f"{item['file']}:{item.get('line', '-')}"
            print(f"  \033[93m[{item['severity']}]\033[0m \033[1m{item['rule']}\033[0m in \033[4m{loc}\033[0m")
            print(f"    Detail: {item['description']}")
            if "preview" in item:
                print(f"    Preview: \"{item['preview']}\"")
            print("")
        print("\033[96mRemediation Guidance:\033[0m")
        print("  1. Remove hardcoded credentials from the file.")
        print("  2. Move secrets to environment variables or config.example.json.")
        print("  3. Ensure sensitive files (.env, *.db, *.key) are listed in .gitignore.")
        print("  4. Unstage blocked files with: git reset HEAD <file>\n")
        sys.exit(1)
    else:
        print("\033[92m[CREDENTIAL-GUARD] No exposed credentials detected. Repository safe to commit/push.\033[0m")
        sys.exit(0)

if __name__ == "__main__":
    main()
