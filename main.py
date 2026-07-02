import argparse
import os

from main_img_processor import process_new_image, watch_and_process_frames
from mt5_funcs import get_account_size
from prop_enforcer import PropFirmManager  # Import the new compliance manager


def process_image_and_sync(
    image_path,
    prop_manager,  # Now requiring the manager
    account_size=10000.0,
    multiplier=1.0,
    state_path="mt5_state.json",
    symbol_map=None,
):
    result = process_new_image(image_path)
    if result.get("status") == "success":
        try:
            # Route through the prop firm manager instead of sync_trade_with_mt5
            result["mt5_sync"] = prop_manager.process_trade_signal(
                result,
                account_size=account_size,
                multiplier=multiplier,
                state_path=state_path,
                symbol_map=symbol_map,
            )
        except Exception as exc:
            result["mt5_sync_error"] = str(exc)
    return result


def build_mt5_callback(prop_manager, account_size=10000.0, multiplier=1.0, state_path="mt5_state.json", symbol_map=None):
    def handle_result(result, image_path):
        if result.get("status") != "success":
            return

        print(f"Synchronizing MT5 for {image_path}...")
        try:
            # Route through the prop firm manager instead of sync_trade_with_mt5
            result["mt5_sync"] = prop_manager.process_trade_signal(
                result,
                account_size=account_size,
                multiplier=multiplier,
                state_path=state_path,
                symbol_map=symbol_map,
            )
            print(f"MT5 sync result for {image_path}: {result['mt5_sync']}")
        except Exception as exc:
            result["mt5_sync_error"] = str(exc)
            print(f"MT5 sync failed for {image_path}: {exc}")

    return handle_result


def main():
    parser = argparse.ArgumentParser(description="Process Dakota frames and sync trades safely via Prop Enforcer")
    parser.add_argument("image_path", nargs="?", help="Optional single image to process")
    parser.add_argument("--frames-folder", default=os.getenv("FRAMES_FOLDER", "./received_frames"))
    parser.add_argument("--account-size", type=float, default=None)
    parser.add_argument("--multiplier", type=float, default=float(os.getenv("MULTIPLIER", "1.0")))
    parser.add_argument("--state-path", default=os.getenv("MT5_STATE_PATH", "mt5_state.json"))
    
    # New Arguments for Prop Firm Compliance
    parser.add_argument("--daily-dd", type=float, default=float(os.getenv("DAILY_DD", "2500.0")), help="Maximum daily drawdown allowance")
    parser.add_argument("--default-sl", type=int, default=int(os.getenv("DEFAULT_SL", "150")), help="Default Stop Loss in points if missing")
    
    args = parser.parse_args()

    account_size = args.account_size
    if account_size is None:
        print("Fetching account size from MT5...")
        account_size = get_account_size()
        print(f"Using account size: {account_size}")

    # Initialize the Prop Firm Manager
    print(f"Initializing Prop Enforcer: Daily DD Limit = {args.daily_dd}, Default SL = {args.default_sl} points.")
    prop_manager = PropFirmManager(
        daily_drawdown_limit=args.daily_dd, 
        default_sl_points=args.default_sl
    )

    if args.image_path:
        result = process_image_and_sync(
            args.image_path,
            prop_manager=prop_manager,
            account_size=account_size,
            multiplier=args.multiplier,
            state_path=args.state_path,
        )
        print(result)
        return

    callback = build_mt5_callback(
        prop_manager=prop_manager,
        account_size=account_size,
        multiplier=args.multiplier,
        state_path=args.state_path,
    )
    
    watch_and_process_frames(frames_folder=args.frames_folder, on_result=callback)


if __name__ == "__main__":
    main()