
from PIL import Image, ImageDraw, ImageFont, ImageOps
import os
import cv2
from color import verify_trade_object_colors
from color import get_base_widths
from face import find_camera_box
import time
import numpy as np

def resize_proportional(img_array, width=None, height=None):
    """
    Resize an image proportionally using either width or height.
    - img_array: input image as a NumPy array (e.g., from cv2.imread)
    - width: desired width (optional)
    - height: desired height (optional)
    Returns: resized image as a NumPy array
    """
    h, w = img_array.shape[:2]

    if width is None and height is None:
        raise ValueError("Either width or height must be specified.")

    if width is not None:
        # Calculate new height to maintain aspect ratio
        aspect_ratio = h / w
        new_height = int(width * aspect_ratio)
        new_size = (width, new_height)
    else:
        # Calculate new width to maintain aspect ratio
        aspect_ratio = w / h
        new_width = int(height * aspect_ratio)
        new_size = (new_width, height)

    resized = cv2.resize(img_array, new_size, interpolation=cv2.INTER_AREA)
    return resized





def similarity(image,template,handle_blur = True,threshold = 0.7):
    if image is None or template is None:
        raise ValueError("One of the images could not be read — check file paths.")

    if image.dtype != np.uint8:
        image = image.astype(np.uint8)
    if template.dtype != np.uint8:
        template = template.astype(np.uint8)
    def estimate_blur(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()

    def match_blur(image, template):
        blur_img = estimate_blur(image)
        blur_tpl = estimate_blur(template)

        if blur_tpl > blur_img:
            blur_strength = np.sqrt(blur_tpl / blur_img)
            ksize = int(max(3, min(blur_strength * 3, 25)))  # limit kernel size
            template = cv2.GaussianBlur(template, (ksize | 1, ksize | 1), 0)

        elif blur_img > blur_tpl:
            blur_strength = np.sqrt(blur_img / blur_tpl)
            ksize = int(max(3, min(blur_strength * 3, 25)))
            image = cv2.GaussianBlur(image, (ksize | 1, ksize | 1), 0)
        return image, template
    if handle_blur == True:
        image, template = match_blur(image, template)


    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)

    locations = np.where(result >= threshold)
    points = list(zip(*locations[::-1]))  # (x, y) points
    _, highest_similarity, _, _ = cv2.minMaxLoc(result)
    min_distance  = 10
    template_h , template_w = template.shape[:2]
    filtered_points = []
    for pt in points:
        if all(np.linalg.norm(np.array(pt) - np.array(fp)) > min_distance for fp in filtered_points):
            filtered_points.append(pt)

    points_f =[]
    # print(f"The length of the filtered points is: {len(filtered_points)}")
    # print(filtered_points)
    if len(filtered_points) != 0 :
        for pt in filtered_points:
            x_min, y_min = pt
            x_max, y_max = x_min + template_w, y_min + template_h
            # cv2.rectangle(image, (x_min, y_min), (x_max, y_max), (0, 255, 0), 2)
            point = ((x_min,y_min),(x_max, y_max))
            points_f.append(point)
    
    # cv2.namedWindow("D", cv2.WINDOW_NORMAL)
    # cv2.imshow("D", image)
    # cv2.resizeWindow("D", 1280, 720)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()

    
    return highest_similarity,points_f



def create_trade_object(line_type):
    if line_type == "buy_in_profit":
        return cv2.imread("samples/buy_in_profit.png")
    elif line_type == "buy_in_loss":
        return cv2.imread("samples/buy_in_loss.png")
    elif line_type == "sell_in_profit":
        return cv2.imread("samples/sell_in_profit.png")
    elif line_type == "sell_in_loss":
        return cv2.imread("samples/sell_in_loss.png")
    elif line_type == "sl":
        return cv2.imread("samples/sl.png")
    elif line_type == "tp":
        return cv2.imread("samples/buy_in_profit.png")

def undo_rotate_180(point, width, height):
    
    x, y = point

    # Undo 180 rotation: same formula as rotate, because 180° twice = identity
    normal_x = width - 1 - x
    normal_y = height - 1 - y

    return normal_x, normal_y



