# 약관 문제로 더 이상 실행하지 않음(2026-11-03)
"""scope.json의 가게를 Google Places API (New)로 조회해 영업시간을 모은다.

1. Text Search(Pro 필드만)로 가게를 찾고, 카카오 이름·좌표와 가까울 때만 같은 가게로 인정한다.
2. 폐업이 아니면 Place Details(regularOpeningHours만)로 영업시간을 받는다.

조회 결과는 data/raw/google_hours.json에 가게별로 저장한다. 다시 실행하면 이미 조회한
가게는 건너뛴다(중복 과금 방지). places.json은 --apply를 줄 때만 고친다.

인자 없이 실행하면 아무것도 조회하지 않는다. 조회는 아래 인자를 줬을 때만 한다.
  python scripts/fetch_google_hours.py --limit 20      # 새로 20개만 시험 조회 (구분별로 고르게)
  python scripts/fetch_google_hours.py --limit 0 --max-calls 2000 --apply   # 전체 조회 + 반영
  python scripts/fetch_google_hours.py --retry no_match   # 매칭 실패 건 다시 조회
  python scripts/fetch_google_hours.py --approve ID...    # 검토 대기 승인 (영업시간 없으면 1건씩 조회)
  python scripts/fetch_google_hours.py --reject ID...     # 검토 대기 거절 (조회 없음)
한 번 실행의 API 호출은 --max-calls(기본 40건)를 넘지 않는다.
"""
import argparse
import difflib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SCOPE_PATH = BASE_DIR / "data" / "scope.json"
PLACES_PATH = BASE_DIR / "data" / "places.json"
CACHE_PATH = BASE_DIR / "data" / "raw" / "google_hours.json"
REVIEW_PATH = BASE_DIR / "data" / "raw" / "review_matches.json"

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{}"
SEARCH_FIELDS = "places.id,places.displayName,places.location,places.businessStatus"
DETAILS_FIELDS = "regularOpeningHours"

# 매칭 등급: 이름 유사도(sim)와 카카오 좌표와의 거리(dist)를 함께 본다.
#  확정  : sim >= 0.8 이고 dist <= 50m          -> 자동 반영
#  검토  : sim >= 0.8 이고 dist <= 150m (확정 제외), 또는 sim >= 0.6 이고 dist <= 50m
#          -> 영업시간은 받아 두되 자동 반영하지 않고 검토 목록(REVIEW_PATH)에 모은다
#  그 외 : 매칭 실패
CONFIRM_SIM, CONFIRM_DIST_M = 0.8, 50
REVIEW_SIM_FAR, REVIEW_DIST_FAR_M = 0.8, 150
REVIEW_SIM_NEAR = 0.6
AUTO_MAX_DIST_M = 10  # 자동 승인: 이 거리 이내이고 이름 차이가 표기 수준일 때만
NEAR_DIST_M = 20  # 이 안이면 유사도와 관계없이 검토 목록

# 한 번 실행에서 보낼 수 있는 API 호출 상한(Text Search + Details). --max-calls로 바꾼다.
DEFAULT_MAX_CALLS = 40
CALLS = {"n": 0}
MAX_ERRORS = 3  # 연속 오류가 이 이상이면 중단 (키/쿼터 문제 가능성)
SEARCH_BIAS_RADIUS_M = 150

# 심야 기준: 이 시각(분) 보다 늦게(다음 날로 넘겨) 닫으면 심야. 0 = 자정 이후.
LATE_NIGHT_AFTER_MIN = 0

UNKNOWN = "확인 필요"
DAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]  # 구글: 0=일요일
KEY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

API_KEY = os.getenv("GOOGLE_PLACES_KEY")


def distance_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# 지점명으로 보고 이름 비교에서 빼는 말 (긴 것부터)
BRANCH_WORDS = [
    "강남역점", "신논현역점", "역삼역점", "교대역점", "강남본점", "강남점", "본점", "직영점",
    "서울", "강남역", "신논현역", "역삼역", "교대역", "강남", "신논현", "역삼", "논현",
]


def normalize(name):
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"[\s·\-_.,&]", "", name).lower()
    for w in BRANCH_WORDS:
        name = name.replace(w, "")
    if len(name) > 2 and name.endswith("점"):
        name = name[:-1]
    return name


