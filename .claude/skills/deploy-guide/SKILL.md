---
name: deploy-guide
description: 최신 커밋 번호를 확인하고 PythonAnywhere에서 입력할 git pull 명령어와 Reload, 메뉴 확인 순서를 안내한다. 직접 배포하지 않는다.
disable-model-invocation: true
---

PythonAnywhere 배포 순서를 **안내만** 한다. 서버에 접속하거나 직접 배포하지 않는다. 구글·카카오 API는 호출하지 않는다. `.env`는 읽지 않는다.

1. 로컬에서 `git log --oneline -1`, `git status -sb`, `git fetch` 후 `git rev-parse HEAD origin/main` 으로 확인한다.
   - 커밋하지 않은 변경이나 푸시하지 않은 커밋이 있으면 "아직 깃허브에 없어서 서버에 반영되지 않는다"고 먼저 알리고, 푸시 여부를 사용자에게 묻는다.
2. 배포할 커밋 번호(짧은 해시와 제목)를 알려 준다.
3. 사용자가 PythonAnywhere에서 입력할 순서를 안내한다.
   1. **Consoles → Bash**를 연다.
   2. 아래를 입력한다.
      ```bash
      cd ~/gangnam-latenight-map
      git pull
      git log --oneline -1
      ```
   3. 마지막 줄의 커밋 번호가 위 1~2에서 알려 준 번호와 같은지 본다.
   4. `requirements.txt`가 바뀐 커밋이면 `workon latenight` 후 `pip install -r requirements.txt`도 입력한다. (바뀌었는지는 `git diff --name-only 이전커밋 새커밋`으로 확인해 알려 준다.)
   5. **Web** 탭 맨 위 초록색 **Reload**를 누른다.
4. 확인 순서를 안내한다.
   1. `https://내아이디.pythonanywhere.com`을 열고 새로고침(Ctrl+F5)한다.
   2. 이번 커밋에서 바뀐 화면·메뉴가 보이는지 확인한다. (바뀐 내용은 `git show --stat`으로 파악해 한두 줄로 알려 준다.)
   3. 음식점과 카페를 각각 한 번씩 눌러 목록이 나오는지 본다. 진짜 모드는 호출 수가 늘어나므로 꼭 필요한 만큼만 누르게 한다.
5. 안 되면 Web 탭의 **Error log**를 보게 하고, 키 값은 붙여넣지 말라고 알려 준다.