def point_in_face_box(image, face_boxes, pt, point_height, point_width):
    """
    expects pt to be in the format (x,y)
    Returns True if the object (defined by top-left pt + size)
    intersects any face bounding box.
    """

    if not face_boxes:
        return False

    x1, y1 = pt
    img_h, img_w = image.shape[:2]

    # Undo rotation (your original function call)
    x1, y1 = undo_rotate_180((x1, y1), img_w, img_h)

    # Object bounding box
    obj_x1 = x1
    obj_y1 = y1
    obj_x2 = x1 + point_width
    obj_y2 = y1 + point_height

    for (fx1, fy1, fx2, fy2) in face_boxes:

        # ---------------------------
        # RECTANGLE INTERSECTION TEST
        # ---------------------------
        overlap_x = not (obj_x2 < fx1 or obj_x1 > fx2)
        overlap_y = not (obj_y2 < fy1 or obj_y1 > fy2)

        if overlap_x and overlap_y:
            return True  # object touches or enters face area

    return False

# def get_resize_height(logo_height):
#     # 39 = 17
#     # 49 = 20 
#     # logo_height =
#     # 74.5 = 16
#     # logo
#     # return int((logo_height * 20) / 49)
#     return int((logo_height * 16) / 74.5)


def get_resize_height(trade_type,logo_height):
    import json
    with open("config.json","r") as file:
        json_data = json.load(file)
        if "logo_2" in json_data.get("logo").get("template_path"):
            logo_height = (59.5 * logo_height)/64
        

    base_logo_height = 59.5
    if trade_type == "sl":
        return int((logo_height * 19)/base_logo_height)
    if trade_type == "sell_in_profit":
        return int((logo_height * 22)/base_logo_height)
    if trade_type == "buy_in_loss":
        return int((logo_height * 21)/base_logo_height)
    if trade_type == "buy_in_profit":
        return int((logo_height * 22)/base_logo_height)
    if trade_type == "tp":
        return int((logo_height * 22)/base_logo_height)
    if trade_type == "sell_in_loss":
        return int((logo_height * 22)/base_logo_height)
    



