import json
import time
from core.database import (
    complete_task, fail_task, record_task_run, log_event
)
from core.llm_router import LLMRouter
from tools.code_engine import CodeEngine
from tools.db_manager import DatabaseManager
from tools.security_auditor import SecurityAuditor
from tools.system_scaler import SystemScaler
from tools.project_learner import ProjectLearner
from core.model_self_improvement import ModelSelfImprovementEngine

class AgentBrain:
    def __init__(self):
        self.router = LLMRouter()
        self.code_engine = CodeEngine()
        self.db_manager = DatabaseManager()
        self.auditor = SecurityAuditor(llm_router=self.router)
        self.scaler = SystemScaler()
        self.learner = ProjectLearner()
        self.self_improver = ModelSelfImprovementEngine(llm_router=self.router)

    def process_task(self, task):
        task_id = task["id"]
        title = task["title"]
        task_type = task["type"]
        prompt = task["prompt"]
        context = task.get("context") or ""

        log_event("TASK_START", f"Starting task #{task_id}: {title} [{task_type}]")

        # 1. Scaling & resource check before launching heavy models
        tier, recommended_model = self.scaler.recommend_model_tier()
        if tier == "low":
            self.scaler.unload_idle_models()

        # 2. Knowledge-Augmented Thinking
        learned_ctx = self.learner.query_project_knowledge(f"{title} {prompt} {context}")
        augmented_context = f"{context}\n\n[Learned Server Knowledge]:\n{learned_ctx}" if learned_ctx else context

        # Thinking phase with DeepSeek reasoning
        thought_data = self.router.think_and_plan(
            task_description=f"Task: {title}\nInstructions: {prompt}",
            context=augmented_context
        )
        thought_process = thought_data["thought"]
        plan = thought_data["plan"]
        model_used = thought_data["model"]
        duration_ms = thought_data["duration_ms"]

        # 3. Execution phase based on task type
        execution_result = ""
        exit_code = 0
        error_msg = None

        try:
            if task_type in ("learn", "learn_server", "knowledge"):
                res = self.learner.learn_all()
                execution_result = (
                    f"Server Knowledge Learning Cycle Completed:\n"
                    f"- Ingested {len(res['projects'])} projects\n"
                    f"- Monitored {len(res['docker']['containers'])} Docker containers\n"
                    f"- Verified {len(res['cloudflare']['tunnels'])} Cloudflare ingress tunnels"
                )

            elif task_type == "self_improve":
                # Execute full self-improvement cycle on local models
                target_model = context.strip() if context else None
                cycle_res = self.self_improver.run_self_improvement_cycle(model_name=target_model)
                execution_result = (
                    f"Model Self-Improvement Cycle Completed for {cycle_res['model']}:\n"
                    f"- Baseline Pass Rate: {cycle_res['before_score']}%\n"
                    f"- Post-Improvement Pass Rate: {cycle_res['after_score']}%\n"
                    f"- Net Accuracy Gain: +{cycle_res['gain']}%\n"
                    f"- Optimizations Applied:\n" + "\n".join(f"  • {f}" for f in cycle_res['fixes_applied'])
                )

            elif task_type == "benchmark":
                target_model = context.strip() if context else None
                bench_res = self.self_improver.run_benchmark(model_name=target_model)
                execution_result = (
                    f"Benchmark Results for {bench_res['model']}:\n"
                    f"- Passed: {bench_res['passed']}/{bench_res['total']} tests ({bench_res['pass_rate']}%)\n"
                    f"- Duration: {bench_res['duration_ms']}ms\n"
                    f"- Details:\n" + "\n".join(f"  [{r['category']}] {r['title']}: {'PASSED' if r['passed'] else 'FAILED'}" for r in bench_res['results'])
                )

            elif task_type == "security_audit":
                target_path = context.strip() if context and context.startswith("/") else "/var/www/signlanguage"
                findings = self.auditor.scan_project(title, target_path)
                execution_result = (
                    f"Security Audit for {target_path} completed.\n"
                    f"Discovered {len(findings)} potential security findings.\n"
                    f"Details recorded in vulnerabilities database."
                )

            elif task_type == "code":
                code_res = self.router.generate_code(instruction=prompt, current_code=augmented_context)
                generated_code = code_res["code"]
                execution_result = f"Code generated using {code_res['model']}:\n\n{generated_code}"

            elif task_type == "database":
                if "CREATE" in prompt.upper() and ".db" in context:
                    ok, msg = self.db_manager.create_database(context, initial_schema_sql=prompt)
                    execution_result = msg
                    if not ok:
                        exit_code = 1
                        error_msg = msg
                else:
                    execution_result = f"Database analysis plan:\n{plan}"

            elif task_type == "scale":
                metrics = self.scaler.collect_metrics()
                execution_result = f"System scaling report:\n{json.dumps(metrics, indent=2)}"

            else:
                execution_result = f"Agent plan and resolution:\n{plan}"

        except Exception as e:
            exit_code = 1
            error_msg = str(e)
            execution_result = f"Execution failed: {error_msg}"

        # 4. Self-healing / Reflection if failed
        if exit_code != 0 and task.get("retry_count", 0) < task.get("max_retries", 3):
            reflection = self.router.think_and_plan(
                task_description=f"Analyze why this task failed and suggest remediation:\n{error_msg}",
                context=f"Original Prompt: {prompt}\nExecution Output: {execution_result}"
            )
            thought_process += f"\n\n[Self-Healing Reflection]: {reflection['thought']}"
            fail_task(task_id, error=error_msg, retry=True)
            log_event("TASK_RETRY", f"Task #{task_id} failed, scheduled for retry with reflection.")
        else:
            if exit_code == 0:
                complete_task(task_id, result=execution_result)
                log_event("TASK_SUCCESS", f"Task #{task_id} completed successfully.")
            else:
                fail_task(task_id, error=error_msg, retry=False)
                log_event("TASK_FAILED", f"Task #{task_id} permanently failed.")

        # 5. Record run history
        record_task_run(
            task_id=task_id,
            model_used=model_used,
            thought_process=thought_process,
            output=execution_result,
            exit_code=exit_code,
            duration_ms=duration_ms
        )
