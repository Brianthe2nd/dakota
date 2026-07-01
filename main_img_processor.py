import cv2
import json
import os
from logo import get_logo_data
from trade_object import fetch_trades
from contract import get_contact_size as get_contract_size

CONFIG_PATH = "config.json"
DEFAULT_DAKOTA_CONFIRMATION_TEMPLATES = [
    "samples/dakota_confirmation.png",
    "samples/dakota_confirmation_2.png",
]
DEFAULT_DAKOTA_CONFIRMATION_THRESHOLD = 0.9


def load_dakota_confirmation_settings(config_path=CONFIG_PATH):
    templates = DEFAULT_DAKOTA_CONFIRMATION_TEMPLATES
    threshold = DEFAULT_DAKOTA_CONFIRMATION_THRESHOLD
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            dakota_config = config.get("dakota_confirmation", {})
            if dakota_config:
                templates = dakota_config.get("templates", templates)
                if isinstance(templates, str):
                    templates = [templates]
                threshold = dakota_config.get("threshold", threshold)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return templates, threshold


DAKOTA_CONFIRMATION_TEMPLATES, DAKOTA_CONFIRMATION_THRESHOLD = load_dakota_confirmation_settings()

# Get logo location and adjust cropping coordinates
logo_size, logo_loc = get_logo_data(image_path="sample_images/vlcsnap-2026-06-19-15h25m09s986.png", template_path="samples/logo.png", config_path="config.json", force_detect=True, threshold=0.4)
(logo_x1, logo_y1), (logo_x2, logo_y2) = logo_loc

# Calculate offset from assumed top-left position (2, 3)
assumed_logo_x, assumed_logo_y = 2, 3
x_offset = logo_x1 - assumed_logo_x
y_offset = logo_y1 - assumed_logo_y

print(f"Logo location: {logo_loc}")
print(f"Logo size: {logo_size}")
print(f"X offset: {x_offset}, Y offset: {y_offset}")