def fetch_trades(image, logo_height, logo_loc): 
    total_start = time.time()
    
    # --- Initialization ---
    top_left, bottom_right = logo_loc
    bottom_right_y = bottom_right[1]
    hi, wi = image.shape[:2]
    
    face_box = find_camera_box()
    image = cv2.rotate(image, cv2.ROTATE_180)
    
    confirmed_tt = []
    found_main_trade = False 
    section2_bbox = None
    trade_types = ["buy_in_loss", "sell_in_profit", "sell_in_loss", "buy_in_profit", "sl", "tp"]
    # resize_height = get_resize_height(logo_height)
    # print(f"Resize height for trade objects: {resize_height}")
    threshold = 0.65
    min_dist = 2  # Suppression radius

    # --- Stage 1: Main trade detection ---
    for trade_type in trade_types:
        if found_main_trade or trade_type in ["tp", "sl"]:
            continue

        type_start = time.time()
        resize_height = get_resize_height(trade_type,logo_height)
        print(f"Resize height for {trade_type}: {resize_height}")
        trade_object = create_trade_object(line_type=trade_type)
        trade_object = resize_proportional(trade_object, height=resize_height)
        th, tw = trade_object.shape[:2]
        trade_object = cv2.rotate(trade_object, cv2.ROTATE_180)
        
        result = cv2.matchTemplate(image, trade_object, cv2.TM_CCOEFF_NORMED)
        
        # --- OPTIMIZED SUPPRESSION ---
        loc = np.where(result >= threshold)
        scores = result[loc]
        # Sort by match quality (best first)
        sorted_indices = np.argsort(scores)[::-1]
        
        # Use a boolean mask to "visit" pixels - much faster than linalg.norm
        mask = np.zeros(result.shape, dtype=bool)
        matched_points = []

        for idx in sorted_indices:
            
            pt_y, pt_x = loc[0][idx], loc[1][idx]
            similarity = scores[idx]
            print(f"similarity: {similarity:.4f} at ({pt_x}, {pt_y})")
            
            if mask[pt_y, pt_x]:
                continue
            
            # Mark neighborhood as visited
            y1, y2 = max(0, pt_y - min_dist), min(result.shape[0], pt_y + min_dist + 1)
            x1, x2 = max(0, pt_x - min_dist), min(result.shape[1], pt_x + min_dist + 1)
            mask[y1:y2, x1:x2] = True
            
            # Logic constraints
            rotated_y = abs(hi - pt_y - th)
            if not point_in_face_box(image, face_box, (pt_x, pt_y), th, tw) and rotated_y > bottom_right_y:
                cropped = image[pt_y:pt_y+th, pt_x:pt_x+tw]
                
                cropped = cv2.rotate(cropped, cv2.ROTATE_180)
                
                # cv2.imshow("Cropped Image for Color Verification", cropped)
                # cv2.waitKey(0)
                # cv2.destroyAllWindows()
                trade_c = verify_trade_object_colors(cropped, trade_type, resize_height=resize_height)
                print(trade_c)
                if trade_c["match"]:
                    # cv2.rectangle(image, (pt_x,pt_y),(pt_x+tw ,pt_y+th), (0,255,0) , 1)
                    # cv2.imshow("Match", image)
                    # cv2.waitKey(0)
                    # cv2.destroyAllWindows()
                    matched_points.append((pt_x, pt_y))

                    if section2_bbox is None and trade_type not in ["tp", "sl"]:
                        # crop the image to the detected trade object and calculate section widths
                        
                        section1_width, section2_width, _ = get_base_widths(trade_type,width = tw) 
                        section2_bbox = cropped[0:th,section1_width:section1_width + section2_width]
                        # cv2.imshow("Section 2 BBox", section2_bbox)
                        # cv2.waitKey(0)
                        # cv2.destroyAllWindows()
                        # section2_bbox = (
                        #     (pt_x + section1_width, pt_y),
                        #     (pt_x + section1_width + section2_width, pt_y + th)
                        # )

                    if trade_type in ["buy_in_loss", "sell_in_loss", "sell_in_profit"]:
                        found_main_trade = True
                        break
        
        # Second-stage 10px filter (only on a few points, so standard loop is fine here)
        refined_points = []
        for pt in matched_points:
            if all(np.linalg.norm(np.array(pt) - np.array(fp)) > 10 for fp in refined_points):
                refined_points.append(pt)
        
        confirmed_tt.extend([trade_type] * len(refined_points))
        print(f"[TIMER] {trade_type} took: {time.time() - type_start:.4f}s")
    # from dump import display_image
    # display_image(image)
    # --- Stage 2: SL / TP Detection ---
    tp = False
    sl = False
    if found_main_trade or "buy_in_profit" in confirmed_tt:
        check_tp = (confirmed_tt.count("buy_in_profit") > 1) if "buy_in_profit" in confirmed_tt else True

        # --- SL CHECK ---
        sl_start = time.time()
        sl_obj = create_trade_object(line_type="sl")
        sl_obj = resize_proportional(sl_obj, height=resize_height)
        sl_obj = cv2.rotate(sl_obj, cv2.ROTATE_180)
        res_sl = cv2.matchTemplate(image, sl_obj, cv2.TM_CCOEFF_NORMED)
        
        sl_loc = np.where(res_sl >= threshold)
        sl_mask = np.zeros(res_sl.shape, dtype=bool)
        sl_th, sl_tw = sl_obj.shape[:2]
        
        for idx in np.argsort(res_sl[sl_loc])[::-1]:
            py, px = sl_loc[0][idx], sl_loc[1][idx]
            if sl_mask[py, px]: continue
            sl_mask[max(0, py-min_dist):py+min_dist+1, max(0, px-min_dist):px+min_dist+1] = True
            
            if not point_in_face_box(image, face_box, (px, py), sl_th, sl_tw) and abs(hi - py - sl_th) > bottom_right_y:
                cropped = image[py:py+sl_th, px:px+sl_tw]
                
                cropped = cv2.rotate(cropped, cv2.ROTATE_180)
                if verify_trade_object_colors(cropped, "sl", resize_height=resize_height)["match"]:
                    cv2.rectangle(image, (px,py),(px+sl_tw ,py+sl_th), (0,255,0) , 1)
                    sl = True
                    break
        print(f"[TIMER] SL Stage took: {time.time() - sl_start:.4f}s")

        # --- TP CHECK ---
        if check_tp:
            tp_start = time.time()
            for trade_type in ["tp", "buy_in_profit"]:
                tp_obj = create_trade_object(line_type=trade_type)
                tp_obj = resize_proportional(tp_obj, height=resize_height)
                tp_obj = cv2.rotate(tp_obj, cv2.ROTATE_180)
                res_tp = cv2.matchTemplate(image, tp_obj, cv2.TM_CCOEFF_NORMED)
                
                tp_loc = np.where(res_tp >= threshold)
                tp_mask = np.zeros(res_tp.shape, dtype=bool)
                tph, tpw = tp_obj.shape[:2]
                
                for idx in np.argsort(res_tp[tp_loc])[::-1]:
                    py, px = tp_loc[0][idx], tp_loc[1][idx]
                    if tp_mask[py, px]: continue
                    tp_mask[max(0, py-min_dist):py+min_dist+1, max(0, px-min_dist):px+min_dist+1] = True
                    
                    if not point_in_face_box(image, face_box, (px, py), tph, tpw) and abs(hi - py - tph) > bottom_right_y:
                        cropped = image[py:py+tph, px:px+tpw]
                        
                        cropped = cv2.rotate(cropped, cv2.ROTATE_180)
                        if verify_trade_object_colors(cropped, trade_type, resize_height=resize_height)["match"]:
                            cv2.rectangle(image, (px,py),(px+tpw ,py+tph), (0,255,0) , 1)
                            tp = True
                            break
                if tp: break
            print(f"[TIMER] TP Stage took: {time.time() - tp_start:.4f}s")

    
     
    # --- Final Mapping ---
    main_trade, status = "unknown", None
    if "buy_in_loss" in confirmed_tt: main_trade, status = "buy", "loss"
    elif "sell_in_loss" in confirmed_tt: main_trade, status = "sell", "loss"
    elif "sell_in_profit" in confirmed_tt: main_trade, status = "sell", "profit"
    elif "buy_in_profit" in confirmed_tt: main_trade, status = "buy", "profit"

    if "buy_in_profit" in confirmed_tt:
        tp = confirmed_tt.count("buy_in_profit") > 1

    print(f"*** TOTAL EXECUTION TIME: {time.time() - total_start:.4f}s ***")
    trade_d = {
        "trade_type": main_trade,
        "status": status,
        "sl": sl,
        "tp": tp,
        "section2_bbox": section2_bbox
    }
    # print(trade_d)
    # cv2.namedWindow("frame",cv2.WINDOW_NORMAL)
    # cv2.imshow("frame",image)
    # # cv2.resizeWindow("frame",1280,720)
    # cv2.waitKey()
    # cv2.destroyAllWindows()
    return trade_d
