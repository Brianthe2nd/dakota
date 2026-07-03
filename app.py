from flask import Flask, render_template, jsonify
import json
import os

app = Flask(__name__)
STATE_FILE = "dashboard.json"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    # Return empty template if file isn't ready
    return jsonify({"metrics": {}, "risk": {}, "timer": {"active": False}, "logs": [], "positions": [], "deals": []})

if __name__ == '__main__':
    # Run alongside your main loop in a separate terminal: python app.py
    app.run(debug=True, port=5000)