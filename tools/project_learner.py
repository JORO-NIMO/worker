import os
import sys
import json
import re
import subprocess
from datetime import datetime

# Ensure worker root directory is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.database import get_connection, log_event

class ProjectLearner:
    """
    Autonomous Knowledge Engine:
    Discovers, inspects, and learns from all codebases, services, containers,
    and configurations residing on the server.
    """

    DEFAULT_TARGETS = [
        {"name": "SignLanguage ASL Platform", "path": "/var/www/signlanguage", "type": "python_ml"},
        {"name": "Server Orchestrator", "path": "/opt/orchestrator", "type": "nodejs_service"},
        {"name": "Interledger Payment Gateway", "path": "/home/ishabarundo/interledger", "type": "nodejs_fullstack"},
        {"name": "Worker Autonomous Brain", "path": "/var/www/worker", "type": "agent_system"},
        {"name": "Fastfats", "path": "/var/www/Fastfats", "type": "web_app"},
        {"name": "WordPress Site", "path": "/var/www/wordpress", "type": "php_cms"},
    ]

    def __init__(self, db_conn=None):
        self.conn = db_conn or get_connection()
        self._ensure_table()

    def _ensure_table(self):
        with self.conn:
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS server_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                project_path TEXT NOT NULL,
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_name, category)
            );
            """)

    def save_knowledge(self, project_name: str, project_path: str, category: str, summary: str, details: dict):
        with self.conn:
            self.conn.execute("""
            INSERT INTO server_knowledge (project_name, project_path, category, summary, details_json, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_name, category) DO UPDATE SET
                project_path = excluded.project_path,
                summary = excluded.summary,
                details_json = excluded.details_json,
                updated_at = CURRENT_TIMESTAMP;
            """, (project_name, project_path, category, summary, json.dumps(details, indent=2)))

    def inspect_dependencies(self, project_path: str) -> dict:
        deps = {"python": [], "node": [], "php": [], "system": []}

        # Python
        for req_file in ["requirements.txt", "pyproject.toml", "Pipfile"]:
            req_path = os.path.join(project_path, req_file)
            if os.path.exists(req_path):
                try:
                    with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                        deps["python"].extend(lines[:40])
                except Exception:
                    pass

        # Node.js
        pkg_path = os.path.join(project_path, "package.json")
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    deps["node"] = list({**data.get("dependencies", {}), **data.get("devDependencies", {})}.keys())
            except Exception:
                pass

        # Composer / PHP
        comp_path = os.path.join(project_path, "composer.json")
        if os.path.exists(comp_path):
            try:
                with open(comp_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    deps["php"] = list(data.get("require", {}).keys())
            except Exception:
                pass

        return deps

    def extract_api_endpoints(self, project_path: str) -> list:
        endpoints = []
        route_patterns = [
            (r'@(?:app|router)\.(get|post|put|delete|patch)\([\'"]([^\'"]+)[\'"]', "python"),
            (r'(?:app|router)\.(get|post|put|delete|patch)\([\'"]([^\'"]+)[\'"]', "node")
        ]

        for root, _, files in os.walk(project_path):
            if any(ign in root for ign in [".git", "node_modules", "venv", ".venv", "__pycache__"]):
                continue
            for file in files:
                if file.endswith((".py", ".js", ".ts")):
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, project_path)
                    try:
                        with open(full_p, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read(50000)
                            for pattern, lang in route_patterns:
                                matches = re.findall(pattern, content, re.IGNORECASE)
                                for method, path in matches:
                                    endpoints.append({
                                        "method": method.upper(),
                                        "path": path,
                                        "file": rel_p,
                                        "framework": lang
                                    })
                    except Exception:
                        pass
        return endpoints[:50]

    def inspect_data_models(self, project_path: str) -> dict:
        models = {"schemas": [], "sqlite_dbs": [], "migrations": []}

        for root, _, files in os.walk(project_path):
            if any(ign in root for ign in [".git", "node_modules", "venv", ".venv", "__pycache__"]):
                continue
            for file in files:
                full_p = os.path.join(root, file)
                rel_p = os.path.relpath(full_p, project_path)
                
                if file.endswith((".db", ".sqlite", ".sqlite3")):
                    models["sqlite_dbs"].append(rel_p)
                elif "migration" in rel_p.lower() or file.endswith(".sql"):
                    models["migrations"].append(rel_p)
                elif file.endswith((".py", ".js", ".ts")):
                    try:
                        with open(full_p, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read(25000)
                            class_matches = re.findall(r'class\s+([A-Za-z0-9_]+)\s*\((?:Base|Model|db\.Model|SQLModel)', content)
                            for cm in class_matches:
                                models["schemas"].append({"model": cm, "file": rel_p})
                    except Exception:
                        pass
        return models

    def inspect_docker_environment(self) -> dict:
        info = {"containers": [], "networks": [], "volumes": []}
        try:
            cmd = ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                res = subprocess.run(["sudo", "-n", "docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if line.strip():
                        parts = line.strip().split("\t")
                        if len(parts) >= 4:
                            info["containers"].append({
                                "id": parts[0],
                                "name": parts[1],
                                "image": parts[2],
                                "status": parts[3],
                                "ports": parts[4] if len(parts) > 4 else ""
                            })
        except Exception:
            pass
        return info

    def inspect_cloudflare_topology(self) -> dict:
        topology = {"tunnels": [], "routes": []}
        cf_dir = "/etc/cloudflared"
        if os.path.exists(cf_dir):
            for file in os.listdir(cf_dir):
                if file.endswith((".yml", ".yaml")):
                    cfg_path = os.path.join(cf_dir, file)
                    try:
                        with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                            tunnel_match = re.search(r'tunnel:\s*([a-zA-Z0-9\-]+)', text)
                            tid = tunnel_match.group(1) if tunnel_match else "unknown"
                            ing_matches = re.findall(r'hostname:\s*([^\s]+)\s+service:\s*([^\s]+)', text)
                            topology["tunnels"].append({
                                "config_file": file,
                                "tunnel_id": tid,
                                "routes": [{"hostname": h, "service": s} for h, s in ing_matches]
                            })
                    except Exception:
                        pass
        return topology

    def learn_project(self, target: dict) -> dict:
        name = target["name"]
        path = target["path"]
        ptype = target.get("type", "general")

        if not os.path.exists(path):
            return {"status": "skipped", "reason": f"Path {path} does not exist"}

        print(f"[ProjectLearner] Learning from: {name} ({path})...")

        # 1. Dependency and Framework Learning
        deps = self.inspect_dependencies(path)
        dep_summary = f"Detected {len(deps['python'])} Python packages, {len(deps['node'])} Node modules."
        self.save_knowledge(name, path, "dependencies", dep_summary, deps)

        # 2. API Endpoints Learning
        endpoints = self.extract_api_endpoints(path)
        api_summary = f"Mapped {len(endpoints)} active API routes."
        self.save_knowledge(name, path, "api_routes", api_summary, {"count": len(endpoints), "routes": endpoints})

        # 3. Data Models and Storage
        data_info = self.inspect_data_models(path)
        model_summary = f"Found {len(data_info['schemas'])} data models, {len(data_info['sqlite_dbs'])} SQLite stores, {len(data_info['migrations'])} migrations."
        self.save_knowledge(name, path, "data_models", model_summary, data_info)

        # 4. Architecture Profile
        has_docker = os.path.exists(os.path.join(path, "Dockerfile"))
        has_compose = os.path.exists(os.path.join(path, "docker-compose.yml"))
        has_git = os.path.exists(os.path.join(path, ".git"))
        arch_profile = {
            "type": ptype,
            "has_docker": has_docker,
            "has_compose": has_compose,
            "has_git": has_git,
            "languages": [k for k, v in deps.items() if v]
        }
        arch_summary = f"Architecture: {ptype.upper()} | Docker: {has_docker} | Compose: {has_compose}"
        self.save_knowledge(name, path, "architecture", arch_summary, arch_profile)

        return {
            "project": name,
            "path": path,
            "dependencies": deps,
            "routes_count": len(endpoints),
            "schemas_count": len(data_info["schemas"])
        }

    def learn_all(self) -> dict:
        results = []
        for target in self.DEFAULT_TARGETS:
            res = self.learn_project(target)
            results.append(res)

        # System Infrastructure
        docker_info = self.inspect_docker_environment()
        self.save_knowledge("Server Infrastructure", "/var/run/docker.sock", "docker_topology",
                            f"{len(docker_info['containers'])} active Docker containers monitored.", docker_info)

        cf_info = self.inspect_cloudflare_topology()
        self.save_knowledge("Cloudflare Ingress", "/etc/cloudflared", "ingress_topology",
                            f"{len(cf_info['tunnels'])} active tunnels registered.", cf_info)

        log_event("LEARNING_COMPLETE", f"Ingested knowledge across {len(results)} server projects and infrastructure.")
        return {"projects": results, "docker": docker_info, "cloudflare": cf_info}

    def get_all_knowledge(self) -> list:
        cur = self.conn.execute("SELECT id, project_name, project_path, category, summary, details_json, updated_at FROM server_knowledge ORDER BY project_name, category")
        rows = cur.fetchall()
        knowledge = []
        for r in rows:
            try:
                details = json.loads(r["details_json"])
            except Exception:
                details = {}
            knowledge.append({
                "id": r["id"],
                "project_name": r["project_name"],
                "project_path": r["project_path"],
                "category": r["category"],
                "summary": r["summary"],
                "details": details,
                "updated_at": r["updated_at"]
            })
        return knowledge

    def query_project_knowledge(self, query_text: str) -> str:
        """
        Retrieves context for LLM thinking and planning.
        """
        knowledge = self.get_all_knowledge()
        relevant = []
        query_lower = query_text.lower()
        for k in knowledge:
            if k["project_name"].lower() in query_lower or any(word in query_lower for word in k["project_name"].lower().split()):
                relevant.append(f"[{k['project_name']} - {k['category'].upper()}]: {k['summary']}")
        
        if not relevant:
            # Provide general server landscape summary
            projects = list({k["project_name"] for k in knowledge})
            return f"Known server projects: {', '.join(projects)}"

        return "\n".join(relevant[:10])

def main():
    learner = ProjectLearner()
    print("=== Running Autonomous Server Project Ingestion & Learning ===")
    results = learner.learn_all()
    print(f"Ingested {len(results['projects'])} projects.")
    for p in results["projects"]:
        if "project" in p:
            print(f"  ✓ {p['project']}: {p['routes_count']} routes, {p['schemas_count']} models")
    print(f"  ✓ Cloudflare Tunnels: {len(results['cloudflare']['tunnels'])}")
    print(f"  ✓ Docker Containers: {len(results['docker']['containers'])}")

if __name__ == "__main__":
    main()
