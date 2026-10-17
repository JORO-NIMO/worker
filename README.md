# Autonomous Agent Worker and Server Management Platform

An autonomous agent worker and server management system running on Linux environments. Built for local LLM orchestration (Qwen Coder and DeepSeek Reasoning via Ollama) with chain-of-thought task execution, Docker containerization, dynamic database auditing, continuous project learning, multi-tenant subdomain dashboard routing, dashboard-enforced SSH key management, and pre-commit Credential Guard leak prevention.

---

## Table of Contents
1. [Overview and Core Capabilities](#overview-and-core-capabilities)
2. [Repository Architecture](#repository-architecture)
3. [Prerequisites and System Requirements](#prerequisites-and-system-requirements)
4. [Installation and Setup](#installation-and-setup)
5. [Docker Containerization](#docker-containerization)
6. [Autonomous Project Learning Engine](#autonomous-project-learning-engine)
7. [Multi-Tenant Subdomain Dashboards](#multi-tenant-subdomain-dashboards)
8. [Dashboard-Enforced SSH Authorization](#dashboard-enforced-ssh-authorization)
9. [Credential Guard and Secret Prevention](#credential-guard-and-secret-prevention)
10. [CLI Reference (workerctl)](#cli-reference-workerctl)
11. [Branch Protection and Repository Rules](#branch-protection-and-repository-rules)
12. [Contribution Workflow](#contribution-workflow)

---

## Overview and Core Capabilities

* **Autonomous Task Daemon**: Operates continuously as a systemd service or Docker container, consuming priority tasks from an ACID SQLite database.
* **Knowledge-Augmented Brain**: Analyzes server codebases, routes, models, and Docker topologies, augmenting model prompts with learned server context before planning.
* **Proactive Maintenance Cycles**: Automatically triggers security audits, model self-improvement benchmarks, and server topology refresh routines every 30 minutes.
* **Zero-Credential Public Cloning**: Hardened with pre-commit and pre-push filters preventing secret exposure, allowing public repository collaboration.
* **Multi-Tenant Dashboard**: Routes incoming traffic by hostname or subdomain to serve role-specific operational presets (DevOps, Security, AI, Developer, Unified Master).
* **Controlled SSH Access**: Removes uncontrolled shell access; authorized public keys are registered, fingerprint-indexed, and synced exclusively through the authenticated interface.

---

## Repository Architecture

```
/var/www/worker/
├── Dockerfile                  # Hardened multi-stage container specification
├── docker-compose.yml          # Container orchestration with volume and network bindings
├── docker-entrypoint.sh        # Container startup and privilege drop script
├── requirements.txt            # Minimal Python dependencies (requests, psutil)
├── .env.example                # Environment variable configuration template
├── config.example.json         # Daemon configuration template
├── .gitignore                  # Exclusion patterns for databases, keys, and environments
├── .dockerignore               # Build context filter
├── .githooks/                  # Git security hooks
│   ├── pre-commit              # Enforces local credential scanning before commit
│   └── pre-push                # Enforces local credential scanning before push
├── bin/
│   └── workerctl               # Unified administrative control CLI
├── core/
│   ├── agent_brain.py          # Central coordinator with learned context augmentation
│   ├── database.py             # SQLite WAL engine with migrations and audit logs
│   ├── llm_router.py           # Model dispatcher (Ollama and OpenAI-compatible APIs)
│   ├── model_self_improvement.py # Reflexion loop and coding benchmark runner
│   └── worker_daemon.py        # Background task processor and dashboard launcher
├── data/                       # Local SQLite state storage (excluded from git)
│   └── .gitkeep
├── tools/
│   ├── code_engine.py          # Code modification engine
│   ├── credential_guard.py     # Static secret, token, and private key scanner
│   ├── db_manager.py           # Database migration and structure auditor
│   ├── project_learner.py      # Server codebase, route, and container indexer
│   ├── security_auditor.py     # Code vulnerability and privilege auditor
│   ├── ssh_manager.py          # Authorized keys manager with SHA256 fingerprints
│   └── system_scaler.py        # System resource monitor and OOM preventer
└── web/
    ├── dashboard_server.py     # HTTP/2 compatible SPA management dashboard (:8888)
    ├── security_middleware.py  # IP whitelisting and session authentication
    └── tenant_manager.py       # Subdomain and preset persona routing
```

---

## Prerequisites and System Requirements

* **Operating System**: Linux (Ubuntu 22.04 LTS or 24.04 LTS recommended)
* **Python**: Python 3.10 or higher
* **Memory**: Minimum 4 GB RAM (8 GB or higher recommended if running local LLMs)
* **Local Inference**: Ollama with `qwen2.5-coder:1.5b` or `qwen2.5-coder:7b`, and `deepseek-r1`
* **Network**: Cloudflare Tunnel or reverse proxy (Nginx) for public ingress

---

## Installation and Setup

### 1. Host Installation (Systemd Service)

```bash
# Clone the repository
git clone https://github.com/JORO-NIMO/worker.git /var/www/worker
cd /var/www/worker

# Install dependencies
pip3 install -r requirements.txt

# Configure environment
cp .env.example .env
cp config.example.json config.json

# Install CLI tool globally
sudo ln -sf /var/www/worker/bin/workerctl /usr/local/bin/workerctl

# Install git security hooks
workerctl install-hooks

# Verify installation and system metrics
workerctl status
```

### 2. Service Configuration

Create `/etc/systemd/system/agent-worker.service`:

```ini
[Unit]
Description=Autonomous Agent and Continuous Worker Service
After=network.target docker.service

[Service]
Type=simple
User=ishabarundo
WorkingDirectory=/var/www/worker
ExecStart=/usr/bin/python3 -m core.worker_daemon
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable and start the daemon:

```bash
sudo systemctl daemon-reload
sudo systemctl enable agent-worker.service
sudo systemctl start agent-worker.service
```

---

## Docker Containerization

To run the worker in an isolated Docker container:

```bash
# Build and start in detached mode
docker compose up -d --build

# Inspect container health and logs
docker compose ps
docker compose logs -f worker
```

Container characteristics:
* Runs as dedicated non-root user `worker` (UID 1001).
* Host communication via `host.docker.internal:11434` for Ollama inference.
* Persistent SQLite state stored in named volume mapped to `./data`.
* Automated health check against `http://localhost:8888/login`.

---

## Autonomous Project Learning Engine

The Autonomous Project Learner (`tools/project_learner.py`) indexes the local server environment and records discoveries into the `server_knowledge` table in `data/worker.db`.

### Capabilities:
1. **Framework and Dependency Discovery**: Identifies Python packages, Node.js modules, and Composer requirements across all server directories.
2. **API Route Mapping**: Scans Python (FastAPI/Flask) and Node.js (Express) route definitions.
3. **Model and Database Inspection**: Locates SQLite databases, schema classes, and SQL migrations.
4. **Docker Topology Inspection**: Monitors active containers, status, and port bindings.
5. **Ingress Topology**: Parses Cloudflare tunnel configurations (`/etc/cloudflared/*.yml`).

### Running the Learner:

```bash
# Direct CLI execution
workerctl learn

# Or via the dashboard API
curl -X POST http://localhost:8888/api/learn -H "Cookie: session_token=<TOKEN>"
```

The learned context is automatically integrated into `AgentBrain` prompts during task planning.

---

## Multi-Tenant Subdomain Dashboards

The web dashboard detects incoming host headers and matches them to operational presets:

| Host / Subdomain Pattern | Preset Persona | Primary Focus | Visible Panels |
| :--- | :--- | :--- | :--- |
| `devops.*` or `infra.*` | DevOps and Infrastructure | System metrics, scaling, filesystem | Overview, Tasks, File Explorer, Settings |
| `security.*` or `audit.*` | Security and Audit | SSH keys, firewall, secret scanner | Overview, Security Whitelist, SSH Keys, Credential Guard |
| `ai.*` or `ml.*` | AI and Models | Benchmarks, self-improvement cycles | Overview, Tasks, Self-Improvement, Settings |
| `dev.*` or `code.*` | Developer and Code | Task queues, code explorer, database | Overview, Tasks, File Explorer, Database |
| Default / Root Host | Unified Master | Complete administrative control | All panels enabled |

---

## Dashboard-Enforced SSH Authorization

Manual modifications to `~/.ssh/authorized_keys` are replaced with dashboard authorization:

1. Authenticate to the dashboard (`http://localhost:8888/login` or configured tunnel).
2. Open the **SSH Key Management** view.
3. Submit the developer's public key (`ssh-ed25519`, `ssh-rsa`, or `ecdsa`).
4. Set the username, label, and expiration duration (default: 30 days).
5. The system computes the SHA256 fingerprint, logs the grant in the audit trail, and synchronizes `~/.ssh/authorized_keys`.

Keys can be revoked instantly from the UI or via CLI:

```bash
# List active keys
workerctl ssh list

# Revoke a key by fingerprint or ID
workerctl ssh revoke <SHA256_FINGERPRINT>
```

---

## Credential Guard and Secret Prevention

To ensure safe public repository cloning and collaborative contribution:

* **Active Hook Scanning**: `tools/credential_guard.py` is invoked during `pre-commit` and `pre-push`.
* **Pattern Detection**:
  * Private keys (`-----BEGIN ... PRIVATE KEY-----`)
  * OpenAI, Claude, and Gemini API keys (`sk-proj-*`, `sk-ant-*`, `AIza*`)
  * Cloud credentials (AWS access keys, GCP service accounts)
  * GitHub personal access tokens (`ghp_*`, `gho_*`)
  * Database connection strings with embedded passwords
  * SQLite database binary files (`*.db`, `*.sqlite`, `*.sqlite3`)
* If a secret is detected, the git operation is aborted with an error identifying the exact file and line number.

---

## CLI Reference (workerctl)

```bash
# View real-time status of worker, queue, and recent runs
workerctl status

# Run an on-demand server project learning cycle
workerctl learn

# Enqueue an autonomous task
workerctl add-task --title "Audit fastfats API" --type security_audit --prompt "Scan for insecure endpoints" --context "/var/www/Fastfats"

# Execute a single pending task immediately
workerctl run-once

# Run code credential guard check
workerctl guard --target all

# Manage SSH authorizations
workerctl ssh list
workerctl ssh authorize --user dev1 --key "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5..." --comment "MacBook Pro"
workerctl ssh revoke <FINGERPRINT>
workerctl ssh sync

# Verify local LLM memory headroom and tier recommendation
workerctl test-models
```

---

## Branch Protection and Repository Rules

To protect production stability and prevent unauthorized changes or secret leaks from reaching the `main` branch, configure the following protection rules in GitHub.

### 1. Protected Branch Settings for `main`

Navigate to **GitHub Repository -> Settings -> Branches -> Add branch protection rule** (or **Rulesets -> New ruleset**).

Apply to branch pattern: `main`

Enable the following rules:

1. **Require a pull request before merging**:
   * Require review approvals: Set to at least **1 approval**.
   * Dismiss stale pull request approvals when new commits are pushed: **Enabled**.
   * Require review from Code Owners: **Optional** (if CODEOWNERS file is maintained).
   * Restrict who can dismiss pull request reviews: **Enabled** (Repository administrators only).

2. **Require status checks to pass before merging**:
   * Require branches to be up to date before merging: **Enabled**.
   * Status checks to require: Add GitHub Actions CI (e.g., `Credential Guard Scan`, `Python Lint / Test`).

3. **Require conversation resolution before merging**:
   * **Enabled** (all comments and review threads must be resolved before merge).

4. **Do not allow bypassing the above settings**:
   * **Enabled** (enforces rules even for repository administrators).

5. **Restrict who can push to matching branches**:
   * Restrict direct pushes: **Enabled**.
   * Specify who can push: Only organization owners / repository administrators.
   * Direct push without PR should be blocked for all standard contributors.

6. **Block force pushes**:
   * **Enabled** (prevents `git push --force` or `--force-with-lease` on `main`).

7. **Block branch deletions**:
   * **Enabled** (prevents deletion of `main`).

---

### 2. GitHub Ruleset Definition (Modern Ruleset Configuration)

If using GitHub **Repository Rulesets**:

1. Target: **Default branch** (`main`).
2. Enforcement status: **Active**.
3. Roles / Bypass list: Repository Admin (Emergency only).
4. Rules:
   * **Restrict creations**: Restrict creating branches named `main` or matching releases.
   * **Restrict updates**: Require Pull Request with 1 approval.
   * **Restrict deletions**: Prevent branch deletion.
   * **Block force pushes**: Prevent history overwrites.
   * **Require linear history**: Prevent merge commits (squash or rebase only).
   * **Require signed commits**: Require GPG/SSH verified commit signatures (recommended).

---

### 3. Allowed Branching Conventions for Contributors

Contributors cannot push directly to `main`. All development must occur on topic branches:

* Feature branches: `feature/<descriptive-name>`
* Bugfix branches: `fix/<issue-name>`
* Documentation branches: `docs/<topic>`
* Refactoring branches: `refactor/<target>`

---

## Contribution Workflow

1. **Clone and Configure**:
   ```bash
   git clone https://github.com/JORO-NIMO/worker.git
   cd worker
   workerctl install-hooks
   ```

2. **Branch from main**:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/my-feature
   ```

3. **Verify Clean Credentials**:
   ```bash
   workerctl guard --target staged
   ```

4. **Commit and Push**:
   ```bash
   git commit -m "feat: implement feature description"
   git push -u origin feature/my-feature
   ```

5. **Open Pull Request**:
   * Submit a Pull Request from `feature/my-feature` targeting `main`.
   * Ensure all automated checks pass.
   * A repository maintainer will review and merge via squash or rebase.

---

## License

This software is maintained for server management and internal infrastructure automation. Licensed under the MIT License.
