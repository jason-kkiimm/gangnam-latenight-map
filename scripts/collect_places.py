"""강남역 반경 1km 안의 음식점(FD6)과 카페(CE7)를 카카오 로컬 API로 모아 data/places.json에 저장한다.

카카오 카테고리 검색은 한 번에 최대 45개(15개 x 3페이지)까지만 주기 때문에,
사각형 영역을 검색해서 결과가 45개를 넘으면 4등분해서 다시 검색한다.

실행: python scripts/collect_places.py
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

API_URL = "https://dapi.kakao.com/v2/local/search/category.json"
CENTER_LAT, CENTER_LNG = 37.4979, 127.0276  # 강남역
RADIUS_M = 1000
CATEGORIES = {"FD6": "음식점", "CE7": "카페"}
MAX_RESULTS = 45  # 카카오 API가 한 검색에서 돌려줄 수 있는 최대 개수
MIN_CELL_DEG = 0.00005  # 이보다 작으면 더 쪼개지 않는다 (약 5m)
UNKNOWN = "확인 필요"

REST_KEY = os.getenv("KAKAO_REST_KEY")
if not REST_KEY:
    sys.exit("KAKAO_REST_KEY가 .env에 없습니다.")


def distance_m(lat1, lng1, lat2, lng2):
    """두 좌표 사이 거리(m), haversine."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def call_api(params):
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {REST_KEY}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f"인증 오류({e.code}): REST 키와 카카오 로컬 API 사용 설정을 확인하세요.\n{e.read().decode()}")
            if e.code == 429 or e.code >= 500:
                time.sleep(1 + attempt)
                continue
            raise
    raise RuntimeError("API 호출이 계속 실패했습니다.")


def search_rect(code, rect):
    """사각형 영역(rect = 'x1,y1,x2,y2')을 검색. (결과 목록, 전체 개수) 반환."""
    results, total = [], 0
    for page in range(1, 4):
        data = call_api({"category_group_code": code, "rect": rect, "page": page, "size": 15})
        total = data["meta"]["total_count"]
        results.extend(data["documents"])
        if data["meta"]["is_end"]:
            break
        time.sleep(0.05)
    return results, total


def collect(code, west, south, east, north, found, stats):
    rect = f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}"
    docs, total = search_rect(code, rect)
    stats["calls"] += 1
    too_small = (east - west) < MIN_CELL_DEG or (north - south) < MIN_CELL_DEG
    if total > MAX_RESULTS and not too_small:
        mx, my = (west + east) / 2, (south + north) / 2
        for w, s, e, n in [(west, south, mx, my), (mx, south, east, my),
                           (west, my, mx, north), (mx, my, east, north)]:
            collect(code, w, s, e, n, found, stats)
        return
    if total > MAX_RESULTS:
        stats["truncated"] += 1
    for d in docs:
        found[d["id"]] = d


def to_place(d):
    return {
        "id": d["id"],
        "name": d["place_name"],
        "address": d["road_address_name"] or d["address_name"],
        "lat": float(d["y"]),
        "lng": float(d["x"]),
        "category": d["category_name"],
        "kakao_url": d["place_url"],
        "is_24h": UNKNOWN,
        "pet_friendly": UNKNOWN,
    }


def main():
    # 반경 1km 원을 감싸는 사각형
    dlat = RADIUS_M / 111_320
    dlng = RADIUS_M / (111_320 * math.cos(math.radians(CENTER_LAT)))
    box = (CENTER_LNG - dlng, CENTER_LAT - dlat, CENTER_LNG + dlng, CENTER_LAT + dlat)

    found, stats = {}, {"calls": 0, "truncated": 0}
    for code, label in CATEGORIES.items():
        before = len(found)
        collect(code, *box, found, stats)
        print(f"{label}({code}): 사각형 기준 {len(found) - before}개")

    places = [
        to_place(d) for d in found.values()
        if distance_m(CENTER_LAT, CENTER_LNG, float(d["y"]), float(d["x"])) <= RADIUS_M
    ]
    places.sort(key=lambda p: p["name"])

    out = BASE_DIR / "data" / "places.json"
    out.write_text(json.dumps(places, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"API 호출 {stats['calls']}회, 45개 초과로 잘린 영역 {stats['truncated']}곳")
    print(f"반경 {RADIUS_M}m 안 {len(places)}개 저장 -> {out}")


if __name__ == "__main__":
    main()
