"""가까운 영업 중 가게 조회 로직 (plan.md 10장).

- 구글 Places API (New) Text Search를 부르거나, 가짜 모드에서는 부르지 않고 가짜 가게를 돌려준다.
- 받은 결과는 저장하지 않는다. 이 모듈은 파일·DB에 가게 정보를 쓰지 않는다.
"""
import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어 고정 오프셋으로 충분하다
RADIUS_M = 1000
PAGE_SIZE = 20
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.location",
        "places.formattedAddress",
        "places.googleMapsUri",
        "places.currentOpeningHours",
    ]
)
TYPES = {"restaurant": "음식점", "cafe": "카페"}  # includedType -> textQuery

GANGNAM_STATION = (37.4979, 127.0276)
EARTH_RADIUS_M = 6371000


def haversine_m(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ---------- 영업시간 계산 ----------

def _abs_min(point):
    """구글 요일(0=일요일)·시·분을 '주 시작(일요일 0시)부터 몇 분'으로 바꾼다."""
    return point.get("day", 0) * 1440 + point.get("hour", 0) * 60 + point.get("minute", 0)


def analyze_hours(opening_hours, now):
    """지금 영업 중인 구간을 찾아 마감 시각과 심야 여부를 계산한다.

    심야: 자정을 넘겨 닫는다(영업 구간이 다음 요일로 이어지고 마감이 00:00이 아님).
          정각 00:00 마감은 제외한다. 24시간 영업은 심야로 본다.
    영업시간 정보가 없거나 지금 구간을 못 찾으면 값은 None(확인 필요).
    """
    unknown = {"closes_at": None, "closes_next_day": None, "is_24h": None, "late_night": None}
    periods = (opening_hours or {}).get("periods") or []
    if not periods:
        return unknown

    google_day = (now.weekday() + 1) % 7  # 파이썬 월=0 -> 구글 일=0
    now_min = google_day * 1440 + now.hour * 60 + now.minute

    for p in periods:
        o, c = p.get("open"), p.get("close")
        if not o:
            continue
        if not c:  # 닫는 시각이 없음 = 24시간 영업
            return {"closes_at": None, "closes_next_day": False, "is_24h": True, "late_night": True}
        start, end = _abs_min(o), _abs_min(c)
        if end <= start:
            end += 7 * 1440
        if end - start >= 1440:  # 하루 종일 이어짐 = 24시간
            return {"closes_at": None, "closes_next_day": False, "is_24h": True, "late_night": True}
        if start <= now_min < end or start <= now_min + 7 * 1440 < end:
            close_hm = (c.get("hour", 0), c.get("minute", 0))
            return {
                "closes_at": "%02d:%02d" % close_hm,
                "closes_next_day": c.get("day", 0) != google_day,
                "is_24h": False,
                "late_night": o.get("day", 0) != c.get("day", 0) and close_hm != (0, 0),
            }
    return unknown


# ---------- 가짜 모드 ----------

def _daily_periods(open_hm, close_hm):
    """매일 같은 시간에 열고 닫는 영업 구간 7개."""
    periods = []
    for d in range(7):
        crosses = close_hm <= open_hm
        periods.append(
            {
                "open": {"day": d, "hour": open_hm[0], "minute": open_hm[1]},
                "close": {"day": (d + 1) % 7 if crosses else d, "hour": close_hm[0], "minute": close_hm[1]},
            }
        )
    return periods


def _fake_places():
    gl, gn = GANGNAM_STATION
    items = [
        ("fake-1", "(가짜) 24시간 카페", 0.0010, 0.0, {"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]}),
        ("fake-2", "(가짜) 정각 자정 마감 식당", 0.0, 0.0030, {"periods": _daily_periods((11, 0), (0, 0))}),
        ("fake-3", "(가짜) 새벽 2시 마감 식당", -0.0040, 0.0, {"periods": _daily_periods((18, 0), (2, 0))}),
        ("fake-4", "(가짜) 밤 11시 마감 카페", 0.0, -0.0060, {"periods": _daily_periods((9, 0), (23, 0))}),
        ("fake-5", "(가짜) 밤 11시 30분 마감 식당", 0.0075, 0.0, {"periods": _daily_periods((10, 0), (23, 30))}),
        ("fake-6", "(가짜) 1km 밖 새벽 2시 마감 식당", -0.0120, 0.0, {"periods": _daily_periods((18, 0), (2, 0))}),
    ]
    return [
        {
            "id": pid,
            "displayName": {"text": name},
            "location": {"latitude": gl + dlat, "longitude": gn + dlng},
            "formattedAddress": "서울특별시 강남구 (가짜 주소)",
            "googleMapsUri": "https://www.google.com/maps/search/?api=1&query=%d,%d" % (gl, gn),
            "currentOpeningHours": hours,
        }
        for pid, name, dlat, dlng, hours in items
    ]


def fake_now():
    """가짜 모드의 시각: 오늘 22:30(KST)로 고정. FAKE_NOW=HH:MM으로 바꿀 수 있다."""
    import os

    hh, mm = (os.getenv("FAKE_NOW") or "22:30").split(":")
    return datetime.now(KST).replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)


# ---------- 구글 호출 ----------

def build_search_request(lat, lng, place_type):
    """Text Search (New) 요청 본문. 호출은 하지 않는다."""
    return {
        "textQuery": TYPES[place_type],
        "includedType": place_type,
        "openNow": True,
        "rankPreference": "DISTANCE",
        "pageSize": PAGE_SIZE,
        "languageCode": "ko",
        "locationBias": {
            "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(RADIUS_M)}
        },
    }


def _post_json(url, body, headers, timeout=10):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def google_search(lat, lng, place_type, api_key, post=_post_json):
    """진짜 구글 호출. 하루 상한 확인은 호출하는 쪽(app.py)이 한다."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    data = post(SEARCH_URL, build_search_request(lat, lng, place_type), headers)
    return data.get("places", [])


# ---------- 결과 가공 ----------

def shape_results(raw_places, lat, lng, now):
    """1km 밖 제외, 가까운 순 정렬, 마감·심야 계산. 결과는 저장하지 않고 돌려주기만 한다."""
    out = []
    for p in raw_places:
        loc = p.get("location") or {}
        if "latitude" not in loc or "longitude" not in loc:
            continue
        dist = haversine_m(lat, lng, loc["latitude"], loc["longitude"])
        if dist > RADIUS_M:
            continue
        hours = analyze_hours(p.get("currentOpeningHours"), now)
        out.append(
            {
                "id": p.get("id"),
                "name": (p.get("displayName") or {}).get("text", ""),
                "address": p.get("formattedAddress", ""),
                "lat": loc["latitude"],
                "lng": loc["longitude"],
                "distance_m": round(dist),
                "google_maps_url": p.get("googleMapsUri", ""),
                **hours,
            }
        )
    out.sort(key=lambda x: x["distance_m"])
    return out


def fake_search():
    return _fake_places()