def name_similarity(a, b):
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:  # 포함 관계: 짧은 쪽이 긴 쪽의 얼마를 차지하는지 (예향 vs 예향정 = 0.67)
        ratio = max(ratio, min(len(a), len(b)) / max(len(a), len(b)))
    return ratio


def name_differs(a, b):
    """지점명을 뺀 이름이 서로 포함 관계도 아니면 핵심 단어가 다른 것 (스시반주헌 vs 스시산원 반주헌)."""
    na, nb = normalize(a), normalize(b)
    return bool(na and nb) and not (na == nb or na in nb or nb in na)


def grade(dist, sim):
    """'confirmed' / 'review' / None"""
    if sim >= CONFIRM_SIM and dist <= CONFIRM_DIST_M:
        return "confirmed"
    if sim >= REVIEW_SIM_FAR and dist <= REVIEW_DIST_FAR_M:
        return "review"
    if sim >= REVIEW_SIM_NEAR and dist <= CONFIRM_DIST_M:
        return "review"
    if dist <= NEAR_DIST_M:  # 아주 가까우면 표기가 달라도(영문 등) 같은 가게일 수 있다. 자동 승인은 안 함
        return "review"
    return None


def api_call(url, headers, body=None):
    CALLS["n"] += 1
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None


def search_place(place):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": SEARCH_FIELDS,
    }
    body = {
        "textQuery": place["name"],
        "languageCode": "ko",
        "pageSize": 5,
        "locationBias": {
            "circle": {
                "center": {"latitude": place["lat"], "longitude": place["lng"]},
                "radius": float(SEARCH_BIAS_RADIUS_M),
            }
        },
    }
    return api_call(SEARCH_URL, headers, body).get("places", [])


def evaluate_candidates(place, candidates):
    """후보마다 거리·이름 유사도·등급을 계산한다."""
    out = []
    for c in candidates:
        loc = c.get("location") or {}
        if "latitude" not in loc:
            continue
        dist = distance_m(place["lat"], place["lng"], loc["latitude"], loc["longitude"])
        sim = name_similarity(place["name"], c.get("displayName", {}).get("text", ""))
        out.append((c, dist, sim, grade(dist, sim)))
    return out


def pick_match(evaluated):
    """확정 후보 중 가장 가까운 것, 없으면 검토 후보 중 가장 가까운 것."""
    for level in ("confirmed", "review"):
        pool = [e for e in evaluated if e[3] == level]
        if pool:
            return min(pool, key=lambda e: e[1])
    return None


def fetch_hours(place_id):
    headers = {"X-Goog-Api-Key": API_KEY, "X-Goog-FieldMask": DETAILS_FIELDS}
    return api_call(DETAILS_URL.format(place_id) + "?languageCode=ko", headers).get("regularOpeningHours")


def lookup(place):
    """가게 하나를 조회해 캐시에 저장할 dict를 돌려준다."""
    candidates = search_place(place)
    evaluated = evaluate_candidates(place, candidates)
    rec = {
        "kakao_name": place["name"],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidates": [
            {
                "id": c.get("id"),
                "name": c.get("displayName", {}).get("text"),
                "businessStatus": c.get("businessStatus"),
            }
            for c in candidates
        ],
    }
    # 후보별 거리·유사도를 남겨 두면 매칭 실패 원인을 나중에 볼 수 있다
    for cand, (_, d, sm, g) in zip(rec["candidates"], evaluated):
        cand.update(dist_m=round(d), sim=round(sm, 2), grade=g)
    match = pick_match(evaluated)
    if not match:
        rec["status"] = "no_match"
        return rec
    c, dist, sim, level = match
    if level == "confirmed" and name_differs(place["name"], c.get("displayName", {}).get("text", "")):
        rec["name_diff"] = True  # 확정이지만 핵심 단어가 달라 사람이 확인해야 한다
    rec.update(
        google_place_id=c["id"],
        google_name=c.get("displayName", {}).get("text"),
        match_distance_m=round(dist),
        match_similarity=round(sim, 2),
        business_status=c.get("businessStatus"),
        match_grade=level,
    )
    if c.get("businessStatus") not in (None, "OPERATIONAL"):
        rec["status"] = "not_operational"  # 폐업 등: 영업시간은 조회하지 않는다
        return rec
    hours = fetch_hours(c["id"])
    rec["regularOpeningHours"] = hours
    rec["status"] = "ok" if hours and hours.get("periods") else "no_hours"
    if level == "review":
        rec["status"] = "review"  # 사람이 확인하기 전에는 반영하지 않는다
    return rec


