import argparse
import os

import cv2


def extract_frame(video_path, timestamp, output_path=None):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        raise ValueError("Could not determine FPS for video")

    frame_number = int(round(timestamp * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise ValueError(f"Could not read frame at {timestamp}s (frame {frame_number})")

    if output_path is None:
        base, _ = os.path.splitext(video_path)
        output_path = f"{base}_{timestamp:.2f}.png"

    cv2.imwrite(output_path, frame)
    return output_path


def main():
    # parser = argparse.ArgumentParser(description="Extract a frame from a video at 6.35 seconds")
    # parser.add_argument("video", help="Path to the input video file")
    # parser.add_argument("--time", type=float, default=6.35, help="Timestamp in seconds to extract the frame")
    # parser.add_argument("--output", help="Output image file path")
    # args = parser.parse_args()
    video = "dakota.mp4"
    output = "frame_2.png"
    time = 11 * 60 
    output_path = extract_frame(video, time, output)
    print(output_path)


if __name__ == "__main__":
    main()
