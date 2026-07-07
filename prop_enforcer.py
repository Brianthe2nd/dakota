import datetime
import time

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - environment dependent
    mt5 = None

from mt5_funcs import (
    _calculate_target_lots,
    _get_mt5_positions,
    _get_symbol,
    get_account_size,
    match_trade_risk_with_mt5,
    sync_trade_with_mt5,
)


class PropFirmManager:
    def __init__(self, daily_drawdown_limit: float, dashboard_state, default_sl_points: int = 135):
        self.daily_dd = daily_drawdown_limit
        self.max_idea_risk = daily_drawdown_limit * 0.50
        self.min_trade_duration_seconds = 70
        self.default_sl_points = default_sl_points
        self.dash = dashboard_state
        self.dash.update("metrics", {"daily_dd": self.daily_dd, "max_idea_risk": self.max_idea_risk})

    def process_trade_signal(self, main_result: dict, account_size: float = None, multiplier: float = 1.0, state_path: str = "mt5_state.json", symbol_map: dict = None) -> dict:
        pair = main_result.get("pair")
        symbol = _get_symbol(pair, symbol_map)

        if not symbol:
            return {"action": "ignored", "reason": "No valid symbol found"}

        if not self._is_risk_acceptable(symbol, main_result):
            return {"action": "rejected", "reason": "Trade exceeds 50% daily drawdown risk limit"}

        self._delay_if_premature_close(symbol, main_result)

        sync_result = sync_trade_with_mt5(
            main_result,
            account_size=account_size,
            multiplier=multiplier,
            state_path=state_path,
            symbol_map=symbol_map,
        )

        self._enforce_stop_losses(symbol)
        return sync_result

    def process_manual_risk_match(self, payload: dict, account_size: float = None, multiplier: float = 1.0, state_path: str = "mt5_state.json", symbol_map: dict = None) -> dict:
        pair = payload.get("pair")
        symbol = _get_symbol(pair, symbol_map)
        if not symbol:
            return {"action": "ignored", "reason": "No valid symbol found"}

        trade_type = str(payload.get("trade_type", "buy")).lower()
        sl_points = float(payload.get("sl_points") or self.default_sl_points)
        effective_sl_points = max(sl_points, float(self.default_sl_points))
        main_result = {
            "pair": pair,
            "contract_size": payload.get("contract_size", 0),
            "status": "success",
            "confirmed_dakota": True,
            "confirmed_pair": bool(pair),
            "trades": {"trade_type": trade_type},
        }

        if not self._is_risk_acceptable(symbol, main_result, sl_points=effective_sl_points):
            return {"action": "rejected", "reason": "Trade exceeds 50% daily drawdown risk limit"}

        return match_trade_risk_with_mt5(
            main_result,
            account_size=account_size,
            multiplier=multiplier,
            state_path=state_path,
            symbol_map=symbol_map,
            sl_points=effective_sl_points,
            default_sl_points=float(self.default_sl_points),
        )

    def _delay_if_premature_close(self, symbol: str, main_result: dict):
        target_size = main_result.get("contract_size")
        if target_size is not None and target_size <= 0:
            positions = _get_mt5_positions(symbol)
            for pos in positions:
                elapsed_time = time.time() - pos.time
                if elapsed_time < self.min_trade_duration_seconds:
                    sleep_time = self.min_trade_duration_seconds - elapsed_time
                    msg = f"Rule 13 Active: Trade open {elapsed_time:.1f}s. Pausing for {sleep_time:.1f}s"
                    print(f"[Prop Firm Rule] {msg}")
                    self.dash.update("timer", {"active": True, "message": msg})
                    time.sleep(sleep_time)
                    self.dash.update("timer", {"active": False, "message": ""})

    def _enforce_stop_losses(self, symbol: str):
        if not mt5.terminal_info():
            mt5.initialize()

        positions = _get_mt5_positions(symbol)
        for pos in positions:
            if pos.sl == 0.0:
                point = mt5.symbol_info(symbol).point
                if pos.type == mt5.ORDER_TYPE_BUY:
                    sl_price = pos.price_open - self.default_sl_points
                else:
                    sl_price = pos.price_open + self.default_sl_points

                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": sl_price,
                    "tp": pos.tp,
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"[Prop Firm Rule] Emergency SL set for ticket {pos.ticket}")

    def _is_risk_acceptable(self, symbol: str, main_result: dict, sl_points: float = None) -> bool:
        trade_type_str = str(main_result.get("trades", {}).get("trade_type", "")).lower()
        if trade_type_str == "unknown" or not trade_type_str:
            return True

        is_buy = trade_type_str.startswith("buy")
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print(f"[Prop Firm Rule] Error: Could not get symbol info for {symbol}")
            return False

        tick_value, tick_size, point = symbol_info.trade_tick_value, symbol_info.trade_tick_size, symbol_info.point
        effective_sl_points = max(float(sl_points or self.default_sl_points), float(self.default_sl_points))
        sl_distance_price = effective_sl_points * point
        risk_per_lot = (sl_distance_price / tick_size) * tick_value

        open_risk = 0.0
        positions = _get_mt5_positions(symbol)
        existing_lots = 0.0

        for pos in positions:
            if pos.type == order_type:
                existing_lots += pos.volume
                if is_buy and pos.sl > 0 and pos.sl >= pos.price_open:
                    continue
                elif not is_buy and pos.sl > 0 and pos.sl <= pos.price_open:
                    continue

                if pos.sl > 0:
                    dist = (pos.price_open - pos.sl) if is_buy else (pos.sl - pos.price_open)
                    open_risk += (dist / tick_size) * tick_value * pos.volume
                else:
                    open_risk += risk_per_lot * pos.volume

        realized_idea_loss = 0.0
        time_from = datetime.datetime.now() - datetime.timedelta(minutes=30)
        deals = mt5.history_deals_get(time_from, datetime.datetime.now(), group=symbol)

        if deals:
            for deal in deals:
                if deal.entry == mt5.DEAL_ENTRY_OUT and deal.profit < 0 and deal.reason != mt5.DEAL_REASON_TP:
                    original_was_buy = deal.type == mt5.DEAL_TYPE_SELL
                    if (is_buy and original_was_buy) or (not is_buy and not original_was_buy):
                        realized_idea_loss += abs(deal.profit)

        try:
            account_size = get_account_size()
            contract_size = main_result.get("contract_size", 0)
            pair = main_result.get("pair")
            desired_lots = _calculate_target_lots(contract_size, pair, account_size)
            new_lots = max(0.0, desired_lots - existing_lots)
            new_trade_risk = new_lots * risk_per_lot
        except Exception:
            return False

        total_idea_risk = open_risk + realized_idea_loss + new_trade_risk
        self.dash.update("risk", {"open_risk": open_risk, "realized_loss_30m": realized_idea_loss, "total_risk": total_idea_risk})

        return total_idea_risk <= self.max_idea_risk



