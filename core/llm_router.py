import urllib.request
import urllib.error
import json
import re
import time
import os

CONFIG_PATH = os.environ.get("WORKER_CONFIG_PATH", "/var/www/worker/config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "ollama_url": "http://127.0.0.1:11434",
        "models": {
            "thinker": "deepseek-r1:7b",
            "coder": "deepseek-coder:6.7b",
            "fast_coder": "qwen2.5-coder:1.5b",
            "sentinel": "llama3.2:1b"
        }
    }

class LLMRouter:
    def __init__(self):
        self.config = load_config()
        self.base_url = self.config.get("ollama_url", "http://127.0.0.1:11434")
        self.models = self.config.get("models", {})

    def _query_ollama(self, model, prompt, system_prompt="", stream=False, timeout=180):
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": 0.2,
                "top_p": 0.95
            }
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )

        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                duration_ms = int((time.time() - start_time) * 1000)
                raw_response = result.get("response", "")
                return raw_response, duration_ms, None
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return "", duration_ms, str(e)

    def think_and_plan(self, task_description, context=""):
        """
        Uses deepseek-r1:7b (thinking model) to break down the task,
        generate chain of thought, and propose concrete steps.
        Falls back to qwen2.5-coder:1.5b if memory or timeout occurs.
        """
        primary_model = self.models.get("thinker", "deepseek-r1:7b")
        fallback_model = self.models.get("fast_coder", "qwen2.5-coder:1.5b")

        system_prompt = (
            "You are an advanced autonomous systems engineer and architect. "
            "Think through the user task deeply and logically. Identify safety risks, edge cases, "
            "database schemas, code structure, and concrete steps needed to complete the goal. "
            "Output your reasoning enclosed within <think>...</think>, followed by a structured JSON plan."
        )

        prompt = f"Goal:\n{task_description}\n\nContext:\n{context}\n\nFormulate your internal chain of thought and plan."

        raw, duration, err = self._query_ollama(primary_model, prompt, system_prompt=system_prompt, timeout=120)
        used_model = primary_model

        if err or not raw.strip():
            # Fallback to lighter model to prevent system blockage
            raw, duration, err = self._query_ollama(fallback_model, prompt, system_prompt=system_prompt, timeout=60)
            used_model = fallback_model

        thought = ""
        content = raw
        think_match = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
        if think_match:
            thought = think_match.group(1).strip()
            content = raw.replace(think_match.group(0), "").strip()

        return {
            "model": used_model,
            "thought": thought or "Direct reasoning applied without tags.",
            "plan": content,
            "duration_ms": duration,
            "error": err
        }

    def generate_code(self, instruction, current_code="", language="python"):
        """
        Generates robust code, SQL queries, or fixes using code-specialized models.
        """
        primary_model = self.models.get("coder", "deepseek-coder:6.7b")
        fallback_model = self.models.get("fast_coder", "qwen2.5-coder:1.5b")

        system_prompt = (
            f"You are a principal {language} engineer. Write production-ready, clean, secure, and performant code. "
            "Include proper error handling, docstrings, and boundary condition checks. "
            "Output ONLY the requested code block inside ``` blocks with no redundant preamble."
        )

        prompt = f"Task:\n{instruction}\n\nExisting Code/Context:\n{current_code}\n\nProvide the complete implementation:"

        raw, duration, err = self._query_ollama(primary_model, prompt, system_prompt=system_prompt, timeout=90)
        used_model = primary_model

        if err or not raw.strip():
            raw, duration, err = self._query_ollama(fallback_model, prompt, system_prompt=system_prompt, timeout=60)
            used_model = fallback_model

        # Extract code inside markdown blocks if present
        code_match = re.search(r"```(?:\w+)?\n(.*?)```", raw, re.DOTALL)
        code = code_match.group(1).strip() if code_match else raw.strip()

        return {
            "model": used_model,
            "code": code,
            "duration_ms": duration,
            "error": err
        }

    def fast_audit_check(self, snippet, check_type="security"):
        """
        Fast evaluation using llama3.2:1b for rapid triage.
        """
        model = self.models.get("sentinel", "llama3.2:1b")
        prompt = (
            f"Inspect the following code for {check_type} issues.\n"
            f"Code snippet:\n{snippet}\n\n"
            "Respond in JSON format: {\"safe\": boolean, \"issues\": [string], \"severity\": string}"
        )
        raw, duration, err = self._query_ollama(model, prompt, timeout=30)
        return {
            "model": model,
            "response": raw,
            "duration_ms": duration,
            "error": err
        }
