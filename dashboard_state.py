import io
import json
import os
import sys
import threading
from datetime import datetime


class DashboardLogStream(io.TextIOBase):
    def __init__(self, stream, dashboard_state):
        self._stream = stream
        self._state = dashboard_state

    def write(self, message):
        if message and message.strip():
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
        self._log_stream_installed = False
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
            self._save()

    def install_log_stream(self):
        if self._log_stream_installed:
            return
        self._log_stream_installed = True
        sys.stdout = DashboardLogStream(sys.stdout, self)
        sys.stderr = DashboardLogStream(sys.stderr, self)

    def _save(self):
        try:
            with open(self.filepath, "w") as handle:
                json.dump(self.data, handle)
        except Exception as exc:
            print(f"[DashboardState] Error saving state: {exc}")