# import time
# import datetime
# import MetaTrader5 as mt5
# from mt5_funcs import sync_trade_with_mt5, _get_mt5_positions, _get_symbol, _calculate_target_lots, get_account_size


# class PropFirmManager:
#     def __init__(self, daily_drawdown_limit: float, default_sl_points: int = 150):
#         """
#         Initializes the compliance manager.
#         :param daily_drawdown_limit: The maximum monetary amount you are allowed to lose in a day.
#         :param default_sl_points: Fallback Stop Loss in points if one isn't provided by the strategy.
#         """
#         self.daily_dd = daily_drawdown_limit
#         # A trader may not risk more than 50% of the daily drawdown on a single trading idea.
#         self.max_idea_risk = daily_drawdown_limit * 0.50 
        
#         # Buffer to safely bypass the "Trades of less than 60 seconds duration are not allowed" rule.
#         self.min_trade_duration_seconds = 80
#         self.default_sl_points = default_sl_points
#     def process_trade_signal(self, main_result: dict, account_size: float = None, multiplier: float = 1.0, state_path: str = "mt5_state.json", symbol_map: dict = None) -> dict:
#             """
#             Wraps sync_trade_with_mt5 to enforce prop firm rules before and after execution.
#             """
#             pair = main_result.get("pair")
#             symbol = _get_symbol(pair, symbol_map)

