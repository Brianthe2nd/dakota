import json
import cv2

def find_camera_box():
    # face_box = (fx1, fy1, fx2, fy2)
    face_1 = (0,807,526,1080)
    face_2 = (807,526,1492,1080)
    face_3 = (1492,807,1920,1080)

    with open("config.json","r") as file:
        config = json.load(file)
    
    faces = []
    face = config.get("faces",1)
    if face == 1:
        faces.append(face_1)
    elif face == 2:
        faces.append(face_1)
        faces.append(face_3)
    elif face == 3:
        faces.append(face_1)
        faces.append(face_2)
        faces.append(face_3)
    
    return faces


def plot_face_boxes(image, face_boxes=None, color=(0, 255, 0), thickness=2):
    """Draw rectangles for face boxes on the given image.

    Args:
        image: Input image as a NumPy array (e.g. from cv2.imread).
        face_boxes: List of face boxes in (x1, y1, x2, y2) format.
            If None, uses find_camera_box().
        color: BGR color tuple for the rectangle outline.
        thickness: Thickness of the rectangle border in pixels.

    Returns:
        Annotated image as a NumPy array.
    """
    if face_boxes is None:
        face_boxes = find_camera_box()

    annotated = image.copy()
    for (x1, y1, x2, y2) in face_boxes:
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)

    return annotated


if __name__ == "__main__":
    # Example usage
    image_path = "frame.png"  # Replace with your image path
    image = cv2.imread(image_path)
    if image is None:
        print(f"Error: Could not read image at {image_path}")
    else:
        annotated_image = plot_face_boxes(image)
        cv2.imshow("Annotated Image", annotated_image)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        cv2.imwrite("annotated_frame.png", annotated_image)  # Save the annotated image