# def fetch_trades(image,logo_height,logo_loc):
#     bs_start = time.time()
#     top_left , bottom_right = logo_loc
#     bottom_right_y = bottom_right[1]
#     hi,wi = image.shape[:2]
#     face_box = find_camera_box(image)
#     image = cv2.rotate(image, cv2.ROTATE_180)
#     confirmed_tt = []
#     found_main_trade = False  # flag for early exit condition
#     trade_types = ["buy_in_loss", "sell_in_profit", "sell_in_loss","buy_in_profit", "sl", "tp"]
#     # trade_types = ["buy_in_profit", "sl"]
#     resize_height = get_resize_height(logo_height)
#     threshold = 0.5
#     # threshold = 0.71
#     # --- Stage 1: Main trade detection ---
#     min_distance = 2
#     for trade_type in trade_types:
#         if found_main_trade:
#             break
#         # skip TP/SL in first stage
#         if trade_type in ["tp","sl"]:
#             continue

#         start = time.time()
#         trade_object = create_trade_object(line_type=trade_type)
#         print("")
#         trade_object = resize_proportional(trade_object, height=resize_height)
#         th , tw = trade_object.shape[:2]
#         trade_object = cv2.rotate(trade_object, cv2.ROTATE_180)
#         # start = time.time()
#         result = cv2.matchTemplate(image, trade_object, cv2.TM_CCOEFF_NORMED)
#         # print(f"matching the trade object took: {start - time.time()} seconds")
#         # min_distance = 1
#         # --- buy_in_profit: check all matches ---
        
