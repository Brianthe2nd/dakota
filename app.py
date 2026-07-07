import base64
import json
import os
import tempfile
from typing import Optional

from flask import Flask, jsonify, render_template, request

from dashboard_state import DashboardState
from mt5_funcs import calculate_calculator_result, estimate_sl_points_from_crop
from prop_enforcer import PropFirmManager

app = Flask(__name__)
STATE_FILE = "dashboard.json"
dashboard_state = DashboardState(filepath=STATE_FILE)
dashboard_state.install_log_stream()


def get_prop_manager() -> PropFirmManager:
    if not hasattr(app, "_prop_manager") or app._prop_manager is None:
        app._prop_manager = PropFirmManager(
            daily_drawdown_limit=float(os.getenv("DAILY_DD", "2500.0")),
            dashboard_state=dashboard_state,
            default_sl_points=int(os.getenv("DEFAULT_SL", "150")),
        )
    return app._prop_manager


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as handle:
                return jsonify(json.load(handle))
        except Exception:
            pass
    return jsonify(
        {
            "metrics": {},
            "risk": {},
            "timer": {"active": False},
            "logs": [],
            "positions": [],
            "deals": [],
            "manual_risk": {"status": "idle", "message": "", "sl_points": 0.0},
            "calculator": {"result": 0.0},
        }
    )


@app.route("/api/calculator", methods=["POST"])
def calculator():
    payload = request.get_json(silent=True) or {}
    x_value = float(payload.get("x", 0) or 0)
    numerator = float(payload.get("numerator", 150.0) or 150.0)
    denominator = float(payload.get("denominator", 0.33) or 0.33)

    result = calculate_calculator_result(x_value, numerator=numerator, denominator=denominator)
    dashboard_state.update(
        "calculator",
        {"result": result, "x": x_value, "numerator": numerator, "denominator": denominator},
    )
    dashboard_state.add_log(
        {
            "time": "",
            "pair": "Calculator",
            "contract_size": "",
            "trade_type": "Manual",
            "result": "INFO",
            "reason": f"Calculator: {numerator}/{x_value} * {denominator} = {result}",
        }
    )
    return jsonify({"result": result})


@app.route("/api/match-risk", methods=["POST"])
def match_risk():
    payload = request.get_json(silent=True) or {}
    image_data = payload.get("image")
    crop = payload.get("crop") or {}
    pair = payload.get("pair")
    contract_size = payload.get("contract_size")
    trade_type = payload.get("trade_type", "buy")
    sl_points = payload.get("sl_points")

    temp_path: Optional[str] = None
    if image_data:
        header, encoded = image_data.split(",", 1) if "," in image_data else (None, image_data)
        image_bytes = base64.b64decode(encoded)
        temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
        os.close(temp_fd)
        with open(temp_path, "wb") as handle:
            handle.write(image_bytes)

    estimated_sl_points = estimate_sl_points_from_crop(temp_path, crop) if temp_path else float(sl_points or 150)
    if sl_points is None:
        sl_points = estimated_sl_points

    prop_manager = get_prop_manager()
    result = prop_manager.process_manual_risk_match(
        {
            "pair": pair,
            "contract_size": contract_size,
            "trade_type": trade_type,
            "sl_points": sl_points,
        },
        account_size=None,
        multiplier=float(os.getenv("MULTIPLIER", "1.0")),
        state_path=os.getenv("MT5_STATE_PATH", "mt5_state.json"),
    )

    dashboard_state.update(
        "manual_risk",
        {
            "status": result.get("action", "processed"),
            "message": result.get("reason", "Manual risk match complete"),
            "sl_points": float(sl_points or estimated_sl_points),
        },
    )
    dashboard_state.add_log(
        {
            "time": "",
            "pair": pair or "Manual",
            "contract_size": contract_size,
            "trade_type": trade_type,
            "result": result.get("action", "processed"),
            "reason": result.get("reason", "Manual risk match complete"),
        }
    )

    if temp_path and os.path.exists(temp_path):
        os.remove(temp_path)

    return jsonify({"sl_points": float(sl_points or estimated_sl_points), "result": result})


if __name__ == "__main__":
    app.run(debug=True, port=5000)