#             if not symbol:
#                 return {"action": "ignored", "reason": "No valid symbol found"}

#             # 1. Enforce Risk Limits (50% of Daily DD)
#             if not self._is_risk_acceptable(symbol, main_result):
#                 return {"action": "rejected", "reason": "Trade exceeds 50% daily drawdown risk limit"}

#             # 2. Enforce Minimum Trade Duration (Wait 80s before closing)
#             self._delay_if_premature_close(symbol, main_result)

#             # 3. Execute the sync via mt5_funcs.py (Now passing all original arguments)
#             sync_result = sync_trade_with_mt5(
#                 main_result, 
#                 account_size=account_size, 
#                 multiplier=multiplier, 
#                 state_path=state_path, 
#                 symbol_map=symbol_map
#             )

#             # 4. Enforce Mandatory Stop Loss (Within 2 mins)
#             self._enforce_stop_losses(symbol)

#             return sync_result
    
#     def _delay_if_premature_close(self, symbol: str, main_result: dict):
#         """
#         Delays the execution if the strategy sends a signal to close/reduce a position 
#         that hasn't been open for at least 80 seconds.
#         """
#         target_size = main_result.get("contract_size")
        
#         # If target size is 0 or less, it implies a close/reduce signal.
#         # We need to check the lifetime of currently open positions.
#         if target_size is not None and target_size <= 0:
#             positions = _get_mt5_positions(symbol)
#             for pos in positions:
#                 elapsed_time = time.time() - pos.time
#                 if elapsed_time < self.min_trade_duration_seconds:
#                     sleep_time = self.min_trade_duration_seconds - elapsed_time
#                     print(f"[Prop Firm Rule] Position open for only {elapsed_time:.1f}s. Sleeping for {sleep_time:.1f}s to meet the >60s rule...")
#                     time.sleep(sleep_time)

#     def _enforce_stop_losses(self, symbol: str):
#         """
#         Checks all open positions for the symbol. If an SL is missing, it adds one immediately 
#         to comply with the strict 2-minute rule.
#         """
#         # Ensure MT5 is initialized
#         if not mt5.terminal_info():
#             mt5.initialize()
            
#         positions = _get_mt5_positions(symbol)
#         for pos in positions:
#             if pos.sl == 0.0:  # SL is missing
#                 point = mt5.symbol_info(symbol).point
                
#                 # Calculate basic SL based on position type
#                 if pos.type == mt5.ORDER_TYPE_BUY:
#                     sl_price = pos.price_open - (self.default_sl_points * point)
#                 else:
#                     sl_price = pos.price_open + (self.default_sl_points * point)

#                 request = {
#                     "action": mt5.TRADE_ACTION_SLTP,
#                     "position": pos.ticket,
#                     "symbol": symbol,
#                     "sl": sl_price,
#                     "tp": pos.tp
#                 }
                
#                 result = mt5.order_send(request)
#                 if result and result.retcode == mt5.TRADE_RETCODE_DONE:
#                     print(f"[Prop Firm Rule] Emergency SL set for ticket {pos.ticket} to avoid 2-minute violation.")
#                 else:
#                     print(f"[Warning] Failed to set SL for {pos.ticket}. Error: {mt5.last_error()}")
#     def _is_risk_acceptable(self, symbol: str, main_result: dict) -> bool:
#         """
#         Calculates if the intended trade breaks the rule of risking >50% Daily DD 
#         on a single trading idea.
#         """
#         trade_type_str = str(main_result.get("trades", {}).get("trade_type", "")).lower()
        
#         # If the strategy is sending a close/reduce signal, it doesn't add risk. Allow it.
#         if trade_type_str == "unknown" or not trade_type_str:
#             return True 
            
#         is_buy = trade_type_str.startswith("buy")
#         order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

#         # --- 1. Calculate MT5 Symbol Metrics ---
#         symbol_info = mt5.symbol_info(symbol)
#         if symbol_info is None:
#             print(f"[Prop Firm Rule] Error: Could not get symbol info for {symbol}")
#             return False