# ---------- 영업시간 계산 ----------

def fmt(h, m):
    return f"{h:02d}:{m:02d}"


def split_periods(periods):
    """period를 (개점 요일, 개점 분, 개점 요일 0시 기준 마감 경과 분) 목록으로 바꾼다.

    구글이 24시간을 넘는 period 하나로 주는 경우(예: 일 09:00 ~ 토 21:00)는 하루 단위로 쪼갠다.
    """
    out = []
    for p in periods:
        o, c = p.get("open"), p.get("close")
        if not o or not c:
            continue
        d = o["day"]
        open_min = o.get("hour", 0) * 60 + o.get("minute", 0)
        close_day_min = c.get("hour", 0) * 60 + c.get("minute", 0)
        gap = (c["day"] - d) % 7
        total = gap * 1440 + close_day_min - open_min
        if total <= 1440 and not (gap == 0 and close_day_min <= open_min):
            out.append((d, open_min, gap * 1440 + close_day_min))
            continue
        # 24시간 초과: 개점일은 다음 날 0시까지, 중간 날은 하루 종일, 마지막 날은 0시부터 마감까지
        if gap == 0:  # 같은 요일에 닫는 시각이 더 이르면 일주일 가까이 이어진 것
            gap = 7
        out.append((d, open_min, 1440))
        for k in range(1, gap):
            out.append(((d + k) % 7, 0, 1440))
        if close_day_min > 0:
            out.append(((d + gap) % 7, 0, close_day_min))
    return out


