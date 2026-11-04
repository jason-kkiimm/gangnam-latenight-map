import json
import logging
import os
import re
import threading
import time
import urllib.error
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

import nearby

BASE_DIR = Path(__file__).resolve().parent  # 실행 위치가 아니라 app.py가 있는 폴더 기준
load_dotenv(BASE_DIR / ".env")

DAILY_LIMIT = 30  # 서버 전체 하루 구글 호출 상한 (plan.md 10-3)
COOLDOWN_SEC = 10  # 같은 사용자 연속 조회 간격
USAGE_FILE = Path(os.getenv("USAGE_FILE") or BASE_DIR / "usage_counter.json")

app = Flask(__name__)

# 위치(lat, lng)는 POST 본문으로 받아 주소(URL)에 남지 않지만, 기본 접속 로그는 꺼 둔다. (plan.md 10-5)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

_lock = threading.Lock()
_last_request = {}  # 사용자(IP) -> 마지막 조회 시각(monotonic). 가게 정보는 담지 않는다.


def places_mode():
    return "real" if (os.getenv("PLACES_MODE") or "fake").strip().lower() == "real" else "fake"


def _today():
    return datetime.now(nearby.KST).strftime("%Y-%m-%d")


def _reserve_call():
    """구글 호출 1건을 센다. 상한이면 None, 아니면 오늘 몇 번째인지 돌려준다.
    파일에는 날짜와 횟수만 적는다(구글 데이터 없음)."""
    with _lock:
        today, count = _today(), 0
        try:
            saved = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
            if saved.get("date") == today:
                count = int(saved.get("count", 0))
        except (OSError, ValueError):
            pass
        if count >= DAILY_LIMIT:
            return None
        USAGE_FILE.write_text(json.dumps({"date": today, "count": count + 1}), encoding="utf-8")
        return count + 1


def _cooldown_left(user):
    with _lock:
        last = _last_request.get(user)
        now = time.monotonic()
        if last is not None and now - last < COOLDOWN_SEC:
            return COOLDOWN_SEC - (now - last)
        _last_request[user] = now
        return 0


def _error_kind(exc):
    """오류 종류만 뽑는다. 키 값이나 응답 본문 전체는 출력하지 않는다."""
    if isinstance(exc, urllib.error.HTTPError):
        status = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            candidate = str((body.get("error") or {}).get("status", ""))
            if re.fullmatch(r"[A-Z_]{3,40}", candidate):  # 예: PERMISSION_DENIED
                status = " " + candidate
        except Exception:
            pass
        return "HTTP %d%s" % (exc.code, status)
    if isinstance(exc, urllib.error.URLError):
        return "연결 오류 (%s)" % type(exc.reason).__name__
    return type(exc).__name__


def _client_id():
    """쿨다운 구분용 사용자 식별. PythonAnywhere는 실제 IP를 X-Real-IP 헤더로 넘긴다.
    https://help.pythonanywhere.com/pages/WebAppClientIPAddresses/"""
    return request.headers.get("X-Real-IP") or request.remote_addr


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


@app.route("/favicon.ico")
def favicon():
    # 브라우저가 기본으로 찾는 주소. SVG 아이콘으로 넘긴다.
    return redirect(url_for("static", filename="favicon.svg"), code=302)


def _is_number(value):
    """JSON 숫자(int/float)만 true. true/false, null, 문자열은 숫자로 보지 않는다."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def round_coord(value):
    """좌표를 소수점 셋째 자리(약 100m 단위)로 줄인다."""
    return round(float(value), 3)


@app.route("/api/nearby", methods=["POST"])
def api_nearby():
    # 좌표는 주소(URL)가 아니라 POST 본문에 담겨 와서 접속 기록에 남지 않는다.
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    place_type = body.get("type", "")
    if not (_is_number(body.get("lat")) and _is_number(body.get("lng"))):
        return _error("lat, lng 값이 필요합니다.", 400)
    try:
        lat, lng = float(body["lat"]), float(body["lng"])
    except OverflowError:  # 아주 큰 정수
        return _error("좌표 범위가 올바르지 않습니다.", 400)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or lat != lat or lng != lng:
        return _error("좌표 범위가 올바르지 않습니다.", 400)
    if not isinstance(place_type, str) or place_type not in nearby.TYPES:
        return _error("type은 restaurant 또는 cafe여야 합니다.", 400)
    lat, lng = round_coord(lat), round_coord(lng)  # 검사 뒤, 서버에서도 한 번 더 줄인다

    wait = _cooldown_left(_client_id())
    if wait > 0:
        return _error("잠시 후 다시 눌러 주세요.", 429, retry_after=round(wait, 1))

    mode = places_mode()
    if mode == "fake":
        raw, now = nearby.fake_search(place_type), nearby.fake_now()
    else:
        key = os.getenv("GOOGLE_PLACES_KEY", "")
        if not key:
            return _error("서버에 GOOGLE_PLACES_KEY가 설정되어 있지 않습니다.", 500)
        used = _reserve_call()
        if used is None:
            return _error("오늘은 조회 한도에 도달했습니다", 429)
        try:
            raw = nearby.google_search(lat, lng, place_type, key)
        except Exception as exc:  # 오류 종류만 터미널에 남기고 키·본문은 출력하지 않는다
            print("\n[진짜 호출] 오늘 호출 %d/%d · 실패: %s\n" % (used, DAILY_LIMIT, _error_kind(exc)), flush=True)
            return _error("구글 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.", 502)
        now =datetime.now(nearby.KST)

    places = nearby.shape_results(raw, lat, lng, now)
    return jsonify({"mode": mode, "count": len(places), "places": places})


def debug_enabled():
    """개발 모드는 FLASK_DEBUG가 1/true/yes/on일 때만 켠다. 없으면 꺼짐."""
    return (os.getenv("FLASK_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    app.run(debug=debug_enabled())
