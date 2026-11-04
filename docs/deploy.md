# PythonAnywhere(무료) 배포 순서 — 왕초보용

> 이 문서에는 키 값을 절대 적지 않는다. 키 "이름"만 적는다.
> 아래 `내아이디`는 PythonAnywhere 가입 아이디로 바꿔 읽는다.

## 0. 먼저 알아둘 것

- 무료 계정은 주소가 `https://내아이디.pythonanywhere.com` 하나이고, 웹앱도 1개만 만들 수 있다.
- 처음에는 반드시 `PLACES_MODE=fake`로 올려서 화면이 뜨는지만 본다. 구글 호출(real)은 그다음에, 승인한 뒤에만 켠다.
- 무료 계정은 **밖으로 나가는 인터넷이 허용 목록(화이트리스트) 사이트로만 제한**된다. 구글 Places 주소(`places.googleapis.com`)가 허용되는지는 **아직 확인하지 못했다.** real 모드로 바꾸기 전에 PythonAnywhere 도움말의 허용 목록을 확인하자. (fake 모드는 인터넷 호출이 없어서 상관없다.)
- 3개월 동안 사이트를 안 열어 보면 무료 웹앱이 멈출 수 있다. Web 탭의 연장 버튼을 눌러 준다.

## 1. 코드 내려받기 (git clone)

PythonAnywhere 상단 **Consoles → Bash**를 열고:

```bash
git clone https://github.com/jason-kkiimm/gangnam-latenight-map
cd gangnam-latenight-map
```

저장소가 비공개라면 비밀번호 대신 토큰이 필요하다. 어려우면 저장소를 잠깐 공개로 바꾸거나, 물어보자.

## 2. 가상환경 만들고 패키지 설치

Web 탭에서 고를 Python 버전과 **같은 버전**으로 만든다. 아래는 3.13 예시(3.10~3.13 중 하나).

```bash
mkvirtualenv --python=/usr/bin/python3.13 latenight
pip install -r requirements.txt
```

- 프롬프트 앞에 `(latenight)`가 보이면 가상환경 안이다. 새 콘솔에서 다시 들어가려면 `workon latenight`.
- `requirements.txt`의 `waitress`는 내 컴퓨터용 서버라서 PythonAnywhere에서는 쓰지 않는다. 같이 설치돼도 문제없다.
- 확인한 것: Flask 3.1.3, python-dotenv 1.2.4, waitress 3.0.2 등 모든 패키지가 Python 3.10·3.11·3.12·3.13용으로 설치 가능하다(2026-11-04, pip 사전 점검).

## 3. `.env` 파일 만들기

`.env`는 깃에 올라가지 않으니 서버에서 직접 만든다.

```bash
cd ~/gangnam-latenight-map
nano .env
```

처음에는 이것만 적는다 (값은 따로 적지 않는다):

```
PLACES_MODE=fake
```

나중에 real 모드를 쓸 때 필요한 키 **이름**:

- `GOOGLE_PLACES_KEY` — 서버 키(구글 Places). 브라우저로 보내지 않는다.
- `GOOGLE_MAPS_BROWSER_KEY` — 브라우저 지도용 키. 구글 콘솔에서 사이트 주소 제한에 `내아이디.pythonanywhere.com`을 **추가**해야 지도가 뜬다.

`FLASK_DEBUG`는 서버에 넣지 않는다(꺼짐이 기본). 저장은 nano에서 `Ctrl+O` → Enter → `Ctrl+X`.

## 4. Web 탭 설정 (Manual configuration)

1. 상단 **Web** → **Add a new web app**
2. 도메인 확인 → Next
3. **Manual configuration** 선택 (Flask 아님! 직접 설정)
4. Python 버전은 2단계에서 가상환경을 만든 버전과 같게 → Next
5. 만들어진 페이지에서 아래를 채운다.

| 항목 | 값 |
|---|---|
| Source code | `/home/내아이디/gangnam-latenight-map` |
| Working directory | `/home/내아이디/gangnam-latenight-map` |
| Virtualenv | `/home/내아이디/.virtualenvs/latenight` |

6. **Static files**에 한 줄 추가한다 (선택이지만 권장, 화면이 빨라진다).

| URL | Directory |
|---|---|
| `/static/` | `/home/내아이디/gangnam-latenight-map/static` |

## 5. WSGI 파일 고치기

Web 탭의 **WSGI configuration file** 링크(`/var/www/내아이디_pythonanywhere_com_wsgi.py`)를 눌러 **내용을 전부 지우고** 아래로 바꾼다.

```python
import sys

path = "/home/내아이디/gangnam-latenight-map"
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application  # noqa
```

`내아이디`를 실제 아이디로 바꾸고 **Save**. 우리 앱은 `app.py` 안의 `app`이라서 `application`이라는 이름으로 가져온다.

`.env`와 `usage_counter.json`은 `app.py`가 있는 폴더를 기준으로 찾기 때문에, WSGI에서 따로 경로를 알려 줄 필요가 없다.

## 6. Reload 하고 확인

1. Web 탭 맨 위 초록색 **Reload** 버튼을 누른다. (코드나 `.env`를 바꿀 때마다 다시 누른다.)
2. `https://내아이디.pythonanywhere.com` 을 열어 지도와 안내 문구가 보이는지 본다.
3. 오류가 나면 Web 탭 아래쪽 **Error log**를 연다. 키 값이 로그에 나오지 않게 조심하자.

## 7. 코드를 고친 뒤 다시 올릴 때

내 컴퓨터에서 커밋·푸시한 뒤, PythonAnywhere Bash에서:

```bash
cd ~/gangnam-latenight-map
git pull
```

그다음 Web 탭에서 **Reload**.

## 8. real 모드로 바꾸기 전 체크 (사용자 승인 후)

- [ ] 허용 목록에 구글 Places 주소가 있는지 확인 (0번 참고)
- [ ] `.env`에 `GOOGLE_PLACES_KEY`, `GOOGLE_MAPS_BROWSER_KEY` 입력, `PLACES_MODE=real`
- [ ] 구글 브라우저 키 제한에 `내아이디.pythonanywhere.com` 추가
- [ ] 하루 호출 상한(`DAILY_LIMIT = 30`)과 예산 알림 확인
- [ ] Reload 후 호출 1건으로 시험
