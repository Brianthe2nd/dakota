import argparse
import os
import threading
import time
import datetime
import MetaTrader5 as mt5

from main_img_processor import (
    process_new_image,
    watch_and_process_frames,
    process_result_entries_from_json,
)
from mt5_funcs import get_account_size
from prop_enforcer import PropFirmManager
from dashboard_state import DashboardState  # Import State Manager

def mt5_data_poller(dash_state):
    """Background thread to continuously update MT5 positions/deals to the UI."""
    mt5.initialize()
    while True:
        try:
            # 1. Fetch Positions
            positions = mt5.positions_get()
            pos_data = []
            if positions:
                for p in positions:
                    pos_data.append({
                        "ticket": p.ticket,
                        "symbol": p.symbol,
                        "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                        "volume": p.volume,
                        "profit": p.profit,
                        "sl": p.sl
                    })
            dash_state.update("positions", pos_data)

            # 2. Fetch Deals (Last 30 Mins)
            time_from = datetime.datetime.now() - datetime.timedelta(minutes=30)
            deals = mt5.history_deals_get(time_from, datetime.datetime.now())
            deal_data = []
            if deals:
                for d in deals:
                    # Filter for out deals
                    if d.entry == mt5.DEAL_ENTRY_OUT:
                        deal_data.append({
                            "ticket": d.ticket,
                            "symbol": d.symbol,
                            "profit": d.profit,
                            "time": datetime.datetime.fromtimestamp(d.time).strftime("%H:%M:%S")
                        })
            # Reverse to show newest deals first
            dash_state.update("deals", deal_data[::-1])
            
            # 3. Keep account size refreshed
            acc_info = mt5.account_info()
            if acc_info:
                dash_state.update("metrics", {"account_size": acc_info.balance})

        except Exception as e:
            import traceback
            print("Error in mt5 data poller:", e)
            traceback.print_exc()
            pass
        time.sleep(2) # Poll every 2 seconds

def build_mt5_callback(prop_manager, dashboard_state, account_size=10000.0, multiplier=1.0, state_path="mt5_state.json", symbol_map=None):
    last_trade_signature = None

    def handle_result(result, image_path):
        nonlocal last_trade_signature
        if result.get("status") != "success":
            return

        trade_signature = (
            result.get("pair"),
            result.get("contract_size"),
            result.get("trades", {}).get("trade_type"),
            result.get("status"),
        )
        if trade_signature != last_trade_signature:
            last_trade_signature = trade_signature
            dashboard_state.update(
                "pending_match_risk",
                {
                    "pair": result.get("pair"),
                    "contract_size": result.get("contract_size"),
                    "trade_type": result.get("trades", {}).get("trade_type"),
                    "image_path": image_path,
                    "source": "new_trade_signal",
                },
            )

        print(f"Synchronizing MT5 for {image_path}...")
        try:
            sync_res = prop_manager.process_trade_signal(
                result,
                account_size=account_size,
                multiplier=multiplier,
                state_path=state_path,
                symbol_map=symbol_map,
            )
            result["mt5_sync"] = sync_res
            print(f"MT5 sync result for {image_path}: {result['mt5_sync']}")
            
            # Log successful signal processing to Dashboard
            dashboard_state.add_log({
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "pair": result.get("pair"),
                "contract_size": result.get("contract_size", "N/A"),
                "trade_type": result.get("trades", {}).get("trade_type", "Unknown"),
                "result": sync_res.get("action", "Processed"),
                "reason": sync_res.get("reason", "")
            })

        except Exception as exc:
            result["mt5_sync_error"] = str(exc)
            print(f"MT5 sync failed for {image_path}: {exc}")
            # Log error to Dashboard
            dashboard_state.add_log({
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "pair": result.get("pair"),
                "contract_size": result.get("contract_size", "N/A"),
                "trade_type": "ERROR",
                "result": "Failed",
                "reason": str(exc)
            })

    return handle_result

