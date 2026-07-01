from flask import Flask, request
from flask_cors import CORS
import os
import time

app = Flask(__name__)
# Updated endpoint to match the background script
CORS(app, resources={r"/upload-frame": {"origins": "*"}})

UPLOAD_FOLDER = './received_frames'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/upload-frame', methods=['POST'])
def upload_frame():
    if 'video_chunk' not in request.files:
        return {"status": "error", "message": "No file field"}, 400

    file = request.files['video_chunk']
    if file.filename == '':
        return {"status": "error", "message": "Empty filename"}, 400

    file_content = file.read()
    file_size = len(file_content)

    if file_size < 1000:
        return {"status": "error", "message": "File too small"}, 400

    # Ensure files are ordered cleanly by timestamp
    timestamp_ms = int(time.time() * 1000)
    filename = "frame_yt.jpg"
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    with open(file_path, 'wb') as f:
        f.write(file_content)

    print(f"Saved: {filename} ({file_size} bytes)")
    return {"status": "success"}, 200

if __name__ == '__main__':
    print("Starting JPEG frame receiver on port 5000...")
    app.run(port=5000, debug=True)