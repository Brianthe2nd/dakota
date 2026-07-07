"""
Extract green/red highlighted prices from a trading ladder / DOM screenshot.

"""

import re
import cv2
import numpy as np
import pytesseract


def extract_highlighted_prices(
    image,
    min_row_coverage=0.5,   # a row counts as "highlighted" if this fraction of its width is the target hue
    max_gap=5,              # merge bands separated by a gap of up to this many rows (text can break the mask)
    saturation_thresh=80,   # minimum HSV saturation to count as a colored (non-gray/white/black) pixel
    padding=4,               # extra rows of context added above/below each band before OCR
    upscale=4,               # upscaling factor applied before OCR (tesseract likes bigger text)
):
    """
    Find horizontal rows highlighted green or red in a price-ladder image and OCR the price on each.

    Parameters
    ----------
    image : str | np.ndarray
        Path to an image file, or an already-loaded BGR image (as returned by cv2.imread).

    Returns
    -------
    list[dict]
        One entry per highlighted row, each with:
          - "color": "green" or "red"
          - "price_text": the raw OCR string, e.g. "29,838.50"
          - "price": float value if it parsed cleanly (e.g. 29838.50), else None
          - "bbox": (x, y, w, h) of the highlighted band in the original image
        Ordered top-to-bottom as they appear in the image.
    """
    img = cv2.imread(image) if isinstance(image, str) else image
    if img is None:
        raise ValueError("Could not load image (bad path or unreadable file)")

    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, _ = cv2.split(hsv)

    # Hue ~0/180 = red (wraps around), hue ~40-80 = green. Saturation filters out
    # the white/gray text and black background, leaving only the colored highlight fill.
    masks = {
        "red": (((H <= 10) | (H >= 170)) & (S > saturation_thresh)).astype(np.uint8),
        "green": ((H >= 40) & (H <= 80) & (S > saturation_thresh)).astype(np.uint8),
    }

    def find_bands(mask):
        row_frac = mask.sum(axis=1) / w
        row_is_highlighted = row_frac > min_row_coverage

        raw_bands = []
        start = None
        for i, flagged in enumerate(row_is_highlighted):
            if flagged and start is None:
                start = i
            elif not flagged and start is not None:
                raw_bands.append([start, i - 1])
                start = None
        if start is not None:
            raw_bands.append([start, len(row_is_highlighted) - 1])

        # merge bands that are only briefly interrupted (e.g. by anti-aliased text)
        merged = []
        for b in raw_bands:
            if merged and b[0] - merged[-1][1] <= max_gap:
                merged[-1][1] = b[1]
            else:
                merged.append(b)
        return merged

    def ocr_price(y1, y2):
        y1p, y2p = max(0, y1 - padding), min(h, y2 + padding + 1)
        crop = img[y1p:y2p, :]
        crop_big = cv2.resize(
            crop, (crop.shape[1] * upscale, crop.shape[0] * upscale),
            interpolation=cv2.INTER_CUBIC,
        )

        config = "--psm 7 -c tessedit_char_whitelist=0123456789.,"
        candidates = [crop_big]
        # Fallback: Otsu-thresholded grayscale version, in case the raw color crop
        # doesn't OCR cleanly for a given color scheme.
        gray = cv2.cvtColor(crop_big, cv2.COLOR_BGR2GRAY)
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        _, th_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        candidates += [th, th_inv]

        price_pattern = re.compile(r"[\d,]+\.\d{2}")
        for cand in candidates:
            text = pytesseract.image_to_string(cand, config=config).strip()
            match = price_pattern.search(text)
            if match:
                return match.group(0)
        return text  # best-effort, may be empty or malformed

    results = []
    for color, mask in masks.items():
        for y1, y2 in find_bands(mask):
            price_text = ocr_price(y1, y2)
            try:
                price = float(price_text.replace(",", ""))
            except ValueError:
                price = None
            results.append({
                "color": color,
                "price_text": price_text,
                "price": price,
                "bbox": (0, y1, w, y2 - y1 + 1),
            })

    results.sort(key=lambda r: r["bbox"][1])
    return results


if __name__ == "__main__":
    import sys
    import json

    path = sys.argv[1] if len(sys.argv) > 1 else "prices.jpg"
    for row in extract_highlighted_prices(path):
        print(json.dumps(row))
