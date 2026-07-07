import json
import os
from typing import Dict, Optional

try:
    import MetaTrader5 as mt5  # type: ignore[import]
except ImportError:
    mt5 = None


DEFAULT_SYMBOL_MAP = {
    "nasdaq": "US100",
    "nq": "NAS100",
    "gold": "XAUUSD",
    "xau": "XAUUSD",
}


def _load_state(state_path: str) -> Dict:
    if not os.path.exists(state_path):
        return {}
    try:
        with open(state_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: Dict, state_path: str) -> None:
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _ensure_mt5_initialized() -> None:
    if mt5 is None:
        raise ImportError("MetaTrader5 package is not installed")
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def _get_symbol(pair: str, symbol_map: Optional[Dict[str, str]] = None) -> Optional[str]:
    if symbol_map is None:
        symbol_map = DEFAULT_SYMBOL_MAP
    if not pair:
        return None
    normalized = pair.strip().lower()
    return symbol_map.get(normalized, normalized.upper())


def get_account_size() -> float:
    """Return the live MT5 account balance as the account size for risk calculations."""
    _ensure_mt5_initialized()
    account_info = mt5.account_info()
    if account_info is None:
        raise RuntimeError("MT5 account info is unavailable")

    balance = getattr(account_info, "balance", None)
    if balance is None:
        raise RuntimeError("MT5 account balance is unavailable")
    return float(balance)


def _calculate_target_lots(contract_size: float, pair: str, account_size: float, multiplier: float = 1) -> float:
    """Convert a detected contract size into a lot size target for MT5."""
    max_contract = 15.0 if pair.strip().lower().startswith("n") else 4.0
    "dakota can have upto 3 trades per session and I can not lose more than 1.5% of my acc so I will use a multiplier of 1.5"
    "during the session so I will have to use 0.5 max risk per trade idea, so max_contract = 15.0 for NQ and 4.0 for XAUUSD"
    "if 1 = 150000 then 0.3 = 5000"
    # 150000 = con
    # acc_ba
    dakotas_acc_size = 150000
    contract_size = contract_size * 0.1
    normalized_contract_size = account_size * contract_size / dakotas_acc_size
    scaled = normalized_contract_size * multiplier
    lots = max(0.01, round(scaled, 2))
    print("The desrired lots are ", lots)
    return lots


def calculate_calculator_result(x: float, numerator: float = 150.0, denominator: float = 0.33) -> float:
    if x == 0:
        raise ValueError("x cannot be zero")
    return (float(numerator) / float(x)) * float(denominator)


def estimate_sl_points_from_crop(image_path: Optional[str], crop: Optional[Dict] = None, default_points: float = 150.0) -> float:
    if not image_path or not os.path.exists(image_path):
        return float(default_points)
    try:
        import cv2
    except ImportError:
        return float(default_points)

    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        return float(default_points)

    height, width = image.shape[:2]
    if crop:
        x = max(0, int(crop.get("x", 0)))
        y = max(0, int(crop.get("y", 0)))
        crop_width = max(1, int(crop.get("width", width)))
        crop_height = max(1, int(crop.get("height", height)))
        if x <= 100 and y <= 100 and crop_width <= 100 and crop_height <= 100:
            x = int(round((x / 100.0) * width))
            y = int(round((y / 100.0) * height))
            crop_width = int(round((crop_width / 100.0) * width))
            crop_height = int(round((crop_height / 100.0) * height))
        x2 = min(width, x + crop_width)
        y2 = min(height, y + crop_height)
        cropped = image[y:y2, x:x2]
    else:
        cropped = image

    if cropped.size == 0:
        return float(default_points)

    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = cv2.countNonZero(edges) / float(edges.size)
    base_distance = ((cropped.shape[1] + cropped.shape[0]) / 2.0) * (0.4 + edge_density)
    return round(float(max(default_points * 0.5, min(default_points * 2.0, base_distance / 2.0))), 2)


def _get_mt5_positions(symbol: str):
    _ensure_mt5_initialized()
    positions = mt5.positions_get(symbol=symbol)
    return positions if positions is not None else []


def _symbol_net_volume(symbol: str) -> float:
    positions = _get_mt5_positions(symbol)
    net_volume = 0.0
    for pos in positions:
        if pos.type == mt5.ORDER_TYPE_BUY:
            net_volume += pos.volume
        elif pos.type == mt5.ORDER_TYPE_SELL:
            net_volume -= pos.volume
    return net_volume


def _close_symbol_positions(symbol: str) -> Dict:
    _ensure_mt5_initialized()
    positions = _get_mt5_positions(symbol)
    closed = 0
    for pos in positions:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "position": pos.ticket,
            "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
            "magic": 0,
            "deviation": 10,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
    return {"closed_positions": closed}


