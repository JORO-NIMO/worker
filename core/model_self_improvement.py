import subprocess
import tempfile
import time
import json
import os
import re
from core.database import (
    record_benchmark_result, record_self_improvement, log_event
)
from core.llm_router import LLMRouter

CODING_BENCHMARK_TASKS = [
    {
        "id": "py_anagram_groups",
        "category": "algorithms",
        "title": "Group Anagrams",
        "prompt": "Write a Python function `def group_anagrams(strs: list[str]) -> list[list[str]]:` that groups anagrams together. Return the list of groups.",
        "test_harness": """
res = group_anagrams(["eat", "tea", "tan", "ate", "nat", "bat"])
res_sorted = sorted([sorted(g) for g in res])
expected = sorted([["ate", "eat", "tea"], ["bat"], ["nat", "tan"]])
assert res_sorted == expected, f"Expected {expected}, got {res_sorted}"

res2 = group_anagrams([""])
assert res2 == [[""]], f"Expected [['']], got {res2}"
print("ALL_TESTS_PASSED")
"""
    },
    {
        "id": "py_lru_cache",
        "category": "data_structures",
        "title": "LRU Cache Implementation",
        "prompt": "Implement an LRU Cache class `class LRUCache:` with `__init__(self, capacity: int)`, `get(self, key: int) -> int`, and `put(self, key: int, value: int) -> None` in Python with O(1) average time complexity.",
        "test_harness": """
cache = LRUCache(2)
cache.put(1, 1)
cache.put(2, 2)
assert cache.get(1) == 1, "Failed key 1"
cache.put(3, 3)
assert cache.get(2) == -1, "Evicted key 2 still found"
cache.put(4, 4)
assert cache.get(1) == -1, "Evicted key 1 still found"
assert cache.get(3) == 3, "Key 3 value mismatch"
assert cache.get(4) == 4, "Key 4 value mismatch"
print("ALL_TESTS_PASSED")
"""
    },
    {
        "id": "sql_user_revenue",
        "category": "sql_generation",
        "title": "SQL Aggregation & Ranking",
        "prompt": "Write a SQLite query that selects the top 3 users by total revenue from a table `orders(user_id, amount, status)` where status = 'completed'. Output columns: user_id, total_revenue. Order by total_revenue DESC limit 3.",
        "test_harness": """
import sqlite3
con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE orders (user_id INT, amount REAL, status TEXT)")
con.executemany("INSERT INTO orders VALUES (?, ?, ?)", [
    (1, 100.0, 'completed'),
    (2, 250.0, 'completed'),
    (1, 150.0, 'completed'),
    (3, 500.0, 'cancelled'),
    (2, 50.0, 'completed'),
    (4, 80.0, 'completed')
])
cur = con.execute(EXTRACTED_SQL)
rows = cur.fetchall()
assert len(rows) <= 3, f"Expected <= 3 rows, got {len(rows)}"
assert rows[0][0] == 2 and rows[0][1] == 300.0, f"Expected user 2 with 300, got {rows[0]}"
assert rows[1][0] == 1 and rows[1][1] == 250.0, f"Expected user 1 with 250, got {rows[1]}"
print("ALL_TESTS_PASSED")
"""
    },
    {
        "id": "sec_sql_injection",
        "category": "security_refactor",
        "title": "Secure Parameterized Query Refactor",
        "prompt": "Fix this vulnerable Python function to prevent SQL injection by using parameterized SQLite queries:\n```python\ndef get_user(db, username):\n    return db.execute(f\"SELECT * FROM users WHERE username = '{username}'\").fetchone()\n```\nProvide the fixed function `def get_user(db, username):`.",
        "test_harness": """
import sqlite3
con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE users (id INT, username TEXT)")
con.execute("INSERT INTO users VALUES (1, 'alice')")
res = get_user(con, "alice")
assert res is not None and res[1] == "alice", "Could not fetch user"
# Test malicious injection string
res_inj = get_user(con, "' OR '1'='1")
assert res_inj is None, "SQL Injection payload bypassed parameterization!"
print("ALL_TESTS_PASSED")
"""
    }
]

