import json
import threading
import os

class DashboardState:
    def __init__(self, filepath="dashboard.json"):
        self.filepath = filepath
        self.lock = threading.Lock()
        self.data = {
            "metrics": {
                "account_size": 0.0,
                "daily_dd": 0.0,
                "max_idea_risk": 0.0
            },
            "risk": {
                "open_risk": 0.0,
                "realized_loss_30m": 0.0,
                "total_risk": 0.0
            },
            "timer": {
                "active": False,
                "message": ""
            },
            "logs": [],
            "positions": [],
            "deals": []
        }
        self._save()

    def update(self, key, value):
        with self.lock:
            if isinstance(self.data[key], dict) and isinstance(value, dict):
                self.data[key].update(value)
            else:
                self.data[key] = value
            self._save()

    def add_log(self, log_entry):
        with self.lock:
            self.data["logs"].insert(0, log_entry)
            self.data["logs"] = self.data["logs"][:50]  # Keep last 50 logs to prevent bloat
            self._save()

    def _save(self):
        # Write to a temp file and rename to avoid the Flask app reading a half-written file
        temp_path = self.filepath + ".tmp"
        try:
            with open(temp_path, 'w') as f:
                json.dump(self.data, f)
            os.replace(temp_path, self.filepath)
        except Exception as e:
            print(f"[DashboardState] Error saving state: {e}")