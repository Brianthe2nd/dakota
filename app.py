import base64
import json
import os
import tempfile
from typing import Optional

from flask import Flask, jsonify, render_template, request

from dashboard_state import DashboardState
from mt5_funcs import calculate_calculator_result, calculate_sl_points_from_price_levels, estimate_sl_points_from_crop
from process_price_crop import extract_highlighted_prices
from prop_enforcer import PropFirmManager

app = Flask(__name__)
STATE_FILE = "dashboard.json"
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
APP_LOG_FILE = os.path.join(LOG_DIR, "app.py.log")
MAIN_LOG_FILE = os.path.join(LOG_DIR, "main.py.log")
COMBINED_LOG_FILE = os.path.join(LOG_DIR, "all_logs.txt")
os.makedirs(LOG_DIR, exist_ok=True)
dashboard_state = DashboardState(filepath=STATE_FILE)
dashboard_state.install_log_stream(log_path=APP_LOG_FILE, stream_name="app.py")


def _load_image_payload(image_data: Optional[str], image_path: Optional[str]) -> Optional[str]:
    if image_data:
        if image_data.startswith("data:"):
            _, encoded = image_data.split(",", 1)
            return encoded
        return image_data
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    return None


def _encode_image_for_response(image_path: Optional[str]) -> Optional[str]:
    if not image_path or not os.path.exists(image_path):
        return None
    with open(image_path, "rb") as handle:
        return f"data:image/png;base64,{base64.b64encode(handle.read()).decode('ascii')}"


def _process_price_crop(image_path: Optional[str], crop: Optional[dict] = None):
    if not image_path or not os.path.exists(image_path):
        return []
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    image = cv2.imread(image_path)
    if image is None:
        return []

    if crop:
        height, width = image.shape[:2]
        x = max(0, int(crop.get("x", 0)))
        y = max(0, int(crop.get("y", 0)))
        crop_width = max(1, int(crop.get("width", 100)))
        crop_height = max(1, int(crop.get("height", 100)))
        if x <= 100 and y <= 100 and crop_width <= 100 and crop_height <= 100:
            x = int(round((x / 100.0) * width))
            y = int(round((y / 100.0) * height))
            crop_width = int(round((crop_width / 100.0) * width))
            crop_height = int(round((crop_height / 100.0) * height))
        x2 = min(width, x + crop_width)
        y2 = min(height, y + crop_height)
        image = image[y:y2, x:x2]

    if image.size == 0:
        return []

    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
        os.close(temp_fd)
        cv2.imwrite(temp_path, image)
        results = extract_highlighted_prices(temp_path)
        return [
            {
                "color": item.get("color"),
                "price_text": item.get("price_text"),
                "price": item.get("price"),
                "bbox": item.get("bbox"),
            }
            for item in results
        ]
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


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
                data = json.load(handle)
            pending = data.get("pending_match_risk") or {}
            image_path = pending.get("image_path")
            if image_path and os.path.exists(image_path):
                data["pending_match_risk"] = {
                    **pending,
                    "image_data": _encode_image_for_response(image_path),
                }
            return jsonify(data)
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


@app.route("/api/logs")
def log_data():
    max_lines = int(request.args.get("max_lines", "250"))
    return jsonify(
        {
            "app": dashboard_state.read_log_tail(APP_LOG_FILE, max_lines=max_lines),
            "main": dashboard_state.read_log_tail(MAIN_LOG_FILE, max_lines=max_lines),
            "combined": dashboard_state.read_log_tail(COMBINED_LOG_FILE, max_lines=max_lines),
        }
    )


@app.route("/api/process-price-crop", methods=["POST"])
def process_price_crop():
    payload = request.get_json(silent=True) or {}
    image_data = payload.get("image")
    image_path = payload.get("image_path")
    crop = payload.get("crop") or {}

    temp_path: Optional[str] = None
    if image_data and image_data.startswith("data:"):
        header, encoded = image_data.split(",", 1)
        image_bytes = base64.b64decode(encoded)
        temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
        os.close(temp_fd)
        with open(temp_path, "wb") as handle:
            handle.write(image_bytes)
    elif image_path and os.path.exists(image_path):
        temp_path = image_path

    rows = _process_price_crop(temp_path, crop) if temp_path else []
    if temp_path and temp_path != image_path and os.path.exists(temp_path):
        os.remove(temp_path)

    return jsonify({"rows": rows})


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

    selected_entry_price = payload.get("selected_entry_price")
    selected_exit_price = payload.get("selected_exit_price")
    if selected_entry_price is not None and selected_exit_price is not None:
        try:
            sl_points = calculate_sl_points_from_price_levels(float(selected_entry_price), float(selected_exit_price))
        except ValueError:
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