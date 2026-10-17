import os
import py_compile
import subprocess
import shutil

class CodeEngine:
    def __init__(self, allowed_roots=None):
        self.allowed_roots = allowed_roots or ["/var/www", "/home/ishabarundo"]

    def _is_path_allowed(self, target_path):
        real_path = os.path.realpath(target_path)
        for root in self.allowed_roots:
            if real_path.startswith(os.path.realpath(root)):
                return True
        return False

    def read_file(self, file_path, max_bytes=100000):
        if not self._is_path_allowed(file_path):
            return None, f"Access denied: path {file_path} is outside allowed directories."
        if not os.path.isfile(file_path):
            return None, f"File not found: {file_path}"
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(max_bytes), None
        except Exception as e:
            return None, str(e)

    def write_file(self, file_path, content, create_backup=True):
        if not self._is_path_allowed(file_path):
            return False, f"Access denied: path {file_path} is outside allowed directories."
        try:
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
            if create_backup and os.path.exists(file_path):
                shutil.copy2(file_path, f"{file_path}.bak")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True, None
        except Exception as e:
            return False, str(e)

    def validate_syntax(self, file_path):
        """Validates syntax of Python or JavaScript files before deploying."""
        if not os.path.exists(file_path):
            return False, "File does not exist"
        
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".py":
            try:
                py_compile.compile(file_path, doraise=True)
                return True, "Python syntax valid"
            except py_compile.PyCompileError as e:
                return False, f"Python syntax error: {e}"
        elif ext in [".js", ".mjs"]:
            try:
                res = subprocess.run(["node", "-c", file_path], capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    return True, "Node syntax valid"
                return False, f"Node syntax error: {res.stderr}"
            except Exception as e:
                return False, f"Syntax verification failed: {e}"
        return True, "No syntax checker needed for this file type"

    def list_files(self, directory_path, max_depth=2):
        if not self._is_path_allowed(directory_path):
            return []
        results = []
        base_depth = directory_path.rstrip(os.path.sep).count(os.path.sep)
        for root, dirs, files in os.walk(directory_path):
            cur_depth = root.count(os.path.sep) - base_depth
            if cur_depth > max_depth:
                dirs[:] = []
                continue
            for f in files:
                results.append(os.path.join(root, f))
        return results