def _close_partial_position(symbol: str, volume_to_close: float) -> Dict:
    """Close the oldest open positions first, partially or fully as needed."""
    _ensure_mt5_initialized()

    if volume_to_close <= 0:
        return {"status": "ignored", "reason": "no volume to close"}

    positions = mt5.positions_get(symbol=symbol)
    if positions is None or not positions:
        return {"status": "ignored", "reason": "position not found"}

    ordered_positions = sorted(positions, key=lambda pos: getattr(pos, "time", 0))
    remaining_volume = float(volume_to_close)
    closed_positions = []

    for pos in ordered_positions:
        if remaining_volume <= 0:
            break
        if pos.volume <= 0:
            continue

        volume_now = min(float(pos.volume), remaining_volume)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": round(volume_now, 2),
            "position": pos.ticket,
            "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
            "price": mt5.symbol_info_tick(symbol).ask if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).bid,
            "deviation": 100,
            "magic": 0,
            "comment": "partial_close",
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        closed_positions.append(
            {
                "ticket": pos.ticket,
                "volume_closed": round(volume_now, 2),
                "result": result._asdict() if hasattr(result, "_asdict") else str(result),
            }
        )
        remaining_volume -= volume_now

    return {
        "status": "closed" if remaining_volume <= 0 else "partial",
        "remaining_volume": round(remaining_volume, 2),
        "closed_positions": closed_positions,
    }


def _open_additional_volume(symbol: str, volume: float, trade_type: str) -> Dict:
    _ensure_mt5_initialized()
    if volume <= 0:
        return {"status": "ignored", "reason": "no volume to add"}

    order_type = mt5.ORDER_TYPE_BUY if trade_type.lower().startswith("buy") else mt5.ORDER_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": round(volume, 2),
        "type": order_type,
        "price": mt5.symbol_info_tick(symbol).ask if order_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).bid,
        "deviation": 100,
        "magic": 0,
        "comment": "sync_trade_with_mt5",
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    result = mt5.order_send(request)
    return {"result": result._asdict() if hasattr(result, "_asdict") else str(result)}


def match_trade_risk_with_mt5(
    main_result: Dict,
    account_size: Optional[float] = None,
    multiplier: float = 1.0,
    state_path: str = "mt5_state.json",
    symbol_map: Optional[Dict[str, str]] = None,
    sl_points: Optional[float] = None,
    default_sl_points: float = 150.0,
) -> Dict:
    """Adjust an existing MT5 position to a new risk profile using a manual SL distance."""
    pair = main_result.get("pair")
    contract_size = main_result.get("contract_size")
    trade_type = str(main_result.get("trades", {}).get("trade_type", "unknown")).lower()
    symbol = _get_symbol(pair, symbol_map)
    if symbol is None:
        return {"action": "ignored", "reason": "unknown symbol for pair"}

    resolved_account_size = get_account_size() if account_size is None else float(account_size)
    desired_lots = _calculate_target_lots(contract_size, pair, resolved_account_size, multiplier)
    selected_sl_points = max(float(sl_points or default_sl_points), float(default_sl_points))
    existing_net_lots = _symbol_net_volume(symbol)

    if abs(existing_net_lots) < 0.001:
        return {"action": "waiting", "reason": "no existing MT5 position found to adjust", "symbol": symbol}

    desired_signed_lots = desired_lots if trade_type.startswith("buy") else -desired_lots
    if existing_net_lots * desired_signed_lots < 0:
        return {"action": "ignored", "reason": "position direction does not match requested trade direction", "symbol": symbol}

    positions = _get_mt5_positions(symbol)
    sl_updates = []
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return {"action": "ignored", "reason": "symbol info unavailable"}

    point_value = float(getattr(symbol_info, "point", 0.01))
    sl_distance = selected_sl_points * point_value
    for pos in positions:
        if (trade_type.startswith("buy") and pos.type == mt5.ORDER_TYPE_BUY) or (trade_type.startswith("sell") and pos.type == mt5.ORDER_TYPE_SELL):
            if pos.type == mt5.ORDER_TYPE_BUY:
                sl_price = pos.price_open - sl_distance
            else:
                sl_price = pos.price_open + sl_distance
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": pos.ticket,
                "symbol": symbol,
                "sl": sl_price,
                "tp": pos.tp,
            }
            result = mt5.order_send(request)
            sl_updates.append({"ticket": pos.ticket, "sl": sl_price, "result": result._asdict() if hasattr(result, "_asdict") else str(result)})

    volume_to_add = max(0.0, abs(desired_lots) - abs(existing_net_lots))
    add_result = {"status": "ignored", "reason": "no additional volume required"}
    if volume_to_add >= 0.01:
        add_result = _open_additional_volume(symbol, round(volume_to_add, 2), trade_type)

    state = _load_state(state_path)
    state.update({"pair": pair, "contract_size": contract_size, "lots": desired_signed_lots, "failure_count": 0})
    _save_state(state, state_path)

    return {
        "action": "match_risk",
        "symbol": symbol,
        "desired_lots": round(desired_lots, 2),
        "existing_net_lots": round(existing_net_lots, 2),
        "added_lots": round(volume_to_add, 2),
        "sl_points": round(selected_sl_points, 2),
        "sl_updates": sl_updates,
        "add_result": add_result,
    }


