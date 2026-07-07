import argparse
import csv
import itertools
from typing import Iterable

import cv2
import numpy as np

from trade_object import create_trade_object, resize_proportional, undo_rotate_180

# optional progress bar
try:
    from tqdm import tqdm
except Exception:
    def tqdm(iterable, **kwargs):
        return iterable


def grid_search_trade_object_configs(
    contract_path: str = "vlcsnap-2026-06-19-15h25m26s466.png",
    trade_types: Iterable[str] = ["buy_in_profit","buy_in_loss","sell_in_profit","sell_in_loss","sl"],
    heights: Iterable[int] = list(range(16,26)),
    ticks_size: int = 8,
    padding: int = 3,
    one_size: int = 9,
    output_csv: str = "trade_object_results.csv",
    top_n: int = 10,
    match_method=cv2.TM_CCOEFF_NORMED,
):
    print(f"Grid search over trade object configs for contract: {contract_path}")
    """
    Grid-search over `trade_types` and `heights` for a fixed trade object
    appearance.

    - Rotates images 180 degrees as required by the pipeline.
    - Prints the top `top_n` combinations and saves the rest to `output_csv`.

    Returns the list of top-n result dicts.
    """

    img = cv2.imread(contract_path)
    if img is None:
        raise FileNotFoundError(f"Could not read contract image: {contract_path}")

    # rotate search image into the same coordinate space used elsewhere
    search_img = cv2.rotate(img, cv2.ROTATE_180)

    combos = list(itertools.product(trade_types, heights))

    results = []

    for trade_type, height in tqdm(combos, desc="Grid search", total=len(combos)):
        try:
            tpl = create_trade_object(line_type=trade_type)
            if tpl is None:
                print(f"Skipping invalid trade object config: ticks_size={ticks_size}, padding={padding}, _1_size={one_size}, trade_type={trade_type}")
                continue

            # resize proportionally to requested height
            try:
                tpl_r = resize_proportional(tpl, height=height)
            except Exception:
                # skip invalid sizes
                print(f"Skipping invalid resize for trade object config: ticks_size={ticks_size}, padding={padding}, _1_size={one_size}, trade_type={trade_type}, height={height}")
                continue

            # rotate template into matching orientation
            tpl_r = cv2.rotate(tpl_r, cv2.ROTATE_180)

            # template matching
            if tpl_r is None or tpl_r.size == 0:
                print(f"Skipping empty template for trade object config: ticks_size={ticks_size}, padding={padding}, _1_size={one_size}, trade_type={trade_type}, height={height}")
                continue

            res = cv2.matchTemplate(search_img, tpl_r, match_method)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            th, tw = tpl_r.shape[:2]
            # print(f"Match for config: ticks_size={ticks_size}, padding={padding}, _1_size={one_size}, trade_type={trade_type}, height={height} => similarity={max_val:.4f} at {max_loc} size={th}x{tw}")

            results.append({
                "similarity": float(max_val),
                "ticks_size": int(ticks_size),
                "padding": int(padding),
                "_1_size": int(one_size),
                "trade_type": trade_type,
                "height": int(th),
                "width": int(tw),
                "match_pt": (int(max_loc[0]), int(max_loc[1])),
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            # keep grid search robust; skip failing combos
            print(f"Error occurred while processing trade object config: ticks_size={ticks_size}, padding={padding}, _1_size={one_size}, trade_type={trade_type}, height={height}")
            print(f"Error: {e}")
            continue

    if not results:
        print("No valid results found.")
        return []

    # sort by similarity (desc)
    results.sort(key=lambda r: r["similarity"], reverse=True)

    top_results = results[:top_n]
    rest = results[top_n:]

    print(f"Top {top_n} matches:")
    for i, r in enumerate(top_results, start=1):
        print(f"{i}. similarity={r['similarity']:.4f} ticks_size={r['ticks_size']} padding={r['padding']} _1_size={r['_1_size']} trade_type={r['trade_type']} size={r['height']}x{r['width']} pt={r['match_pt']}")

    # save rest to CSV
    if results:
        with open(output_csv, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["similarity", "ticks_size", "padding", "_1_size", "trade_type", "height", "width", "match_pt"])
            writer.writeheader()
            for r in results:
                # flatten match_pt
                row = r.copy()
                row["match_pt"] = f"{r['match_pt'][0]},{r['match_pt'][1]}"
                writer.writerow(row)
        print(f"Wrote {len(results)} remaining combinations to {output_csv}")

    return top_results


def find_and_show_trade_object(
    contract_path: str = "contract.png",
    ticks_size: int = 8,
    padding: int = 3,
    one_size: int = 9,
    trade_type: str = "sl",
    height: int = 28,
    match_method=cv2.TM_CCOEFF_NORMED,
):
    """
    Create a single trade object, match it against `contract_path`, and show the result.
    """
    img = cv2.imread(contract_path)
    if img is None:
        raise FileNotFoundError(f"Could not read contract image: {contract_path}")

    hi, wi = img.shape[:2]
    search_img = cv2.rotate(img, cv2.ROTATE_180)

    tpl = create_trade_object( line_type=trade_type)
    if tpl is None:
        raise RuntimeError("Failed to create trade object template.")

    tpl_r = resize_proportional(tpl, height=22)
    tpl_r = cv2.rotate(tpl_r, cv2.ROTATE_180)

    if tpl_r is None or tpl_r.size == 0:
        raise RuntimeError("Resized template is empty.")

    res = cv2.matchTemplate(search_img, tpl_r, match_method)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    th, tw = tpl_r.shape[:2]
    orig_x, orig_y = undo_rotate_180((max_loc[0], max_loc[1]), wi, hi)
    cv2.rectangle(search_img, (max_loc[0], max_loc[1]), (max_loc[0] + tw, max_loc[1] + th), (0, 255, 0), 2)
    annotated = img.copy()
    cv2.rectangle(annotated, (orig_x, orig_y), (orig_x + tw, orig_y + th), (0, 255, 0), 2)
    cv2.putText(
        annotated,
        f"sim={max_val:.4f}",
        (orig_x, max(15, orig_y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 255, 0),
        1,
        cv2.LINE_AA,
    )
    cv2.imwrite("annotated_contract_unmodified.png", search_img)
    cv2.imshow("Contract unmodified", search_img)
    cv2.imshow("Contract", annotated)
    cv2.imshow("Template", tpl_r)
    print(f"Best similarity: {max_val:.4f}")
    print(f"Trade type: {trade_type}")
    print(f"Ticks size: {ticks_size}, padding: {padding}, _1_size: {one_size}, height: {height}")
    print(f"Match location: {orig_x},{orig_y}")
    print("Press any key in the image window to close.")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    return {
        "similarity": float(max_val),
        "ticks_size": ticks_size,
        "padding": padding,
        "_1_size": one_size,
        "trade_type": trade_type,
        "height": th,
        "width": tw,
        "location": (orig_x, orig_y),
    }


def prompt_for_single_values():
    print("Enter values for a single trade object search.")
    contract_path = input("Contract image path [contract.png]: ").strip() or "contract.png"
    trade_type = input("Trade type [buy_in_profit]: ").strip() or "buy_in_profit"
    ticks_size = int(input("Ticks size [8]: ").strip() or 8)
    padding = int(input("Padding [3]: ").strip() or 3)
    one_size = int(input("_1_size [9]: ").strip() or 9)
    height = int(input("Resize height [28]: ").strip() or 28)
    return contract_path, trade_type, ticks_size, padding, one_size, height


def main():
    import os 
    contracts = os.listdir("sample_images")
    for contract in contracts:
        print (f"Processing contract: {contract}")
        parser = argparse.ArgumentParser(description="Trade object matching utility")
        parser.add_argument("--mode", choices=["grid", "single"], default="single", help="Choose either a grid search or a single-match mode.")
        parser.add_argument("--contract", default="c.png", help="Path to the contract image.")
        parser.add_argument("--trade_type", default="buy_in_profit", help="Trade object line type.")
        parser.add_argument("--ticks_size", type=int, default=8, help="Font ticks size for the trade object.")
        parser.add_argument("--padding", type=int, default=3, help="Padding for the trade object.")
        parser.add_argument("--one_size", type=int, default=9, help="Size for the 1 font in the trade object.")
        parser.add_argument("--height", type=int, default=28, help="Resize height for the trade object template.")
        parser.add_argument("--interactive", action="store_true", help="Prompt for single input values.")
        args = parser.parse_args()
        
        if args.mode == "grid":
            grid_search_trade_object_configs(contract_path=os.path.join("sample_images", contract))
            print("\n")
            # return
            continue  # Continue to the next contract image after grid search
        if args.interactive:
            contract_path, trade_type, ticks_size, padding, one_size, height = prompt_for_single_values()
        else:
            contract_path = args.contract
            trade_type = args.trade_type
            ticks_size = args.ticks_size
            padding = args.padding
            one_size = args.one_size
            height = args.height
        contract_path = "vlcsnap-2026-06-19-15h25m26s466.png"
        trade_type = "sl"
        height = 19
        find_and_show_trade_object(
            contract_path=contract_path,
            ticks_size=ticks_size,
            padding=padding,
            one_size=one_size,
            trade_type=trade_type,
            height=height,
        )


if __name__ == "__main__":
    main()