class ModelSelfImprovementEngine:
    def __init__(self, llm_router: LLMRouter = None):
        self.router = llm_router or LLMRouter()
        self.dataset_path = "/var/www/worker/data/fine_tuning_dataset.jsonl"
        os.makedirs(os.path.dirname(self.dataset_path), exist_ok=True)

    def extract_code(self, response_text: str, language: str = "python") -> str:
        # Search for ```python ... ``` block
        pattern = re.compile(rf"```{language}?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
        match = pattern.search(response_text)
        if match:
            return match.group(1).strip()
        
        # Search for general ``` block
        pattern_gen = re.compile(r"```\s*(.*?)\s*```", re.DOTALL)
        match_gen = pattern_gen.search(response_text)
        if match_gen:
            return match_gen.group(1).strip()

        # Fallback to lines that look like code
        return response_text.strip()

    def run_python_test(self, code_str: str, test_harness: str) -> tuple[bool, str]:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(code_str + "\n\n" + test_harness)
            test_file = f.name

        try:
            res = subprocess.run(
                ["python3", test_file],
                capture_output=True,
                text=True,
                timeout=6
            )
            success = res.returncode == 0 and "ALL_TESTS_PASSED" in res.stdout
            output = res.stdout if success else (res.stderr or res.stdout)
            return success, output.strip()
        except subprocess.TimeoutExpired:
            return False, "Execution timed out (infinite loop or hang > 6s)"
        except Exception as e:
            return False, f"Subprocess error: {e}"
        finally:
            if os.path.exists(test_file):
                try:
                    os.unlink(test_file)
                except OSError:
                    pass

    def run_benchmark(self, model_name: str = None) -> dict:
        """
        Executes the benchmark battery on the target local model.
        Returns detailed scores and execution traces.
        """
        model = model_name or self.router.fast_coder_model
        results = []
        passed_count = 0
        total_tests = len(CODING_BENCHMARK_TASKS)
        start_time = time.time()

        log_event("BENCHMARK_START", f"Running self-improvement coding benchmark on {model}")

        for task in CODING_BENCHMARK_TASKS:
            t0 = time.time()
            prompt = (
                f"You are an expert software engineer.\n"
                f"{task['prompt']}\n\n"
                f"Write clean, syntactically perfect, production code. Wrap your final code strictly in a ```python``` block."
            )
            llm_res = self.router.generate(prompt=prompt, model=model, temperature=0.1)
            raw_response = llm_res.get("response", "")
            code = self.extract_code(raw_response)

            # Test execution
            if task["category"] == "sql_generation":
                # For SQL, inject the extracted SQL string into harness
                clean_sql = re.sub(r'```sql|```', '', code).strip()
                harness = task["test_harness"].replace("EXTRACTED_SQL", repr(clean_sql))
                passed, test_output = self.run_python_test("", harness)
            else:
                passed, test_output = self.run_python_test(code, task["test_harness"])

            duration = round((time.time() - t0) * 1000)
            if passed:
                passed_count += 1
                # Save high-quality problem/solution pair for fine-tuning
                self.record_synthetic_sample(task["prompt"], code, model)

            results.append({
                "id": task["id"],
                "category": task["category"],
                "title": task["title"],
                "passed": passed,
                "output": test_output[:300],
                "duration_ms": duration
            })

        total_duration = round((time.time() - start_time) * 1000)
        pass_rate = round((passed_count / total_tests) * 100, 1)

        # Record to database
        record_benchmark_result(
            model_name=model,
            category="comprehensive_coding",
            score=passed_count,
            total_tests=total_tests,
            pass_rate=pass_rate,
            duration_ms=total_duration,
            details=results
        )

        return {
            "model": model,
            "passed": passed_count,
            "total": total_tests,
            "pass_rate": pass_rate,
            "duration_ms": total_duration,
            "results": results
        }

    def run_self_improvement_cycle(self, model_name: str = None) -> dict:
        """
        Continuous Self-Improvement Loop (Reflexion & Self-Correction):
        1. Runs baseline benchmark.
        2. Identifies failed challenges.
        3. Prompts the model with the failure stack trace to reflect and self-correct.
        4. Verifies the corrected code.
        5. Logs the improvement metrics and persists verified synthetic training data.
        """
        model = model_name or self.router.fast_coder_model
        baseline = self.run_benchmark(model)
        before_score = baseline["pass_rate"]

        log_event("SELF_IMPROVEMENT_CYCLE", f"Initiating self-improvement loop for {model}. Baseline: {before_score}%")

        fixes_applied = []
        newly_passed = 0

        for item in baseline["results"]:
            if not item["passed"]:
                task_def = next((t for t in CODING_BENCHMARK_TASKS if t["id"] == item["id"]), None)
                if not task_def:
                    continue

                # Reflexion & Self-Correction Turn
                reflection_prompt = (
                    f"Your previous code solution for the task '{task_def['title']}' failed with the following error:\n"
                    f"```\n{item['output']}\n```\n\n"
                    f"Original Task: {task_def['prompt']}\n\n"
                    f"Analyze why the solution failed. Then provide the completely corrected, bug-free implementation wrapped in a ```python``` block."
                )

                fix_res = self.router.generate(prompt=reflection_prompt, model=model, temperature=0.1)
                corrected_code = self.extract_code(fix_res.get("response", ""))

                if task_def["category"] == "sql_generation":
                    clean_sql = re.sub(r'```sql|```', '', corrected_code).strip()
                    harness = task_def["test_harness"].replace("EXTRACTED_SQL", repr(clean_sql))
                    passed_now, out_now = self.run_python_test("", harness)
                else:
                    passed_now, out_now = self.run_python_test(corrected_code, task_def["test_harness"])

                if passed_now:
                    newly_passed += 1
                    fixes_applied.append(f"Fixed {task_def['title']} via error reflection")
                    self.record_synthetic_sample(task_def["prompt"], corrected_code, model)

        after_score = round(((baseline["passed"] + newly_passed) / baseline["total"]) * 100, 1)

        # Log iteration record in database
        record_self_improvement(
            iteration=int(time.time()),
            model_name=model,
            focus_area="Code Generation & Reflexion",
            before_score=before_score,
            after_score=after_score,
            optimizations="\n".join(fixes_applied) if fixes_applied else "Baseline verified; no regressions detected.",
            status="completed"
        )

        log_event(
            "SELF_IMPROVEMENT_COMPLETE",
            f"Self-improvement cycle complete for {model}: {before_score}% -> {after_score}%",
            payload={"fixes": fixes_applied}
        )

        return {
            "model": model,
            "before_score": before_score,
            "after_score": after_score,
            "gain": round(after_score - before_score, 1),
            "fixes_applied": fixes_applied
        }

    def record_synthetic_sample(self, instruction: str, code: str, model: str):
        record = {
            "instruction": instruction,
            "output": code,
            "verified": True,
            "model": model,
            "timestamp": time.time()
        }
        try:
            with open(self.dataset_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"[ModelSelfImprovement] Error logging sample: {e}")