def confirm_dakota(image):
    height, width, _ = image.shape
    c_height = 242 + y_offset
    c_width = width // 2  + x_offset
    cropped_img = image[0:c_height , 0:c_width]
    print(f"Cropped image dimensions for dakota confirmation: {cropped_img.shape}")
    # cv2.imshow("Cropped Image confirm dakota", cropped_img)
    # cv2.waitKey(0)

    for template_path in DAKOTA_CONFIRMATION_TEMPLATES:
        dakota_confirmation = cv2.imread(template_path)
        print(f"dakota confirmation dimensions: {dakota_confirmation.shape if dakota_confirmation is not None else 'Failed to load'}")
        if dakota_confirmation is None:
            print(f"Warning: Could not read dakota confirmation template: {template_path}")
            continue

        similarity = cv2.matchTemplate(cropped_img, dakota_confirmation, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(similarity)
        print(f"Similarity score for {template_path}: {max_val}")

        if max_val > DAKOTA_CONFIRMATION_THRESHOLD:
            print(f"Confirmed dakota with template {template_path}")
            return True

    print("No dakota confirmation template matched.")
    return False

def confirm_pair(image):
    height, width, _ = image.shape
    c_height = 66 + y_offset
    c_width = 490 + x_offset
    cropped_img = image[0:c_height + 119, 0:c_width]
    # cv2.imshow("Cropped Image confirm pair", cropped_img)
    # cv2.waitKey(0)
    nq = cv2.imread("samples/nasdaq.png")
    gold = cv2.imread("samples/gold.png")
    if nq is None or gold is None:
        print("Error: Could not read the confirmation images.")
        return False
    else:
        nq_similarity = cv2.matchTemplate(cropped_img, nq, cv2.TM_CCOEFF_NORMED)
        nq_min_val, nq_max_val, nq_min_loc, nq_max_loc = cv2.minMaxLoc(nq_similarity)
        print(f"Nasdaq similarity score: {nq_max_val}")

        gold_similarity = cv2.matchTemplate(cropped_img, gold, cv2.TM_CCOEFF_NORMED)
        gold_min_val, gold_max_val, gold_min_loc, gold_max_loc = cv2.minMaxLoc(gold_similarity)
        print(f"Gold similarity score: {gold_max_val}")

        if nq_max_val > 0.8 and nq_max_val > gold_max_val:
            print("Confirmed: Nasdaq")
            return "Nasdaq"
        elif gold_max_val > 0.8 and gold_max_val > nq_max_val:
            print("Confirmed: Gold")
            return "Gold"
        else:
            print("No clear confirmation for Nasdaq or Gold.")
            return None


def process_new_image(image_path):
    """
    Process a new image from the server:
    1. Verify it's from dakota
    2. Confirm the trading pair
    3. Fetch and extract trades from the image
    
    Args:
        image_path: Path to the image file
        
    Returns:
        dict with status, pair, and trades (if successful), or error info
    """
    # Read the image
    image = cv2.imread(image_path)
    if image is None:
        print(f"Error: Could not read image at {image_path}")
        return {"status": "error", "message": "Failed to read image"}
    
    # Step 1: Check if it's from dakota
    print(f"\n[Step 1] Verifying image is from dakota...")
    is_dakota = confirm_dakota(image)
    if not is_dakota:
        print("Image not confirmed as dakota image. Skipping.")
        return {"status": "rejected", "message": "Not a dakota image"}
    
    print("✓ Confirmed: Dakota image")
    
    # Step 2: Confirm the trading pair
    print(f"\n[Step 2] Confirming trading pair...")
    pair = confirm_pair(image)
    if pair is None:
        print("Could not confirm trading pair. Skipping.")
        return {"status": "rejected", "message": "Could not confirm pair"}
    
    print(f"✓ Confirmed pair: {pair}")
    
    # Step 3: Fetch trades from the image
    print(f"\n[Step 3] Extracting trades from image...")
    try:
        trade_info = fetch_trades(image, logo_size, logo_loc)
        print("✓ Trade extraction completed")

        section2_bbox = trade_info.get("section2_bbox")
        # cv2.imwrite("section2_bbox.png", section2_bbox)
        contract_size = None
        if section2_bbox is not None:
            # cv2.imshow("Section 2 Image for Contract Size", section2_bbox)
            # cv2.waitKey(0)
            # cv2.destroyAllWindows()
            contract_size = get_contract_size(section2_bbox)
            print(f"Contract size extracted: {contract_size}")
        else:
            print("Section 2 bounding box not found.")
        
        # print("what is happening")
        # remove section2_bbox from trade_info to avoid returning image data in the final result
        trade_info.pop("section2_bbox", None)
        # print("Trade info: ", trade_info)
        return {
            "status": "success",
            "pair": pair,
            "trades": trade_info,
            "logo_size": logo_size,
            "logo_loc": logo_loc,
            "contract_size": contract_size
        }
    except Exception as e:
        import traceback
        print(f"Error fetching trades: {e}")
        traceback.print_exc()
        return {"status": "error", "message": f"Failed to fetch trades: {str(e)}"}


def watch_and_process_frames(frames_folder="./received_frames", on_result=None):
    """
    Monitor the received_frames folder and process new images as they arrive.
    This is useful for real-time processing of frames from the server.
    
    Args:
        frames_folder: Path to the folder where frames are saved by the server
        on_result: Optional callback invoked with (result, image_path)
    """
    
    print(f"Watching {frames_folder} for new frames...")
    
    while True:
        try:
            if not os.path.exists(frames_folder):
                print(f"Frames folder not found: {frames_folder}")
                break
            
            files = sorted(os.listdir(frames_folder))
            for filename in files:
                if filename.endswith('.jpg'):
                    image_path = os.path.join(frames_folder, filename)
                    print(f"\nProcessing: {filename}")
                    
                    result = process_new_image(image_path)
                    print(f"Result: {result}")
                    
                    if on_result is not None:
                        try:
                            on_result(result, image_path)
                        except Exception as callback_error:
                            print(f"Error in result callback: {callback_error}")
                    
                    
            
        except KeyboardInterrupt:
            print("\nStopping frame watcher.")
            break
        except Exception as e:
            print(f"Error in frame watcher: {e}")


# Example usage:
if __name__ == "__main__":
    # Option 1: Process a single image
    result = process_new_image("/home/brian/Desktop/yt/sample_images/vlcsnap-2026-06-19-17h58m31s400.png")
    print("RESULT")
    print(result)
    
    # Option 2: Watch and automatically process new frames as they arrive
    # watch_and_process_frames("./received_frames")
    pass