def analyze_hours(hours):
    """regularOpeningHours -> (is_24h, late_night, closes_at)."""
    if not hours or not hours.get("periods"):
        return UNKNOWN, UNKNOWN, None
    periods = hours["periods"]

    # 24시간 영업: 구글은 일요일 0시에 열고 close가 없는 period 하나로 알려준다.
    if len(periods) == 1 and "close" not in periods[0]:
        o = periods[0].get("open", {})
        if o.get("hour", 0) == 0 and o.get("minute", 0) == 0:
            return "예", "예", {k: "24h" for k in KEY_ORDER}

    # 요일별로 가장 늦은 마감을 구한다 (분 단위, 개점 요일 0시 기준 경과 분)
    latest = {}  # day index -> (close_elapsed_min, open_min)
    for d, open_min, close_min in split_periods(periods):
        if d not in latest or close_min > latest[d][0]:
            latest[d] = (close_min, open_min)

    closes = {}
    for i, key in enumerate(DAY_KEYS):
        if i not in latest:
            closes[key] = None  # 쉬는 날
            continue
        close_min, open_min = latest[i]
        if open_min == 0 and close_min >= 1440:
            closes[key] = "24h"  # 0시에 열어 다음 날 0시(이상)까지
        else:
            m = close_min % 1440
            closes[key] = fmt(m // 60, m % 60)
    closes = {k: closes[k] for k in KEY_ORDER}

    all_24h = all(closes[k] == "24h" for k in KEY_ORDER)
    late = any(
        (latest[i][0] > 1440 + LATE_NIGHT_AFTER_MIN) or closes[DAY_KEYS[i]] == "24h"
        for i in latest
    )
    return ("예" if all_24h else "아니오"), ("예" if (all_24h or late) else "아니오"), closes


# ---------- 입출력 ----------

def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


def pick_sample(todo, n):
    """시험용: scope의 reason별로 고르게(균등 간격) n개를 뽑는다."""
    if not todo:
        return []
    groups = {}
    for s in todo:
        groups.setdefault(s["reason"], []).append(s)
    picked, i = [], 0
    names = sorted(groups)
    per = {r: max(1, round(n * len(groups[r]) / len(todo))) for r in names}
    for r in names:
        g = groups[r]
        k = min(per[r], len(g))
        step = len(g) / k
        picked += [g[int(j * step)] for j in range(k)]
    # 반올림 오차 보정
    rest = [s for s in todo if s not in picked]
    while len(picked) < n and rest:
        picked.append(rest.pop(0))
    return picked[:n]


def apply_to_places(cache):
    places = load_json(PLACES_PATH, [])
    changed = 0
    for p in places:
        rec = cache.get(p["id"])
        if not rec:
            continue
        pending = (
            rec["status"] == "rejected"  # 거절된 매칭
            or (rec["status"] == "review" and not rec.get("approved"))  # 검토 대기
            or (rec.get("name_diff") and not rec.get("name_diff_checked"))  # 이름 차이 미확인
        )
        if pending:
            # 사람이 승인하기 전에는 구글 값을 쓰지 않는다 (이전에 반영된 값도 되돌린다)
            p["is_24h"], p["late_night"], p["closes_at"] = UNKNOWN, UNKNOWN, None
            p.pop("google_place_id", None)
            continue
        is_24h, late, closes = analyze_hours(rec.get("regularOpeningHours"))
        p["is_24h"], p["late_night"], p["closes_at"] = is_24h, late, closes
        if rec.get("google_place_id"):
            p["google_place_id"] = rec["google_place_id"]
        changed += 1
    save_json(PLACES_PATH, places)
    return changed


def reclassify_cache(cache):
    """매칭 기준을 바꿨을 때 이미 받은 결과를 API 호출 없이 다시 분류한다."""
    moved = 0
    for rec in cache.values():
        if rec["status"] == "no_match":
            near = [c for c in rec.get("candidates", []) if c.get("dist_m") is not None and c["dist_m"] <= NEAR_DIST_M]
            if near:
                c = min(near, key=lambda c: c["dist_m"])
                rec.update(status="review", google_place_id=c["id"], google_name=c["name"],
                           match_distance_m=c["dist_m"], match_similarity=c["sim"],
                           match_grade="review", needs_hours=True)  # 영업시간은 승인 후에 조회
                moved += 1
            continue
        if rec.get("google_name") is None or rec.get("match_distance_m") is None:
            continue
        if rec["status"] not in ("ok", "no_hours", "review") or rec.get("approved"):
            continue
        sim = name_similarity(rec["kakao_name"], rec["google_name"])
        level = grade(rec["match_distance_m"], sim)
        has = bool(rec.get("regularOpeningHours") and rec["regularOpeningHours"].get("periods"))
        new = "review" if level != "confirmed" else ("ok" if has else "no_hours")
        if level is None:
            new = "review"  # 새 기준으로는 매칭이 약하지만 이미 받은 값이라 검토로 넘긴다
        rec["match_similarity"], rec["match_grade"] = round(sim, 2), level
        if level == "confirmed" and name_differs(rec["kakao_name"], rec["google_name"]) and not rec.get("name_diff_checked"):
            rec["name_diff"] = True
        if rec["status"] != new:
            rec["status"] = new
            moved += 1
    return moved


def write_review_list(scope, cache):
    """사람이 확인할 목록: 검토 대기 매칭 + 영업시간 없음 + 매칭 실패."""
    names = {s["id"]: s for s in scope}
    items = []
    for pid, rec in cache.items():
        flagged = bool(rec.get("name_diff")) and rec["status"] in ("ok", "no_hours")
        if rec["status"] not in ("review", "no_match", "no_hours", "not_operational") and not flagged:
            continue
        if rec["status"] == "review" and rec.get("approved"):
            continue
        is_24h, late, closes = analyze_hours(rec.get("regularOpeningHours"))
        items.append({
            "id": pid,
            "kakao_name": rec["kakao_name"],
            "status": "confirmed_name_diff" if flagged and rec["status"] == "ok" else rec["status"],
            "note": "확정(이름 차이 확인 필요): 이미 반영 대상. 다른 가게면 --reject" if flagged else None,
            "google_name": rec.get("google_name"),
            "dist_m": rec.get("match_distance_m"),
            "similarity": rec.get("match_similarity"),
            "google_place_id": rec.get("google_place_id"),
            "if_approved": {"is_24h": is_24h, "late_night": late, "closes_at": closes}
            if rec["status"] == "review" or flagged else None,
            "other_candidates": [
                f'{c.get("name")} ({c.get("dist_m")}m, 유사도 {c.get("sim")})'
                for c in rec.get("candidates", [])
            ] if rec["status"] == "no_match" else None,
            "scope_reason": names.get(pid, {}).get("reason"),
        })
    order = {"confirmed_name_diff": 0, "review": 0, "no_match": 1, "no_hours": 2, "not_operational": 3}
    items.sort(key=lambda x: order[x["status"]])
    save_json(REVIEW_PATH, items)
    return items


def loose_name(name):
    """띄어쓰기·지점명·기호(&/AND)·까페/카페 차이를 없앤 이름."""
    n = normalize(name).replace("까페", "카페").replace("(주)", "")
    return re.sub(r"and", "", n)


def auto_approve(cache, hold_ids):
    """거리 AUTO_MAX_DIST_M 이내이고 이름이 표기 차이뿐이면 승인한다. API 호출 없음.

    영업시간을 아직 받지 않은 항목(needs_hours)은 승인하려면 호출이 필요해서 건너뛴다.
    돌려주는 값: (승인한 id 목록, {id: 건너뛴 이유})
    """
    approved, skipped = [], {}
    for pid, rec in cache.items():
        flagged = rec.get("name_diff") and rec["status"] in ("ok", "no_hours")
        if not (flagged or (rec["status"] == "review" and not rec.get("approved"))):
            continue
        if pid in hold_ids:
            skipped[pid] = "보류 지정"
        elif rec.get("match_distance_m") is None or rec["match_distance_m"] > AUTO_MAX_DIST_M:
            skipped[pid] = "거리 초과"
        elif loose_name(rec["kakao_name"]) != loose_name(rec.get("google_name") or ""):
            skipped[pid] = "상호명 다름"
        elif rec.get("needs_hours"):
            skipped[pid] = "영업시간 미조회"
        else:
            if flagged:
                rec.pop("name_diff")
                rec["name_diff_checked"] = True
            else:
                rec["approved"] = True
            rec["auto_approved"] = True
            approved.append(pid)
    return approved, skipped


def reject(cache, ids):
    for pid in ids:
        rec = cache.get(pid)
        flagged = rec is not None and rec.get("name_diff") and rec["status"] in ("ok", "no_hours")
        if not rec or (rec["status"] != "review" and not flagged):
            print(f"  ! {pid}: 검토 대기 항목이 아님")
            continue
        rec["status"] = "rejected"  # 다른 가게로 확정. 값은 확인 필요로 남는다
        rec.pop("needs_hours", None)
        print(f"  거절: {rec['kakao_name']} -> {rec.get('google_name')}")


def approve(cache, ids, max_calls):
    for pid in ids:
        rec = cache.get(pid)
        if rec and rec.get("name_diff") and rec["status"] in ("ok", "no_hours"):
            rec.pop("name_diff")  # 이름 차이를 사람이 확인하고 같은 가게로 승인
            rec["name_diff_checked"] = True
            print(f"  승인(이름 차이 확인): {rec['kakao_name']} -> {rec.get('google_name')}")
            continue
        if not rec or rec["status"] != "review":
            print(f"  ! {pid}: 검토 대기 항목이 아님")
            continue
        if rec.get("needs_hours"):
            if CALLS["n"] + 1 > max_calls:
                print(f"  ! {pid}: 호출 상한 때문에 승인 보류")
                continue
            rec["regularOpeningHours"] = fetch_hours(rec["google_place_id"])
            rec.pop("needs_hours")
        rec["approved"] = True
        print(f"  승인: {rec['kakao_name']} -> {rec.get('google_name')}")


def summarize(scope_item, rec):
    is_24h, late, closes = analyze_hours(rec.get("regularOpeningHours"))
    return {
        "name": scope_item["name"],
        "reason": scope_item["reason"],
        "status": rec["status"],
        "google_name": rec.get("google_name"),
        "dist": rec.get("match_distance_m"),
        "sim": rec.get("match_similarity"),
        "is_24h": is_24h,
        "late": late,
        "closes_at": closes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="새로 조회할 개수 (예: 20). 0이면 전체. 주지 않으면 아무것도 조회하지 않는다")
    ap.add_argument("--retry", choices=["no_match"], help="캐시에서 해당 상태의 가게를 지우고 다시 조회")
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS, help="이번 실행의 API 호출 상한")
    ap.add_argument("--approve", nargs="+", metavar="KAKAO_ID", help="검토 대기 매칭을 승인 (영업시간이 없으면 1건만 조회)")
    ap.add_argument("--reject", nargs="+", metavar="KAKAO_ID", help="검토 대기 매칭을 거절 (다른 가게로 처리, 조회 없음)")
    ap.add_argument("--auto-approve", action="store_true", help="거리 10m 이내이고 이름 차이가 표기 수준인 검토 건을 승인 (조회 없음)")
    ap.add_argument("--hold", nargs="+", default=[], metavar="KAKAO_ID", help="--auto-approve에서 제외할 id")
    ap.add_argument("--apply", action="store_true", help="캐시 결과를 places.json에 반영")
    args = ap.parse_args()

    if not API_KEY:
        sys.exit("GOOGLE_PLACES_KEY가 .env에 없습니다.")

    scope = load_json(SCOPE_PATH, [])
    places = {p["id"]: p for p in load_json(PLACES_PATH, [])}
    cache = load_json(CACHE_PATH, {})
    moved = reclassify_cache(cache)
    if moved:
        print(f"기존 결과 {moved}건을 새 기준으로 재분류 (API 호출 없음)")
    retry_ids = []
    if args.retry:
        retry_ids = [k for k, v in cache.items() if v["status"] == args.retry]
        for k in retry_ids:
            del cache[k]
        print(f"재조회 대상 {len(retry_ids)}건 ({args.retry})")
    todo = [s for s in scope if s["id"] not in cache]
    if args.retry:
        todo = [s for s in todo if s["id"] in retry_ids]
    print(f"범위 {len(scope)}개 / 이미 조회 {len(scope) - len(todo)}개 / 남음 {len(todo)}개")

    if args.approve or args.reject or args.auto_approve:
        if args.auto_approve:
            done, skipped = auto_approve(cache, set(args.hold))
            reasons = {}
            for r in skipped.values():
                reasons[r] = reasons.get(r, 0) + 1
            print(f"자동 승인 {len(done)}건 / 확인 필요로 남김 {len(skipped)}건 {reasons}")
        if args.reject:
            reject(cache, args.reject)
        if args.approve:
            approve(cache, args.approve, args.max_calls)
        batch = []
    elif args.limit is None and not args.retry:
        print("조회 인자(--limit N / --retry)가 없어 아무것도 조회하지 않습니다.")
        batch = []
    elif args.retry or args.limit == 0:
        batch = todo
    else:
        batch = pick_sample(todo, args.limit)
    shown, errors = [], 0
    for i, s in enumerate(batch, 1):
        if CALLS["n"] + 2 > args.max_calls:
            print(f"호출 상한({args.max_calls}건)에 닿아 중단합니다. 더 하려면 --max-calls를 올리세요.")
            break
        place = places.get(s["id"])
        if not place:
            print(f"  ! places.json에 없는 id: {s['id']} {s['name']}")
            continue
        try:
            rec = lookup(place)
            errors = 0
        except (RuntimeError, urllib.error.URLError, TimeoutError) as e:
            errors += 1
            print(f"  ! 오류 {s['name']}: {e}")
            if errors >= MAX_ERRORS:
                print("연속 오류가 많아 중단합니다. (지금까지 결과는 저장됨)")
                break
            continue
        cache[s["id"]] = rec
        save_json(CACHE_PATH, cache)  # 매 건 저장: 중간에 끊겨도 이어서 가능
        shown.append(summarize(s, rec))
        if i % 50 == 0:
            print(f"  {i}/{len(batch)}")
        time.sleep(0.05)

    save_json(CACHE_PATH, cache)
    review = write_review_list(scope, cache)
    print(f"\n확인 필요 목록 {len(review)}건 -> {REVIEW_PATH.relative_to(BASE_DIR)}")
    if args.limit or args.retry:
        print(f"\n=== 이번 조회 결과 {len(shown)}건 ===")
        for r in shown:
            print(json.dumps(r, ensure_ascii=False))
    stat = {}
    for r in shown:
        stat[r["status"]] = stat.get(r["status"], 0) + 1
    print("\n이번 실행 상태 집계:", stat)

    print(f"이번 실행 API 호출 {CALLS['n']}건 (상한 {args.max_calls})")

    if args.apply:
        n = apply_to_places(cache)
        print(f"places.json에 {n}개 반영")
    else:
        print("places.json은 건드리지 않았습니다. (--apply로 반영)")


if __name__ == "__main__":
    main()
