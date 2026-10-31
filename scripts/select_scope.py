"""구글 영업시간을 조회할 대상 약 900개를 고른다.

대상:
  1) 심야 업종(국밥·해장·설렁탕 등) 카테고리 가게
  2) 술집
  3) 이름에 "24시"/"24h"가 들어간 가게 (보조 기준, 항상 포함)
  4) 위에 해당하지 않는 카페를 강남역에서 가까운 순으로 채워 총 TARGET개를 맞춘다

결과는 data/scope.json에 저장한다. data/places.json은 수정하지 않는다.

실행: python scripts/select_scope.py
"""
import json
import math
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PLACES_PATH = BASE_DIR / "data" / "places.json"
SCOPE_PATH = BASE_DIR / "data" / "scope.json"

CENTER_LAT, CENTER_LNG = 37.4979, 127.0276  # 강남역
TARGET = 900  # 구글 영업시간 조회 무료 한도(월 1,000건) 안에 들도록 맞춘 개수

LATE_NIGHT_KEYWORDS = [
    "국밥", "해장", "설렁탕", "순대", "곰탕", "감자탕",
    "햄버거", "패스트푸드", "분식", "김밥", "치킨",
]
NAME_24H_KEYWORDS = ["24시", "24h"]


def distance_m(lat, lng):
    """강남역까지의 거리(m), haversine."""
    r = 6371000
    p1, p2 = math.radians(CENTER_LAT), math.radians(lat)
    dp, dl = p2 - p1, math.radians(lng - CENTER_LNG)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main():
    places = json.loads(PLACES_PATH.read_text(encoding="utf-8"))

    chosen = {}  # id -> reason (먼저 걸린 기준이 이유가 된다)
    for p in places:
        name = p["name"].lower()
        if any(k in name for k in NAME_24H_KEYWORDS):
            chosen[p["id"]] = "name_24h"
    for p in places:
        if p["id"] not in chosen and any(k in p["category"] for k in LATE_NIGHT_KEYWORDS):
            chosen[p["id"]] = "late_night_category"
    for p in places:
        if p["id"] not in chosen and "술집" in p["category"]:
            chosen[p["id"]] = "bar"

    cafes = sorted(
        (p for p in places if p["id"] not in chosen and "카페" in p["category"]),
        key=lambda p: distance_m(p["lat"], p["lng"]),
    )
    need = max(0, TARGET - len(chosen))
    picked_cafes = cafes[:need]
    for p in picked_cafes:
        chosen[p["id"]] = "cafe_nearest"

    scope = [
        {"id": p["id"], "name": p["name"], "reason": chosen[p["id"]],
         "distance_m": round(distance_m(p["lat"], p["lng"]))}
        for p in places if p["id"] in chosen
    ]
    scope.sort(key=lambda s: s["distance_m"])
    SCOPE_PATH.write_text(json.dumps(scope, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = Counter(s["reason"] for s in scope)
    print(f"전체 {len(places)}개 중 조회 대상 {len(scope)}개 -> {SCOPE_PATH}")
    for reason in ("name_24h", "late_night_category", "bar", "cafe_nearest"):
        print(f"  {reason}: {counts.get(reason, 0)}")
    if picked_cafes:
        print(f"  선택된 카페 중 가장 먼 곳: {distance_m(picked_cafes[-1]['lat'], picked_cafes[-1]['lng']):.0f}m")
    if len(chosen) - len(picked_cafes) > TARGET:
        print(f"주의: 카페를 빼도 {len(chosen)}개로 TARGET({TARGET})을 넘었습니다.")
    if len(cafes) < need:
        print(f"주의: 카페가 모자라 {len(scope)}개만 선택했습니다.")


if __name__ == "__main__":
    main()