#         if trade_type == "buy_in_profit": 
#             start = time.time()
#             loc = np.where(result >= threshold)
#             print(f"scanning the trade object took: {start - time.time()} seconds")
#             scan_filtered_points = []      # 2px scan-time filter
#             matched_points = []             # (pt, trade_type)

            
#             print(f"Some BS took:   {time.time() - bs_start} seconds")    
#             print(f"There are {len(loc[::-1])} points")
#             main_start = time.time()
#             for pt in zip(*loc[::-1]):
#                 start = time.time()
#                 pt_x, pt_y = pt
#                 rotated_y = abs(hi - pt[1] - th)

#                 if rotated_y > bottom_right_y:
                    
#                     if all(np.linalg.norm(np.array(pt) - np.array(fp)) > min_distance
#                         for fp in scan_filtered_points):

#                         scan_filtered_points.append(pt)
                        
#                         if not point_in_face_box(image, face_box, pt, th, tw):
                            
#                             cropped = image[pt[1]:pt[1]+th, pt[0]:pt[0]+tw]

#                             cropped = cv2.rotate(cropped, cv2.ROTATE_180)
#                             start - time.time()
#                             trade_c = verify_trade_object_colors(
#                                 cropped,
#                                 trade_type,
#                                 resize_height=resize_height
#                             )
#                             print("Confirming the trade colors took: ",time.time() - start)

#                             if trade_c["match"]:
#                                 matched_points.append(pt)

#             # --------------------------------------------------
#             # SECOND-STAGE FILTERING (10px)
#             # --------------------------------------------------
#             final_min_distance = 10
#             refined_points = []

#             for pt in matched_points:
#                 if all(np.linalg.norm(np.array(pt) - np.array(fp)) > final_min_distance
#                     for fp in refined_points):
#                     refined_points.append(pt)

#             # --------------------------------------------------
#             # FINAL confirmed_tt (same behavior as original code)
#             # --------------------------------------------------
#             confirmed_tt.extend(["buy_in_profit"] * len(refined_points))
#             print(f"Confirming the colors on the image took: {time.time() - main_start}")
        
#         else:
#             loc = np.where(result >= threshold)
#             th, tw = trade_object.shape[:2]

#             scan_filtered_points = []      # 2px scan-time filter
#             matched_points = []            # store matched points only

#             min_distance = 2

#             for pt in zip(*loc[::-1]):
#                 pt_x, pt_y = pt
#                 rotated_y = abs(hi - pt[1] - th)

#                 if all(np.linalg.norm(np.array(pt) - np.array(fp)) > min_distance
#                     for fp in scan_filtered_points):

#                     scan_filtered_points.append(pt)

#                     if (not point_in_face_box(image, face_box, pt, th, tw)) and \
#                     rotated_y > bottom_right_y:

#                         cropped = image[pt[1]:pt[1]+th, pt[0]:pt[0]+tw]
#                         cropped = cv2.rotate(cropped, cv2.ROTATE_180)

#                         trade_c = verify_trade_object_colors(
#                             cropped,
#                             trade_type,
#                             resize_height=resize_height
#                         )

#                         if trade_c["match"]:
#                             print(trade_c)
#                             matched_points.append(pt)

#                             # preserve early exit for main trade detection
#                             if trade_type in ["buy_in_loss", "sell_in_loss", "sell_in_profit"]:
#                                 found_main_trade = True
#                                 break

#             # --------------------------------------------------
#             # SECOND-STAGE FILTERING (10px)
#             # --------------------------------------------------
#             final_min_distance = 10
#             refined_points = []

#             for pt in matched_points:
#                 if all(np.linalg.norm(np.array(pt) - np.array(fp)) > final_min_distance
#                     for fp in refined_points):
#                     refined_points.append(pt)

#             # --------------------------------------------------
#             # FINAL confirmed_tt (same output semantics as before)
#             # --------------------------------------------------
#             confirmed_tt.extend([trade_type] * len(refined_points))

    
#     tp = False
#     sl = False

