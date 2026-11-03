# gangnam-latenight-map

강남역 근처에서 **지금 영업 중인 음식점·카페**를 가까운 순으로 보여주고, 오늘 마감 시각과 심야(자정을 넘겨 닫는 곳) 여부를 알려주는 웹 서비스입니다. 구글 Places API (New)를 실시간으로 조회하며 가게 정보는 저장하지 않습니다. 설계는 `docs/plan.md` 10장을 봅니다.

## 실행 방법

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

브라우저에서 http://127.0.0.1:5000 을 엽니다.

## 모드

`.env`의 `PLACES_MODE`로 정합니다. **기본값은 `fake`** 이고 이때는 구글을 호출하지 않고 가짜 가게 6개를 돌려줍니다. 진짜 조회는 `PLACES_MODE=real`로 바꾸고 `GOOGLE_PLACES_KEY`를 넣어야 합니다. 지도는 `GOOGLE_MAPS_BROWSER_KEY`가 있을 때만 뜨고, 없으면 목록만 보입니다.

진짜 모드의 안전장치: 서버 전체 하루 30건 상한, 같은 사용자 10초 쿨다운. 호출 횟수만 `usage_counter.json`에 세고 구글 데이터는 저장하지 않습니다.
