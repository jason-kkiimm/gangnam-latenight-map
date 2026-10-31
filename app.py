import json
from pathlib import Path

from flask import Flask, jsonify, render_template

BASE_DIR = Path(__file__).parent
app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/places")
def places():
    with open(BASE_DIR / "data" / "places.json", encoding="utf-8") as f:
        return jsonify(json.load(f))


if __name__ == "__main__":
    app.run(debug=True)
