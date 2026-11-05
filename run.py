"""Start the FastAPI backend and Next.js frontend together."""
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from src.config import Settings

ROOT = Path(__file__).resolve().parent
settings = Settings(_env_file=ROOT / ".env")
PYTHON_CMD = [sys.executable]
for environment in (".venv", "venv"):
    candidate = ROOT / environment / "Scripts" / "python.exe"
    if candidate.exists():
        PYTHON_CMD = [str(candidate)]
        break

npm = shutil.which("npm")
if not npm:
    raise RuntimeError("Node.js and npm are required to run the Next.js frontend.")

print("Starting ShopAssist AI...\n")

api = subprocess.Popen(
    PYTHON_CMD + [
        "-m", "uvicorn", "src.main:app", "--host", settings.api_host,
        "--port", str(settings.api_port),
    ],
    cwd=str(ROOT),
)
print(f"   FastAPI      http://localhost:{settings.api_port}  (PID {api.pid})")

if os.name == "nt":
    frontend_command = f'"{npm}" run dev -- --hostname 127.0.0.1'
    frontend_env = os.environ.copy()
    frontend_env.setdefault(
        "SHOPASSIST_API_URL",
        f"http://127.0.0.1:{settings.api_port}/api/v1",
    )
    frontend = subprocess.Popen(
        frontend_command, cwd=str(ROOT), shell=True, env=frontend_env
    )
else:
    frontend = subprocess.Popen(
        [npm, "run", "dev", "--", "--hostname", "127.0.0.1"],
        cwd=str(ROOT),
    )
print(f"   Next.js      http://localhost:3000  (PID {frontend.pid})")

time.sleep(3)
webbrowser.open("http://localhost:3000")

print("\nBoth servers are running. Press Ctrl+C to stop.\n")

try:
    while api.poll() is None and frontend.poll() is None:
        time.sleep(0.5)
    if api.poll() is not None:
        raise RuntimeError(f"FastAPI stopped with exit code {api.returncode}.")
    raise RuntimeError(f"Next.js stopped with exit code {frontend.returncode}.")
except KeyboardInterrupt:
    print("\nShutting down...")
finally:
    for process in (frontend, api):
        if process.poll() is None:
            process.terminate()
    for process in (frontend, api):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    if api.returncode not in (0, None):
        sys.exit(api.returncode)