def sync_trade_with_mt5(
    main_result: Dict,
    account_size: Optional[float] = None,
    multiplier: float = 1.0,
    state_path: str = "mt5_state.json",
    symbol_map: Optional[Dict[str, str]] = None,
) -> Dict:
    """Synchronize one detected trade from main.py with MT5.

    This function:
    - only acts if main.py confirmed the trade pair and dakota image
    - ignores the trade until an MT5 position exists for the symbol
    - compares current lot risk to the desired contract size
    - adds to the position when the detected risk is larger
    - reduces the position only when main.py also reduced contract_size
    - closes MT5 positions when the trade disappears and confirmation exists
    """
    pair = main_result.get("pair")
    contract_size = main_result.get("contract_size")
    status = main_result.get("status")
    confirmed_dakota = main_result.get("confirmed_dakota", status == "success")
    confirmed_pair = main_result.get("confirmed_pair", bool(pair))

    state = _load_state(state_path)
    prev_pair = state.get("pair")
    prev_contract_size = state.get("contract_size")
    prev_lots = state.get("lots")
    failure_count = state.get("failure_count", 0)


    if not confirmed_dakota or not confirmed_pair or pair is None or contract_size is None:
        return {"action": "ignored", "reason": "trade not confirmed or missing contract data"}

    symbol = _get_symbol(pair, symbol_map)
    if symbol is None:
        return {"action": "ignored", "reason": "unknown symbol for pair"}

    resolved_account_size = get_account_size() if account_size is None else float(account_size)

    existing_net_lots = _symbol_net_volume(symbol)
    if abs(existing_net_lots) < 0.001:
        return {"action": "waiting", "reason": "trade exists in main.py but no MT5 position found yet", "symbol": symbol}

    desired_lots = _calculate_target_lots(contract_size, pair, resolved_account_size, multiplier)
    trade_type = str(main_result.get("trades", {}).get("trade_type", "unknown")).lower()

    # if trade_type == "unknown":
    #     if prev_pair and confirmed_pair and prev_pair == pair:
    #         failure_count += 1
    #         state.update({
    #             "pair": pair,
        #             "contract_size": contract_size,
        #             "lots": existing_net_lots,
    #             "failure_count": failure_count,
    #         })
    #         if failure_count >= 3:
    #             close_result = _close_symbol_positions(symbol)
    #             state.clear()
    #             _save_state(state, state_path)
    #             return {
    #                 "action": "closed_after_failures",
    #                 "symbol": symbol,
    #                 "close_result": close_result,
    #                 "failure_count": failure_count,
    #             }
    #         _save_state(state, state_path)
    #         return {
    #             "action": "ignored",
    #             "reason": "trade_type unknown, confirmed pair matches existing trade",
    #             "pair": pair,
    #             "failure_count": failure_count,
    #         }
    #     return {
    #         "action": "ignored",
    #         "reason": "trade_type unknown with no matching existing trade",
    #         "pair": pair,
    #     }

    desired_signed_lots = desired_lots if trade_type.startswith("buy") else -desired_lots

    if existing_net_lots * desired_signed_lots < 0:
        return {
            "action": "ignored",
            "reason": "existing MT5 position direction does not match detected trade direction",
            "symbol": symbol,
            "existing_net_lots": existing_net_lots,
            "desired_signed_lots": desired_signed_lots,
        }

    diff = desired_signed_lots - existing_net_lots
    if abs(diff) < 0.01:
        state.update({"pair": pair, "contract_size": contract_size, "lots": desired_signed_lots, "failure_count": 0})
        _save_state(state, state_path)
        return {"action": "matched", "symbol": symbol, "existing_net_lots": existing_net_lots, "desired_signed_lots": desired_signed_lots}

    if abs(existing_net_lots) < abs(desired_signed_lots):
        action_result = _open_additional_volume(symbol, abs(diff), trade_type)
        state.update({"pair": pair, "contract_size": contract_size, "lots": desired_signed_lots, "failure_count": 0})
        _save_state(state, state_path)
        return {
            "action": "add_volume",
            "symbol": symbol,
            "added_lots": abs(diff),
            "existing_net_lots": existing_net_lots,
            "desired_signed_lots": desired_signed_lots,
            "result": action_result,
        }

    if abs(existing_net_lots) > abs(desired_signed_lots):
        if prev_contract_size is not None and contract_size < prev_contract_size:
            reduce_amount = abs(existing_net_lots) - abs(desired_signed_lots)
            # close_result = _close_symbol_positions(symbol)
            partial_close_result = _close_partial_position(symbol, reduce_amount)
            state.update({"pair": pair, "contract_size": contract_size, "lots": desired_signed_lots, "failure_count": 0})
            _save_state(state, state_path)
            return {
                "action": "reduce_position",
                "symbol": symbol,
                "reduced_amount": reduce_amount,
                "existing_net_lots": existing_net_lots,
                "desired_signed_lots": desired_signed_lots,
                "close_result": partial_close_result,
            }
        return {
            "action": "ignored",
            "reason": "risk mismatch but main.py did not reduce contract size, so leave MT5 position unchanged",
            "symbol": symbol,
            "existing_net_lots": existing_net_lots,
            "desired_signed_lots": desired_signed_lots,
        }

    return {"action": "ignored", "reason": "no MT5 adjustment required"}
