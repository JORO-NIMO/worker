# Autonomous Agent Worker & Continuous Server Management Platform

An autonomous, continuous agent worker and server management system running locally on the server. Powered by local LLMs (Qwen Coder & DeepSeek Reasoning via Ollama) with chain-of-thought task execution, containerized Docker deployment, dynamic database management, self-healing code iteration, multi-tenant subdomain dashboard routing, dashboard-only SSH key authorization, and automated Credential Guard leak prevention.

---

## Table of Contents
1. [Architecture & Components](#architecture--components)
2. [Docker Containerization](#docker-containerization)
3. [Multi-Tenant Subdomain Dashboards](#multi-tenant-subdomain-dashboards)
4. [SSH Authorization via Dashboard](#ssh-authorization-via-dashboard)
5. [Credential Guard & Secret Scanner](#credential-guard--secret-scanner)
6. [Public Contribution & Branching Guide](#public-contribution--branching-guide)
7. [CLI Management with `workerctl`](#cli-management-with-workerctl)

---

## Architecture & Components

```
/var/www/worker/
├── Dockerfile                  # Multi-stage hardened production container
├── docker-compose.yml          # Container orchestration with volume & network bindings
├── docker-entrypoint.sh        # Container startup & permission initialization
├── requirements.txt            # Python dependencies (requests, psutil)
├── .env.example                # Sanitized environment variable template
├── config.example.json         # Sanitized daemon configuration template
├── .gitignore                  # Comprehensive secret and database ignore patterns
├── .dockerignore               # Container build isolation
├── .githooks/                  # Enforcing Git hooks
│   ├── pre-commit              # Credential guard pre-commit scanner
│   └── pre-push                # Credential guard pre-push scanner
├── bin/
│   └── workerctl               # Unified management CLI
├── core/
│   ├── agent_brain.py          # Decision-making coordinator (Think -> Act -> Evaluate)
│   ├── database.py             # SQLite WAL persistence with automated migrations
│   ├── llm_router.py           # Model dispatcher (Qwen 2.5 Coder & DeepSeek R1)
│   ├── model_self_improvement.py # Autonomous prompt & benchmark engine
│   └── worker_daemon.py        # Background task worker loop
├── tools/
│   ├── code_engine.py          # Safe filesystem & codebase modification engine
│   ├── credential_guard.py     # Live token, key, and password leak detector
│   ├── db_manager.py           # Database migration & schema auditor
│   ├── security_auditor.py     # Static code & permission vulnerability auditor
│   ├── ssh_manager.py          # Authorized keys registry & fingerprint manager
│   └── system_scaler.py        # CPU/RAM/Swap headroom monitor & OOM governor
└── web/
    ├── dashboard_server.py     # Real-time SPA dashboard with dark UI (:8888)
    ├── security_middleware.py  # IP whitelisting & session validation
    └── tenant_manager.py       # Subdomain & persona resolution engine
```

---

## Docker Containerization

The project is fully containerized using a hardened multi-stage Docker build running under a non-root `worker` user.

### Quick Start with Docker Compose

```bash
# 1. Clone repository
git clone https://github.com/JORO-NIMO/worker.git
cd worker

# 2. Initialize environment config from templates
cp .env.example .env
cp config.example.json config.json

# 3. Build and launch container
docker compose up -d

# 4. View real-time container logs
docker compose logs -f
```

### Docker Features
* **Non-Root Execution**: Runs under isolated UID `1001` (`worker`) for least-privilege security.
* **Volume Persistence**: Named volumes `./data` (SQLite database) and `./logs` persist across container restarts.
* **Local Host AI Gateway**: Connects directly to host Ollama models via `host.docker.internal:11434`.
* **Built-in Healthchecks**: Probes `http://localhost:8888/login` every 30 seconds with automated failure detection.

---

## Multi-Tenant Subdomain Dashboards

The dashboard server automatically detects incoming request hosts and query presets to serve tailored, role-based dashboards for different users and teams:

| Subdomain Pattern | Preset Persona | Primary Focus | Visible Panels |
| :--- | :--- | :--- | :--- |
| `devops.*` or `infra.*` | **DevOps & Infra** | Server metrics, scaling, filesystem explorer | Overview, Tasks, File Explorer, Settings |
| `security.*` or `audit.*` | **Security & Auditor** | SSH authorizations, firewall, secret guard | Overview, Security & Whitelist, SSH Keys, Credential Guard |
| `ai.*` or `ml.*` | **AI & Models** | Model benchmarks, reasoning self-improvement | Overview, Tasks, Self-Improvement, Settings |
| `dev.*` or `code.*` | **Developer & Code** | Task dispatching, codebase explorer, database | Overview, Tasks, File Explorer, Database |
| (Default / Root host) | **Unified Master** | Full administrative access | All panels enabled |

Tenants can also switch between configured presets seamlessly from the dashboard top-bar view switcher without modifying backend code.

---

## SSH Authorization via Dashboard

To enforce zero unauthorized shell access, SSH public keys cannot be manually appended by unauthenticated users. Shell access is centrally managed through the authenticated web dashboard:

1. Log in to the dashboard at `http://<server-ip>:8888` or your configured tunnel.
2. Navigate to the **SSH Authorization** panel.
3. Paste the developer's public key (`ssh-ed25519`, `ssh-rsa`, or `ecdsa`).
4. Select the access role (`Administrator`, `Developer`, or `Read-Only`).
5. Click **Authorize & Install Key**.

The dashboard automatically:
* Calculates the SHA256 key fingerprint.
* Records the authorizing administrator and timestamp in the SQLite database.
* Safely updates and prunes `~/.ssh/authorized_keys` with file locking.
* Allows instant one-click key revocation directly from the web interface.

---

## Credential Guard & Secret Scanner

To enable safe public cloning and open-source contributions without risking server or personal API keys:

1. **Pre-Commit & Pre-Push Hooks**: Automatically scan staged changes and outgoing commits using `tools/credential_guard.py`.
2. **Blocked Patterns**:
   * Private cryptographic keys (OpenSSH / PEM / RSA / ED25519 format)
   * OpenAI API keys (`sk-proj-...`)
   * Anthropic Claude keys (`sk-ant-...`)
   * Google Gemini API keys (`AIza...`)
   * AWS Access Keys (`AKIA...`)
   * GitHub Personal Access Tokens (`ghp_...`, `gho_...`)
   * Database connection URIs containing embedded passwords
   * Hardcoded database files (`*.db`, `*.sqlite*`)
3. **Automated Enforcement**: Any commit or push containing matched secrets is immediately aborted with remediation instructions.

---

## Public Contribution & Branching Guide

This repository is designed so anyone can clone and contribute freely without exposing host credentials:

```bash
# 1. Clone repository
git clone https://github.com/JORO-NIMO/worker.git
cd worker

# 2. Install Git protection hooks
./bin/workerctl install-hooks

# 3. Create your own feature branch
git checkout -b feature/my-new-enhancement

# 4. Make changes and run credential check
python3 tools/credential_guard.py scan-git

# 5. Commit and push your branch
git add .
git commit -m "feat: describe your enhancement"
git push origin feature/my-new-enhancement
```

---

## CLI Management with `workerctl`

The included `workerctl` script provides instant CLI control over the worker daemon, SSH authorizations, and security auditing:

```bash
# Check daemon and system status
./bin/workerctl status

# Start, stop, or restart the agent service
sudo ./bin/workerctl start
sudo ./bin/workerctl restart

# Manage SSH key authorizations
./bin/workerctl ssh list
./bin/workerctl ssh authorize "John Laptop" "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5..."
./bin/workerctl ssh revoke <fingerprint>
./bin/workerctl ssh sync

# Run security and credential checks
./bin/workerctl audit
./bin/workerctl guard

# Install Git hooks to prevent credential leaks
./bin/workerctl install-hooks
```

---

# worker
