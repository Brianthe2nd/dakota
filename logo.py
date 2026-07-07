"""
Utility to find a logo in an image using template matching.

Functions
- find_logo_in_image(image_path, template_path='logo.png') -> (float, ((x1,y1),(x2,y2)))

The function performs multi-scale template matching and returns the detected
logo size (as the average of width/height) and the top-left/bottom-right
coordinates as integer tuples.
"""

from typing import Tuple
import os
import math
import json
import cv2
import numpy as np


def find_logo_in_image(image_path: str, template_path: str = "logo.png", *,
					   scales: np.ndarray = None,
					   method = cv2.TM_CCOEFF_NORMED,
					   threshold: float = 0.5) -> Tuple[float, Tuple[Tuple[int,int], Tuple[int,int]]]:
	"""Finds the best match of `template_path` inside `image_path`.

	Returns:
	  logo_size: float — the average of matched width and height (pixels).
	  logo_loc: ((x1,y1),(x2,y2)) — top-left and bottom-right coordinates.

	If no match is found above `threshold`, returns (0.0, ((0,0),(0,0))).
	"""
	if scales is None:
		scales = np.linspace(0.6, 1.6, 41)

	if not os.path.exists(image_path):
		raise FileNotFoundError(f"Image not found: {image_path}")
	if not os.path.exists(template_path):
		raise FileNotFoundError(f"Template not found: {template_path}")

	img_color = cv2.imread(image_path)
	if img_color is None:
		raise ValueError(f"Failed to read image: {image_path}")
	img_gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)

	template_orig = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
	if template_orig is None:
		raise ValueError(f"Failed to read template: {template_path}")

	best_val = -1.0
	best_loc = (0,0)
	best_w = 0
	best_h = 0

	for scale in scales:
		# resize template by scale
		t_h, t_w = template_orig.shape[:2]
		new_w = max(1, int(t_w * scale))
		new_h = max(1, int(t_h * scale))
		resized = cv2.resize(template_orig, (new_w, new_h), interpolation=cv2.INTER_AREA)

		if resized.shape[0] > img_gray.shape[0] or resized.shape[1] > img_gray.shape[1]:
			continue

		res = cv2.matchTemplate(img_gray, resized, method)
		min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
		if method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
			match_val = 1.0 - min_val
			match_loc = min_loc
		else:
			match_val = max_val
			match_loc = max_loc

		if match_val > best_val:
			best_val = match_val
			best_loc = match_loc
			best_w = new_w
			best_h = new_h

	print("Best match value:", best_val)
	if best_val < threshold or best_w == 0 or best_h == 0:
		return 0.0, ((0,0),(0,0))

	x1, y1 = best_loc
	x2, y2 = x1 + best_w, y1 + best_h
	logo_size = float((best_w + best_h) / 2.0)

	# round to one decimal for tidy output
	logo_size = round(logo_size, 1)

	return logo_size, ((int(x1), int(y1)), (int(x2), int(y2)))


def plot_logo_rectangle(image_path: str, logo_loc: Tuple[Tuple[int,int], Tuple[int,int]], 
						output_path: str = None, color: Tuple[int,int,int] = (0, 255, 0), 
						thickness: int = 2) -> np.ndarray:
	"""Draws a rectangle around the detected logo on the image.

	Args:
	  image_path: Path to the image file.
	  logo_loc: ((x1,y1),(x2,y2)) coordinates from find_logo_in_image().
	  output_path: Path to save the annotated image. If None, returns the annotated image.
	  color: BGR color tuple for the rectangle (default: green).
	  thickness: Thickness of the rectangle border in pixels.

	Returns:
	  The annotated image as numpy array.
	"""
	if not os.path.exists(image_path):
		raise FileNotFoundError(f"Image not found: {image_path}")

	img = cv2.imread(image_path)
	if img is None:
		raise ValueError(f"Failed to read image: {image_path}")

	(x1, y1), (x2, y2) = logo_loc
	cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)

	# if output_path:
	# 	cv2.imwrite(output_path, img)
	# 	print(f"Annotated image saved to: {output_path}")

	return img


