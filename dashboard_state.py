import io
import json
import os
import sys
import tempfile
import threading
from datetime import datetime


class DashboardLogStream(io.TextIOBase):
    def __init__(self, stream, dashboard_state):
        self._stream = stream
        self._state = dashboard_state

    def write(self, message):
        if message and message.strip():
            self._state._append_log_line(message.strip(), source=self._state.stream_name)
            self._state.add_log(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "pair": "System",
                    "contract_size": "",
                    "trade_type": "Console",
                    "result": "INFO",
                    "reason": message.strip(),
                }
            )
        return self._stream.write(message)

    def flush(self):
        if hasattr(self._stream, "flush"):
            self._stream.flush()

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()


class DashboardState:
    def __init__(self, filepath="dashboard.json"):
        self.filepath = filepath
        self.lock = threading.Lock()
        self.data = {
            "metrics": {
                "account_size": 0.0,
                "daily_dd": 0.0,
                "max_idea_risk": 0.0,
            },
            "risk": {
                "open_risk": 0.0,
                "realized_loss_30m": 0.0,
                "total_risk": 0.0,
            },
            "timer": {"active": False, "message": ""},
            "logs": [],
            "positions": [],
            "deals": [],
            "manual_risk": {"status": "idle", "message": "", "sl_points": 0.0},
            "calculator": {"result": 0.0, "x": 0.0, "numerator": 150.0, "denominator": 0.33},
        }
        self.log_dir = os.path.join(os.path.dirname(self.filepath) or ".", "logs")
        self.combined_log_path = os.path.join(self.log_dir, "all_logs.txt")
        self.stream_name = "dashboard"
        self._log_stream_installed = False
        os.makedirs(self.log_dir, exist_ok=True)
        self._save()

    def update(self, key, value):
        with self.lock:
            if key in self.data and isinstance(self.data[key], dict) and isinstance(value, dict):
                self.data[key].update(value)
            else:
                self.data[key] = value
            self._save()

    def add_log(self, log_entry):
        with self.lock:
            self.data["logs"].insert(0, log_entry)
            self.data["logs"] = self.data["logs"][:50]
            self._append_log_line(json.dumps(log_entry), source="dashboard")
            self._save()

    def install_log_stream(self, log_path=None, stream_name="dashboard"):
        if self._log_stream_installed:
            return
        self._log_stream_installed = True
        self.stream_name = stream_name
        self.log_file_path = log_path or self.combined_log_path
        os.makedirs(self.log_dir, exist_ok=True)
        sys.stdout = DashboardLogStream(sys.stdout, self)
        sys.stderr = DashboardLogStream(sys.stderr, self)

    def read_log_tail(self, log_path, max_lines=250):
        if not log_path or not os.path.exists(log_path):
            return ""
        try:
            with open(log_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return ""
        return "".join(lines[-max_lines:])

    def _append_log_line(self, message, source=None):
        if not message:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_name = source or self.stream_name
        for line in str(message).splitlines():
            if not line.strip():
                continue
            entry = f"[{timestamp}] [{source_name}] {line.strip()}\n"
            with open(self.combined_log_path, "a", encoding="utf-8") as handle:
                handle.write(entry)
            if getattr(self, "log_file_path", None) and self.log_file_path != self.combined_log_path:
                with open(self.log_file_path, "a", encoding="utf-8") as handle:
                    handle.write(entry)

    def _save(self):
        try:
            directory = os.path.dirname(self.filepath) or "."
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", dir=directory, delete=False) as handle:
                json.dump(self.data, handle)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = handle.name
            os.replace(temp_path, self.filepath)
        except Exception as exc:
            print(f"[DashboardState] Error saving state: {exc}")