#         tick_value = symbol_info.trade_tick_value
#         tick_size = symbol_info.trade_tick_size
#         point = symbol_info.point
        
#         # Risk (Monetary) per Lot for our default SL distance [cite: 7]
#         sl_distance_price = self.default_sl_points * point
#         risk_per_lot = (sl_distance_price / tick_size) * tick_value

#         # --- 2. Calculate Active Open Risk ---
#         open_risk = 0.0
#         positions = _get_mt5_positions(symbol)
#         existing_lots = 0.0
        
#         for pos in positions:
#             if pos.type == order_type:  # Same direction [cite: 4]
#                 existing_lots += pos.volume
                
#                 # Trades at BE and TP do not count towards risk.
#                 # A buy position is at BE when SL is at or above the entry price,
#                 # and a sell position is at BE when SL is at or below the entry price.
#                 if is_buy and pos.sl > 0 and pos.sl >= pos.price_open:
#                     continue
#                 elif not is_buy and pos.sl > 0 and pos.sl <= pos.price_open:
#                     continue
                
#                 # Calculate the highest risk defined by the stop loss [cite: 7]
#                 if pos.sl > 0:
#                     dist = (pos.price_open - pos.sl) if is_buy else (pos.sl - pos.price_open)
#                     open_risk += (dist / tick_size) * tick_value * pos.volume
#                 else:
#                     # If SL isn't placed yet, calculate based on the default SL we will enforce
#                     open_risk += risk_per_lot * pos.volume

#         # --- 3. Calculate Realized Loss from the Same Trading Idea (Last 30 mins) ---
#         # "Executed within a time interval of no more than 30 minutes" 
#         realized_idea_loss = 0.0
#         time_from = datetime.datetime.now() - datetime.timedelta(minutes=30)
#         deals = mt5.history_deals_get(time_from, datetime.datetime.now(), group=symbol)
        
#         if deals:
#             for deal in deals:
#                 # We only care about closing deals (DEAL_ENTRY_OUT) that resulted in a loss.
#                 # Trades closed at TP/BE do not count towards risk limits.
#                 if deal.entry == mt5.DEAL_ENTRY_OUT and deal.profit < 0 and deal.reason != mt5.DEAL_REASON_TP:
#                     # MT5 Deal Types are inverted for exits. A SELL deal closes a BUY position.
#                     original_was_buy = (deal.type == mt5.DEAL_TYPE_SELL)
#                     # Check if it was in the same direction 
#                     if (is_buy and original_was_buy) or (not is_buy and not original_was_buy):
#                         realized_idea_loss += abs(deal.profit)

#         # --- 4. Calculate Risk of the NEW Trade ---
#         try:
#             account_size = get_account_size()
#             contract_size = main_result.get("contract_size", 0)
#             pair = main_result.get("pair")
#             # Calculate total lots desired by the strategy
#             desired_lots = _calculate_target_lots(contract_size, pair, account_size)
            
#             # We only calculate new risk if we are ADDING volume to the market
#             new_lots = max(0.0, desired_lots - existing_lots)
#             new_trade_risk = new_lots * risk_per_lot
            
#         except Exception as e:
#             print(f"[Prop Firm Rule] Error calculating target lots: {e}")
#             return False

#         # --- 5. Final Evaluation ---
#         total_idea_risk = open_risk + realized_idea_loss + new_trade_risk
        
#         # A trader may not risk more than 50% of the daily drawdown on a single trading idea [cite: 1]
#         if total_idea_risk > self.max_idea_risk:
#             print(f"[Prop Firm Rule] BLOCKED: Idea Risk ({total_idea_risk:.2f}) exceeds 50% Daily DD limit ({self.max_idea_risk:.2f}).")
#             print(f"   -> Breakdown: Open Risk: {open_risk:.2f} | Realized 30m Loss: {realized_idea_loss:.2f} | New Trade Risk: {new_trade_risk:.2f}")
#             return False
            
#         print(f"[Prop Firm Rule] PASSED: Idea Risk ({total_idea_risk:.2f}) is within limits.")
#         return True