#     if "buy_in_profit" in confirmed_tt:
#         check_tp = confirmed_tt.count("buy_in_profit") > 1
#     else:
#         check_tp = True

#     if found_main_trade or "buy_in_profit" in confirmed_tt:
#         # check SL
            
#         for trade_type in ["sl"]:
#             filtered_points =[]
#             trade_object = create_trade_object(line_type=trade_type)
#             trade_object = resize_proportional(trade_object, height=resize_height)
#             trade_object = cv2.rotate(trade_object, cv2.ROTATE_180)

#             result = cv2.matchTemplate(image, trade_object, cv2.TM_CCOEFF_NORMED)

#             # --- GET ALL MATCHES ABOVE threshold ---
#             loc = np.where(result >= threshold)

#             th, tw = trade_object.shape[:2]
#             # print(f"We have {len(loc[0])} matches")

#             for pt in zip(*loc[::-1]): 
#                 pt_x, pt_y = pt
#                 if all(np.linalg.norm(np.array(pt) - np.array(fp)) > min_distance for fp in filtered_points):
#                     filtered_points.append(pt)
#                     max_loc = (pt_x, pt_y)
#                     rotated_y = abs(hi - pt_y - th)

#                     # skip unwanted locations
#                     if point_in_face_box(image, face_box, max_loc, th, tw):
#                         continue
#                     if rotated_y <= bottom_right_y:
#                         continue

#                     # extract and rotate
#                     cropped = image[pt_y:pt_y + th, pt_x:pt_x + tw]
#                     cropped = cv2.rotate(cropped, cv2.ROTATE_180)

#                     trade_c = verify_trade_object_colors(cropped, trade_type, resize_height=resize_height)
#                     if trade_c["match"]:
#                         print(trade_c)
#                         sl = True
#                         break

#         if check_tp:
#             filtered_points =[]
#             # for this loop we have both tp and buy_in_profit because they are visually the same and just have minor differences
#             for trade_type in ["tp" , "buy_in_profit"]:
#                 trade_object = create_trade_object(line_type=trade_type)
#                 trade_object = resize_proportional(trade_object, height=resize_height)
#                 trade_object = cv2.rotate(trade_object, cv2.ROTATE_180)

#                 result = cv2.matchTemplate(image, trade_object, cv2.TM_CCOEFF_NORMED)

#                 loc = np.where(result >= threshold)

#                 th, tw = trade_object.shape[:2]
#                 # print(f"We have {len(loc[0])} matches")

#                 for pt in zip(*loc[::-1]): 
#                     pt_x, pt_y = pt
#                     if all(np.linalg.norm(np.array(pt) - np.array(fp)) > min_distance for fp in filtered_points):
#                         filtered_points.append(pt)
#                         max_loc = (pt_x, pt_y)
#                         rotated_y = abs(hi - pt_y - th)

#                         # skip unwanted locations
#                         if point_in_face_box(image, face_box, max_loc, th, tw):
#                             continue
#                         if rotated_y <= bottom_right_y:
#                             continue

#                         # extract and rotate
#                         cropped = image[pt_y:pt_y + th, pt_x:pt_x + tw]
#                         cropped = cv2.rotate(cropped, cv2.ROTATE_180)

#                         trade_c = verify_trade_object_colors(cropped, trade_type, resize_height=resize_height)

#                         if trade_c["match"]:
#                             print(trade_c)
#                             tp = True
#                             break

#     main_trade, status = "unknown", None
#     if "buy_in_loss" in confirmed_tt:
#         main_trade, status = "buy", "loss"
#     elif "sell_in_loss" in confirmed_tt:
#         main_trade, status = "sell", "loss"
#     elif "sell_in_profit" in confirmed_tt:
#         main_trade, status = "sell", "profit"
#     elif "buy_in_profit" in confirmed_tt:
#         main_trade, status = "buy", "profit"

#     # --- If buy_in_profit matched multiple times → both TP + Buy-in-Profit exist ---
#     two_objects = confirmed_tt.count("buy_in_profit") > 1
#     print("confirmed trade objects")
#     print(confirmed_tt)
#     if "buy_in_profit" in confirmed_tt:
#         # print("There is more than one buy")
        
#         tp = False if not two_objects else True  # use your rule