def save_logo_data_to_config(logo_size: float, logo_loc: Tuple[Tuple[int,int], Tuple[int,int]], 
							  config_path: str = "config.json" , template_path: str = "logo.png") -> None:
	"""Saves logo size and location to config.json."""
	try:
		with open(config_path, 'r') as f:
			config = json.load(f)
	except (FileNotFoundError, json.JSONDecodeError):
		config = {}

	config['logo'] = {
		'use_cached': True,
		'size': logo_size,
		'location': [list(logo_loc[0]), list(logo_loc[1])],
		'template_path': template_path
	}

	with open(config_path, 'w') as f:
		json.dump(config, f, indent=2)


def get_logo_data(image_path: str, template_path: str = "logo.png", 
				   config_path: str = "config.json", threshold: float = 0.4,
				   force_detect: bool = False) -> Tuple[float, Tuple[Tuple[int,int], Tuple[int,int]]]:
	"""Gets logo data: either from cached config or by detecting in the image.

	Args:
	  image_path: Path to the image file.
	  template_path: Path to the template/logo file.
	  config_path: Path to config.json.
	  threshold: Matching threshold for detection.
	  force_detect: If True, always detect fresh (ignore cached values).

	Returns:
	  (logo_size, logo_loc) tuple.
	"""
	# Check if cached data exists
	
	if not force_detect:
		template_path = ""
		try:
			with open(config_path, 'r') as f:
				config = json.load(f)
				logo_config = config.get('logo', {})
				if logo_config.get('use_cached'):
					cached_size = logo_config.get('size')
					cached_loc = logo_config.get('location')
					if cached_size is not None and cached_loc is not None:
						# Convert back to tuple format
						logo_loc = (tuple(cached_loc[0]), tuple(cached_loc[1]))
						print(f"Using cached logo data from {config_path}")
						return cached_size, logo_loc
				if logo_config.get('template_path'):
					template_path = logo_config.get('template_path')
		except (FileNotFoundError, json.JSONDecodeError, KeyError):
			pass

	# Detect fresh
	print(f"Detecting logo in {image_path}...")
	print(f"Using template: {template_path if template_path else 'default logo.png'}")
	size, loc = find_logo_in_image(image_path, template_path, threshold=threshold)
	
	# Save to config
	if loc != ((0, 0), (0, 0)):
		save_logo_data_to_config(size, loc, config_path, template_path)
		print(f"Logo data saved to {config_path}")
	
	return size, loc


if __name__ == "__main__":
	# import sys
	# if len(sys.argv) < 2:
	# 	print("Usage: python logo.py <image_path> [template_path]")
	# 	sys.exit(1)

	# image_path = sys.argv[1]
	# template_path = sys.argv[2] if len(sys.argv) > 2 else "logo.png"
	import os
	images = os.listdir("sample_images")
	for image in images:
		image_path = os.path.join("sample_images", image)
		print(f"\nProcessing image: {image_path}")
		
		template_path = "samples/logo_2.png"
		config_path = "config.json"
		
		# Get logo data (from cache if available, else detect)
		size, loc = get_logo_data(image_path, template_path, config_path, threshold=0.4, force_detect=True)
		print(f"logo_size = {size}")
		print(f"logo_loc = {loc}")
		print("\n")
		# Plot rectangle around the logo
		# if loc != ((0, 0), (0, 0)):
		# 	annotated_img = plot_logo_rectangle(image_path, loc, output_path="frame_with_logo.png", 
		# 										color=(0, 255, 0), thickness=2)
		# 	print("Rectangle plotted and saved!")
		# 	cv2.imshow("Detected Logo", annotated_img)
		# 	cv2.waitKey(0)
		# 	cv2.destroyAllWindows()



