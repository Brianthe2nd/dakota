import cv2
import pytesseract
import numpy as np

# If you are on Windows, point pytesseract to your executable path:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def crop_section2(img):
    height, width, _ = img.shape
    print(f"Original image dimensions: {img.shape}")
    if width > 18:
        cropped_img = img[0:height, (width - 18)//2:(width - 18)//2 + 18]
    return cropped_img


def get_contact_size(img):
    img = crop_section2(img)
    # --- Preprocessing for Tesseract ---
    # 1. Scale up the image (Tesseract needs characters to be at least ~30 pixels tall)
    img_scaled = cv2.resize(img, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

    # 2. Convert to grayscale
    gray = cv2.cvtColor(img_scaled, cv2.COLOR_BGR2GRAY)

    # 3. Apply thresholding to make the text pure black and background pure white
    # Using Otsu's thresholding works well for solid backgrounds
    _, binary_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # --- Run OCR ---
    # --psm 6 tells Tesseract to assume a single uniform block of text
    custom_config = r'--oem 3 --psm 6'
    text = pytesseract.image_to_string(binary_img, config=custom_config)

    print("Extracted Text:\n", text.strip())
    #  remove non-digit characters and convert to float
    size_str = ''.join(filter(lambda c: c.isdigit() or c == '.', text.strip()))
    return int(size_str)