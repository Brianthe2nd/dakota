import json
import os
from typing import Dict, Optional

try:
    import MetaTrader5 as mt5  # type: ignore[import]
except ImportError:
    mt5 = None


DEFAULT_SYMBOL_MAP = {
    "nasdaq": "NAS100",
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
    normalized_contract_size = account_size * contract_size / dakotas_acc_size
    scaled = normalized_contract_size * multiplier
    lots = max(0.01, round(scaled / 10000.0, 2))
    return lots


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

    if trade_type == "unknown":
        if prev_pair and confirmed_pair and prev_pair == pair:
            failure_count += 1
            state.update({
                "pair": pair,
                "contract_size": contract_size,
                "lots": existing_net_lots,
                "failure_count": failure_count,
            })
            if failure_count >= 3:
                close_result = _close_symbol_positions(symbol)
                state.clear()
                _save_state(state, state_path)
                return {
                    "action": "closed_after_failures",
                    "symbol": symbol,
                    "close_result": close_result,
                    "failure_count": failure_count,
                }
            _save_state(state, state_path)
            return {
                "action": "ignored",
                "reason": "trade_type unknown, confirmed pair matches existing trade",
                "pair": pair,
                "failure_count": failure_count,
            }
        return {
            "action": "ignored",
            "reason": "trade_type unknown with no matching existing trade",
            "pair": pair,
        }

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
            close_result = _close_symbol_positions(symbol)
            state.update({"pair": pair, "contract_size": contract_size, "lots": desired_signed_lots, "failure_count": 0})
            _save_state(state, state_path)
            return {
                "action": "reduce_position",
                "symbol": symbol,
                "reduced_amount": reduce_amount,
                "existing_net_lots": existing_net_lots,
                "desired_signed_lots": desired_signed_lots,
                "close_result": close_result,
            }
        return {
            "action": "ignored",
            "reason": "risk mismatch but main.py did not reduce contract size, so leave MT5 position unchanged",
            "symbol": symbol,
            "existing_net_lots": existing_net_lots,
            "desired_signed_lots": desired_signed_lots,
        }

    return {"action": "ignored", "reason": "no MT5 adjustment required"}
