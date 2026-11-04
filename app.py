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


def _print_trial_report(used, elapsed_ms, raw, lat, lng, shaped):
    """진짜 호출 시험용 출력. 서버 터미널에만 찍고 파일로 저장하지 않는다."""
    order = {p["id"]: i + 1 for i, p in enumerate(shaped)}
    print("\n[진짜 호출] 오늘 호출 %d/%d · 구글 응답 %d ms · 받은 %d곳, 1km 안 %d곳" % (used, DAILY_LIMIT, elapsed_ms, len(raw), len(shaped)))
    print("  구글순번 | 거리(m) | 서버 정렬 후")
    prev, sorted_same = -1, True
    for i, p in enumerate(raw, 1):
        loc = p.get("location") or {}
        if "latitude" not in loc or "longitude" not in loc:
            print("  %7d | %7s | -" % (i, "?"))
            continue
        d = nearby.haversine_m(lat, lng, loc["latitude"], loc["longitude"])
        if d < prev:
            sorted_same = False
        prev = d
        print("  %7d | %7d | %s" % (i, round(d), order.get(p.get("id"), "제외(1km 밖)")))
    print("  구글 순서가 거리순과 %s\n" % ("같음" if sorted_same else "다름 (서버 재정렬이 필요했음)"), flush=True)


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
        raw, now = nearby.fake_search(place_type), nearby.fake_now()
    else:
        key = os.getenv("GOOGLE_PLACES_KEY", "")
        if not key:
            return _error("서버에 GOOGLE_PLACES_KEY가 설정되어 있지 않습니다.", 500)
        used = _reserve_call()
        if used is None:
            return _error("오늘은 조회 한도에 도달했습니다", 429)
        started = time.monotonic()
        try:
            raw = nearby.google_search(lat, lng, place_type, key)
        except Exception as exc:  # 오류 종류만 터미널에 남기고 키·본문은 출력하지 않는다
            print("\n[진짜 호출] 오늘 호출 %d/%d · 실패: %s\n" % (used, DAILY_LIMIT, _error_kind(exc)), flush=True)
            return _error("구글 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.", 502)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        now = datetime.now(nearby.KST)

    places = nearby.shape_results(raw, lat, lng, now)
    if mode == "real":
        _print_trial_report(used, elapsed_ms, raw, lat, lng, places)
    return jsonify({"mode": mode, "count": len(places), "places": places})


def debug_enabled():
    """개발 모드는 FLASK_DEBUG가 1/true/yes/on일 때만 켠다. 없으면 꺼짐."""
    return (os.getenv("FLASK_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    app.run(debug=debug_enabled())