def main():
    parser = argparse.ArgumentParser(description="Process Dakota frames and sync trades safely via Prop Enforcer")
    parser.add_argument("--frames-folder", default=os.getenv("FRAMES_FOLDER", "./received_frames"))
    parser.add_argument("--results", help="Path to a JSON file containing precomputed result objects")
    parser.add_argument("--account-size", type=float, default=None)
    parser.add_argument("--multiplier", type=float, default=float(os.getenv("MULTIPLIER", "1.0")))
    parser.add_argument("--state-path", default=os.getenv("MT5_STATE_PATH", "mt5_state.json"))
    parser.add_argument("--daily-dd", type=float, default=None)
    parser.add_argument("--default-sl", type=int, default=int(os.getenv("DEFAULT_SL", "150")))
    args = parser.parse_args()

    account_size = args.account_size
    if account_size is None:
        account_size = get_account_size()
    if args.daily_dd is None:
        args.daily_dd = float((2/100)* account_size)
    # 1. Initialize Dashboard State
    dash_state = DashboardState()
    dash_state.install_log_stream(log_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "main.py.log"), stream_name="main.py")
    dash_state.update("metrics", {"account_size": account_size})

    # 2. Start Background Data Poller
    poller_thread = threading.Thread(target=mt5_data_poller, args=(dash_state,), daemon=True)
    poller_thread.start()

    # 3. Initialize PropFirm Manager
    prop_manager = PropFirmManager(
        daily_drawdown_limit=args.daily_dd, 
        dashboard_state=dash_state,
        default_sl_points=args.default_sl
    )

    callback = build_mt5_callback(
        prop_manager=prop_manager,
        dashboard_state=dash_state,
        account_size=account_size,
        multiplier=args.multiplier,
        state_path=args.state_path,
    )
    # If a results JSON is provided, process those precomputed results and exit.
    if args.results:
        print(f"Processing precomputed result entries from {args.results}")
        process_result_entries_from_json(args.results, on_result=callback)
        return

    watch_and_process_frames(frames_folder=args.frames_folder, on_result=callback)

if __name__ == "__main__":
    main()
#  import argparse
# import os

# from main_img_processor import process_new_image, watch_and_process_frames
# from mt5_funcs import get_account_size
# from prop_enforcer import PropFirmManager  # Import the new compliance manager


# def process_image_and_sync(
#     image_path,
#     prop_manager,  # Now requiring the manager
#     account_size=10000.0,
#     multiplier=1.0,
#     state_path="mt5_state.json",
#     symbol_map=None,
# ):
#     result = process_new_image(image_path)
#     if result.get("status") == "success":
#         try:
#             # Route through the prop firm manager instead of sync_trade_with_mt5
#             result["mt5_sync"] = prop_manager.process_trade_signal(
#                 result,
#                 account_size=account_size,
#                 multiplier=multiplier,
#                 state_path=state_path,
#                 symbol_map=symbol_map,
#             )
#         except Exception as exc:
#             result["mt5_sync_error"] = str(exc)
#     return result


# def build_mt5_callback(prop_manager, account_size=10000.0, multiplier=1.0, state_path="mt5_state.json", symbol_map=None):
#     def handle_result(result, image_path):
#         if result.get("status") != "success":
#             return

#         print(f"Synchronizing MT5 for {image_path}...")
#         try:
#             # Route through the prop firm manager instead of sync_trade_with_mt5
#             result["mt5_sync"] = prop_manager.process_trade_signal(
#                 result,
#                 account_size=account_size,
#                 multiplier=multiplier,
#                 state_path=state_path,
#                 symbol_map=symbol_map,
#             )
#             print(f"MT5 sync result for {image_path}: {result['mt5_sync']}")
#         except Exception as exc:
#             result["mt5_sync_error"] = str(exc)
#             print(f"MT5 sync failed for {image_path}: {exc}")

#     return handle_result


# def main():
#     parser = argparse.ArgumentParser(description="Process Dakota frames and sync trades safely via Prop Enforcer")
#     parser.add_argument("image_path", nargs="?", help="Optional single image to process")
#     parser.add_argument("--frames-folder", default=os.getenv("FRAMES_FOLDER", "./received_frames"))
#     parser.add_argument("--account-size", type=float, default=None)
#     parser.add_argument("--multiplier", type=float, default=float(os.getenv("MULTIPLIER", "1.0")))
#     parser.add_argument("--state-path", default=os.getenv("MT5_STATE_PATH", "mt5_state.json"))
    
#     # New Arguments for Prop Firm Compliance
#     parser.add_argument("--daily-dd", type=float, default=float(os.getenv("DAILY_DD", "2500.0")), help="Maximum daily drawdown allowance")
#     parser.add_argument("--default-sl", type=int, default=int(os.getenv("DEFAULT_SL", "150")), help="Default Stop Loss in points if missing")
    
#     args = parser.parse_args()

#     account_size = args.account_size
#     if account_size is None:
#         print("Fetching account size from MT5...")
#         account_size = get_account_size()
#         print(f"Using account size: {account_size}")

#     # Initialize the Prop Firm Manager
#     print(f"Initializing Prop Enforcer: Daily DD Limit = {args.daily_dd}, Default SL = {args.default_sl} points.")
#     prop_manager = PropFirmManager(
#         daily_drawdown_limit=args.daily_dd, 
#         default_sl_points=args.default_sl
#     )

#     if args.image_path:
#         result = process_image_and_sync(
#             args.image_path,
#             prop_manager=prop_manager,
#             account_size=account_size,
#             multiplier=args.multiplier,
#             state_path=args.state_path,
#         )
#         print(result)
#         return

#     callback = build_mt5_callback(
#         prop_manager=prop_manager,
#         account_size=account_size,
#         multiplier=args.multiplier,
#         state_path=args.state_path,
#     )
    
#     watch_and_process_frames(frames_folder=args.frames_folder, on_result=callback)


# if __name__ == "__main__":
#     main()