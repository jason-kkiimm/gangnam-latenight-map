import json
import logging
import os
import threading
import time
import urllib.error
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import nearby

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

DAILY_LIMIT = 30  # 서버 전체 하루 구글 호출 상한 (plan.md 10-3)
COOLDOWN_SEC = 10  # 같은 사용자 연속 조회 간격
USAGE_FILE = Path(os.getenv("USAGE_FILE") or BASE_DIR / "usage_counter.json")

app = Flask(__name__)

# 요청 주소에 사용자 위치(lat, lng)가 들어가므로 접속 로그에 남기지 않는다. (plan.md 10-5)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

_lock = threading.Lock()
_last_request = {}  # 사용자(IP) -> 마지막 조회 시각(monotonic). 가게 정보는 담지 않는다.


def places_mode():
    return "real" if (os.getenv("PLACES_MODE") or "fake").strip().lower() == "real" else "fake"


def _today():
    return datetime.now(nearby.KST).strftime("%Y-%m-%d")


def _reserve_call():
    """구글 호출 1건을 센다. 상한이면 False. 파일에는 날짜와 횟수만 적는다(구글 데이터 없음)."""
    with _lock:
        today, count = _today(), 0
        try:
            saved = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
            if saved.get("date") == today:
                count = int(saved.get("count", 0))
        except (OSError, ValueError):
            pass
        if count >= DAILY_LIMIT:
            return False
        USAGE_FILE.write_text(json.dumps({"date": today, "count": count + 1}), encoding="utf-8")
        return True


def _cooldown_left(user):
    with _lock:
        last = _last_request.get(user)
        now = time.monotonic()
        if last is not None and now - last < COOLDOWN_SEC:
            return COOLDOWN_SEC - (now - last)
        _last_request[user] = now
        return 0


def _error(message, status, **extra):
    return jsonify({"error": message, **extra}), status


@app.route("/")
def index():
    # 브라우저에는 지도용 브라우저 키만 보낸다. 서버 키(GOOGLE_PLACES_KEY)는 보내지 않는다.
    return render_template(
        "index.html",
        maps_key=os.getenv("GOOGLE_MAPS_BROWSER_KEY", ""),
        mode=places_mode(),
        station={"lat": nearby.GANGNAM_STATION[0], "lng": nearby.GANGNAM_STATION[1]},
        cooldown=COOLDOWN_SEC,
    )


@app.route("/api/nearby")
def api_nearby():
    place_type = request.args.get("type", "")
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
    except (KeyError, ValueError):
        return _error("lat, lng 값이 필요합니다.", 400)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or lat != lat or lng != lng:
        return _error("좌표 범위가 올바르지 않습니다.", 400)
    if place_type not in nearby.TYPES:
        return _error("type은 restaurant 또는 cafe여야 합니다.", 400)

    wait = _cooldown_left(request.remote_addr)
    if wait > 0:
        return _error("잠시 후 다시 눌러 주세요.", 429, retry_after=round(wait, 1))

    mode = places_mode()
    if mode == "fake":
        raw, now = nearby.fake_search(), nearby.fake_now()
    else:
        key = os.getenv("GOOGLE_PLACES_KEY", "")
        if not key:
            return _error("서버에 GOOGLE_PLACES_KEY가 설정되어 있지 않습니다.", 500)
        if not _reserve_call():
            return _error("오늘은 조회 한도에 도달했습니다", 429)
        try:
            raw = nearby.google_search(lat, lng, place_type, key)
        except (urllib.error.URLError, TimeoutError, ValueError):
            return _error("구글 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.", 502)
        now = datetime.now(nearby.KST)

    places = nearby.shape_results(raw, lat, lng, now)
    return jsonify({"mode": mode, "count": len(places), "places": places})


if __name__ == "__main__":
    app.run(debug=True)
