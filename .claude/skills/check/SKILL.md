---
name: check
description: CLAUDE.md의 확인 3종(문법 검사, 가짜 모드 /api/nearby, git status)을 실행하고 표로 보여 준다.
disable-model-invocation: true
---

CLAUDE.md의 "확인 3종"을 순서대로 실행하고 결과를 표로 보여 준다. 구글·카카오 API는 호출하지 않는다. `.env`는 읽지 않는다. 커밋·푸시는 하지 않는다.

1. `python -m py_compile app.py nearby.py` (시스템 python에 패키지가 없으면 `.venv\Scripts\python.exe` 사용)
2. 가짜 모드(`PLACES_MODE=fake`)로 서버를 임시 포트(예: 5077)에 켜고 `/api/nearby`에 **POST + JSON**(`{"lat":37.498,"lng":127.028,"type":"restaurant"}`)으로 `restaurant`와 `cafe`를 각각 요청한다. 요청 사이는 11초 이상 띄운다(10초 쿨다운). 각각 200이고 종류에 맞는 목록이 오는지 본다. (`FAKE_NOW` 기본 22:30 기준: 음식점 2곳, 카페 3곳.) 끝나면 서버를 끈다.
3. `git status` 로 바뀐 파일을 확인한다.

결과는 이 형식의 표로 보여 준다.

| 확인 | 결과 | 내용 |
|---|---|---|
| 1. 문법 검사 | 통과/실패 | |
| 2-a. restaurant | 통과/실패 | 상태 코드, 곳 수 |
| 2-b. cafe | 통과/실패 | 상태 코드, 곳 수 |
| 3. git status | 확인 | 바뀐 파일 목록 |

하나라도 실패하면 "커밋하지 않는다"고 말하고, 원인을 초보자도 알 수 있게 한 줄로 설명한다.
