import os
import shutil
import urllib.request
import json
from core.database import record_metrics, log_event

class SystemScaler:
    def __init__(self, ollama_url="http://127.0.0.1:11434"):
        self.ollama_url = ollama_url

    def collect_metrics(self):
        # 1. CPU load average
        load1, load5, load15 = os.getloadavg()
        cpu_load_str = f"{load1:.2f}, {load5:.2f}, {load15:.2f}"

        # 2. Memory stats from /proc/meminfo
        mem_info = {}
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        mem_info[key] = int(val)
        except Exception:
            pass

        total_ram_mb = mem_info.get("MemTotal", 0) // 1024
        avail_ram_mb = mem_info.get("MemAvailable", mem_info.get("MemFree", 0)) // 1024
        used_ram_mb = max(0, total_ram_mb - avail_ram_mb)

        total_swap_mb = mem_info.get("SwapTotal", 0) // 1024
        free_swap_mb = mem_info.get("SwapFree", 0) // 1024
        used_swap_mb = max(0, total_swap_mb - free_swap_mb)

        # 3. Disk usage
        disk = shutil.disk_usage("/")
        disk_used_percent = round((disk.used / disk.total) * 100, 1)

        # Record to database
        record_metrics(cpu_load_str, used_ram_mb, total_ram_mb, used_swap_mb, disk_used_percent)

        return {
            "cpu_load": cpu_load_str,
            "ram_total_mb": total_ram_mb,
            "ram_used_mb": used_ram_mb,
            "ram_avail_mb": avail_ram_mb,
            "swap_used_mb": used_swap_mb,
            "disk_used_percent": disk_used_percent
        }

    def recommend_model_tier(self):
        """
        Calculates safe model capacity based on real-time available RAM.
        Prevents Linux OOM Killer.
        """
        metrics = self.collect_metrics()
        avail_mb = metrics["ram_avail_mb"]

        if avail_mb >= 2200:
            return "high", "deepseek-r1:7b"
        elif avail_mb >= 1400:
            return "medium", "deepseek-coder:6.7b"
        else:
            return "low", "qwen2.5-coder:1.5b"

    def unload_idle_models(self):
        """
        Instructs Ollama to free VRAM/RAM if memory is constrained.
        """
        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/ps",
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode())
                running_models = data.get("models", [])
                for m in running_models:
                    model_name = m.get("name")
                    if model_name:
                        # Send 0s keepalive to unload
                        unload_req = urllib.request.Request(
                            f"{self.ollama_url}/api/generate",
                            data=json.dumps({"model": model_name, "keep_alive": 0}).encode(),
                            headers={"Content-Type": "application/json"}
                        )
                        urllib.request.urlopen(unload_req, timeout=5)
                        log_event("SCALE_RESOURCE", f"Unloaded idle model {model_name} from memory")
        except Exception as e:
            log_event("SCALE_WARN", f"Failed to check/unload models: {e}")