#     return {
#         "trade_type": main_trade,
#         "status": status,
#         "sl": sl,
#         "tp": tp
#     }

if __name__ == "__main__":
    # trade_types = ["buy_in_profit", "buy_in_loss", "sell_in_profit", "sell_in_loss",
    #                "buy_sl", "sell_sl", "buy_tp", "sell_tp"]
    # from logo import detect_best_logo_height
    image = cv2.imread("sample_images/vlcsnap-2026-06-19-15h25m09s986.png")
    # frame_image = cv2.imread("frame.jpg")
    # logo_height = 66
    # logo_template = cv2.imread("templates/x_logo.png")
    # logo_size,_,logo_loc = detect_best_logo_height(frame_image,logo_template)
    # {'logo_height': 41.6, 'logo_top_left': (178, 51), 'logo_bottom_right': (219, 92)}
    logo_size = 59.5
    logo_loc = ((178, 51),(219, 92))
    trades = fetch_trades(image,logo_size,logo_loc)
    print(trades)
    # match_image = cv2.imread("buy_in_profit.png")  
    # match_fail_image = cv2.imread("surviving_crop_138_277.png")
      
    # match_result = verify_trade_object_colors(match_image,"buy_in_profit")
    # match_fail_result = verify_trade_object_colors(match_fail_image,"buy_in_profit")
    # print("Match Result")
    # print(match_result)
    # print("\n")
    # print("Match Fail Result")
    # print(match_fail_result)
    
        
            

def get_best_trade_object(image_path: str = "frame_3.png",
                          trade_types: list = None,
                          try_heights: list = None):
    """Search `image_path` for the best-fitting trade object by resizing
    templates and using template matching. Prints best similarity, height,
    and width, draws a rectangle around the best match, and saves an
    annotated image next to the input.

    Returns a dict with keys: `similarity`, `height`, `width`, `trade_type`,
    `location`, `annotated_path`.
    """
    if trade_types is None:
        trade_types = ["buy_in_profit", "sl"]

    if try_heights is None:
        try_heights = list(range(20, 82, 2))

    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    hi, wi = img.shape[:2]
    # work in the same rotated coordinate space used elsewhere
    search_img = cv2.rotate(img, cv2.ROTATE_180)

    best = {
        "sim": -1.0,
        "trade_type": None,
        "height": 0,
        "width": 0,
        "pt": (0, 0)
    }

    for trade_type in trade_types:
        print(f"Checking trade type: {trade_type}")
        tpl = create_trade_object(line_type=trade_type)
        # cv2.imshow("Template", tpl)
        # cv2.waitKey(0)
        for h in try_heights:
            try:
                tpl_r = resize_proportional(tpl, height=h)
            except Exception:
                continue

            th, tw = tpl_r.shape[:2]
            # rotate template to match pipeline
            tpl_r = cv2.rotate(tpl_r, cv2.ROTATE_180)

            res = cv2.matchTemplate(search_img, tpl_r, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

            if max_val > best["sim"]:
                best["sim"] = float(max_val)
                best["trade_type"] = trade_type
                best["height"] = int(th)
                best["width"] = int(tw)
                best["pt"] = (int(max_loc[0]), int(max_loc[1]))

    if best["sim"] < 0:
        print("No matches found")
        return None

    pt_x, pt_y = best["pt"]
    th, tw = best["height"], best["width"]

    # convert top-left in rotated image back to original image coords
    orig_x, orig_y = undo_rotate_180((pt_x, pt_y), wi, hi)

    annotated = img.copy()
    cv2.rectangle(annotated, (orig_x, orig_y), (orig_x + tw, orig_y + th), (0, 255, 0), 2)

    # out_path = os.path.splitext(image_path)[0] + "_annotated.png"
    # cv2.imwrite(out_path, annotated)

    print(f"Best similarity: {best['sim']:.4f}")
    print(f"Matched template size (h x w): {th} x {tw}")
    print(f"Trade type: {best['trade_type']}")
    # print(f"Annotated image saved to: {out_path}")

    return {
        "similarity": best["sim"],
        "height": th,
        "width": tw,
        "trade_type": best["trade_type"],
        "location": (orig_x, orig_y)
        # "annotated_path": out_path
    }

            


