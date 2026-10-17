import time
import signal
import sys
import os
import threading
from core.database import (
    init_db, get_next_pending_task, create_task, log_event
)
from core.agent_brain import AgentBrain
from web.dashboard_server import run_server

class WorkerDaemon:
    def __init__(self, poll_interval=10):
        self.poll_interval = poll_interval
        self.running = True
        self.brain = None
        self.last_auto_maintenance = 0
        self.auto_maintenance_interval = 1800 # Every 30 minutes

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        log_event("DAEMON_STOPPING", f"Signal {signum} received, stopping worker daemon...")
        self.running = False

    def start_dashboard(self):
        dashboard_thread = threading.Thread(target=run_server, daemon=True)
        dashboard_thread.start()
        print("[WorkerDaemon] Dashboard server thread initialized on port 8888.")

    def trigger_periodic_maintenance(self):
        """
        Autonomous proactive continuous improvement:
        Ensures the system continuously checks for security issues, scales gracefully,
        and self-improves local models.
        """
        now = time.time()
        if now - self.last_auto_maintenance > self.auto_maintenance_interval:
            self.last_auto_maintenance = now
            log_event("AUTO_CYCLE", "Triggering autonomous maintenance cycle")
            
            # 1. Enqueue proactive security audit
            create_task(
                title="Proactive Security Audit - SignLanguage",
                task_type="security_audit",
                prompt="Perform a static security audit of the signlanguage project to detect secret leaks or insecure patterns.",
                context="/var/www/signlanguage",
                priority=20
            )

            # 2. Enqueue autonomous model self-improvement cycle
            create_task(
                title="Autonomous Model Self-Improvement & Coding Reflexion",
                task_type="self_improve",
                prompt="Run algorithmic and coding benchmark with reflexion loop to identify and resolve model weaknesses.",
                context="qwen2.5-coder:1.5b",
                priority=30
            )

            # 3. Enqueue system scale check
            create_task(
                title="System Resource & Scale Inspection",
                task_type="scale",
                prompt="Evaluate RAM, swap, and CPU load to ensure inference headroom.",
                context="",
                priority=40
            )

    def run(self):
        init_db()
        self.brain = AgentBrain()
        self.start_dashboard()
        log_event("DAEMON_STARTED", "Autonomous worker daemon and dashboard started successfully")
        print("[WorkerDaemon] Started continuous execution loop.")

        while self.running:
            try:
                task = get_next_pending_task()
                if task:
                    print(f"[WorkerDaemon] Processing Task #{task['id']}: {task['title']}")
                    self.brain.process_task(task)
                else:
                    self.trigger_periodic_maintenance()
                    time.sleep(self.poll_interval)
            except Exception as e:
                log_event("DAEMON_ERROR", f"Unhandled error in worker loop: {e}")
                time.sleep(5)

        print("[WorkerDaemon] Worker loop exited cleanly.")

if __name__ == "__main__":
    daemon = WorkerDaemon()
    daemon.run()
