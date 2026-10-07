"""
core/app_runner.py
------------------------------------------------------------------------------
YAKSHA AI v2.0 — Generated-app runner (backs the dashboard's Playground)

Runs a generated `app.py` as a separate local process so the dashboard can
offer one-click Start / Stop and an embedded live preview.

Design choices:
    - The app is loaded as a MODULE (not run as __main__) by a tiny launcher,
      and `<flask_app_var>.run(...)` is called by the launcher instead. That
      lets the runner pick a FREE port and bind to 127.0.0.1, rather than
      trusting the port/host hard-coded into LLM-generated code (which binds
      0.0.0.0 — i.e. exposes the app to the whole network — and often clashes
      with a port already in use).
    - stdout/stderr go to a log file next to the app, so import errors and
      tracebacks can be shown in the UI instead of vanishing.
    - Non-blocking: start() returns immediately; state() reports
      starting -> running by probing the port, or crashed if the process died.

SECURITY: this EXECUTES LLM-generated code on the local machine, with this
user's permissions. The dashboard shows a warning before the first start, and
QA's dangerous-call scan surfaces suspicious constructs, but nothing here is a
sandbox. Review generated code you don't trust.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HOST = "127.0.0.1"

_LAUNCHER = """
import importlib.util, sys
path, var, host, port = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
spec = importlib.util.spec_from_file_location("yaksha_generated_app", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
getattr(module, var).run(host=host, port=port, debug=False, use_reloader=False)
"""


@dataclass
class AppState:
    status: str                      # "stopped" | "starting" | "running" | "crashed"
    run_id: Optional[str] = None
    port: Optional[int] = None
    url: Optional[str] = None
    returncode: Optional[int] = None
    age_seconds: float = 0.0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _port_open(port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=timeout):
            return True
    except OSError:
        return False


class GeneratedAppRunner:
    """Manages at most ONE running generated app at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._log_handle = None
        self._log_path: Optional[Path] = None
        self._port: Optional[int] = None
        self._run_id: Optional[str] = None
        self._started = 0.0
        atexit.register(self.stop)  # never leave an orphaned server behind

    # -- lifecycle -------------------------------------------------------------

    def start(self, run_id: str, app_path: Path | str, flask_var: str = "app") -> AppState:
        app_path = Path(app_path).resolve()
        if not app_path.exists():
            raise FileNotFoundError(f"Generated app not found: {app_path}")

        self.stop()  # one app at a time
        with self._lock:
            port = _free_port()
            self._log_path = app_path.parent / "server.log"
            self._log_handle = open(self._log_path, "wb")
            self._log_handle.write(
                f"# {time.strftime('%Y-%m-%d %H:%M:%S')} starting {app_path.name} on {HOST}:{port}\n".encode()
            )
            self._log_handle.flush()

            kwargs: dict = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True

            self._proc = subprocess.Popen(
                [sys.executable, "-c", _LAUNCHER, str(app_path), flask_var, HOST, str(port)],
                cwd=str(app_path.parent),
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                **kwargs,
            )
            self._port, self._run_id, self._started = port, run_id, time.monotonic()
        return self.state()

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
            handle, self._log_handle = self._log_handle, None
            self._port = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if handle is not None:
            handle.close()

    # -- inspection ------------------------------------------------------------

    def state(self) -> AppState:
        with self._lock:
            proc, port, run_id, started = self._proc, self._port, self._run_id, self._started
        if proc is None:
            return AppState("stopped")
        age = time.monotonic() - started
        rc = proc.poll()
        if rc is not None:
            return AppState("crashed" if rc != 0 else "stopped", run_id, port, None, rc, age)
        url = f"http://{HOST}:{port}"
        return AppState("running" if _port_open(port) else "starting", run_id, port, url, None, age)

    def log_tail(self, lines: int = 40) -> str:
        path = self._log_path
        if path is None or not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])

    def probe(self, path: str = "/", timeout: float = 3.0) -> tuple[Optional[int], float, Optional[str]]:
        """Smoke test: GET the running app. Returns (http_status, latency_ms, error)."""
        st = self.state()
        if st.status != "running" or not st.url:
            return None, 0.0, "app is not running"
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(st.url + path, timeout=timeout) as resp:
                return resp.status, round((time.monotonic() - t0) * 1000, 1), None
        except urllib.error.HTTPError as exc:  # server answered, with an error status
            return exc.code, round((time.monotonic() - t0) * 1000, 1), None
        except Exception as exc:  # noqa: BLE001
            return None, round((time.monotonic() - t0) * 1000, 1), str(exc)