import argparse
import os

from main_img_processor import process_new_image, watch_and_process_frames
from mt5_funcs import get_account_size, sync_trade_with_mt5


def process_image_and_sync(
    image_path,
    account_size=10000.0,
    multiplier=1.0,
    state_path="mt5_state.json",
    symbol_map=None,
):
    result = process_new_image(image_path)
    if result.get("status") == "success":
        try:
            result["mt5_sync"] = sync_trade_with_mt5(
                result,
                account_size=account_size,
                multiplier=multiplier,
                state_path=state_path,
                symbol_map=symbol_map,
            )
        except Exception as exc:
            result["mt5_sync_error"] = str(exc)
    return result


def build_mt5_callback(account_size=10000.0, multiplier=1.0, state_path="mt5_state.json", symbol_map=None):
    def handle_result(result, image_path):
        if result.get("status") != "success":
            return

        print(f"Synchronizing MT5 for {image_path}...")
        try:
            result["mt5_sync"] = sync_trade_with_mt5(
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
    parser = argparse.ArgumentParser(description="Process Dakota frames and optionally sync trades to MT5")
    parser.add_argument("image_path", nargs="?", help="Optional single image to process")
    parser.add_argument("--frames-folder", default=os.getenv("FRAMES_FOLDER", "./received_frames"))
    parser.add_argument("--account-size", type=float, default=None)
    parser.add_argument("--multiplier", type=float, default=float(os.getenv("MULTIPLIER", "1.0")))
    parser.add_argument("--state-path", default=os.getenv("MT5_STATE_PATH", "mt5_state.json"))
    args = parser.parse_args()

    account_size = args.account_size
    if account_size is None:
        print("Fetching account size from MT5...")
        account_size = get_account_size()
        print(f"Using account size: {account_size}")

    if args.image_path:
        result = process_image_and_sync(
            args.image_path,
            account_size=account_size,
            multiplier=args.multiplier,
            state_path=args.state_path,
        )
        print(result)
        return

    callback = build_mt5_callback(
        account_size=account_size,
        multiplier=args.multiplier,
        state_path=args.state_path,
    )
    watch_and_process_frames(frames_folder=args.frames_folder, on_result=callback)


if __name__ == "__main__":
    main()
