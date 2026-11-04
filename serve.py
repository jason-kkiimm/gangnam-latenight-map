"""운영용 서버 실행: python serve.py
waitress는 Windows·Linux 모두에서 돌아가는 순수 파이썬 운영용 서버다.
HOST(기본 127.0.0.1), PORT(기본 8000)를 환경변수로 바꿀 수 있다."""
import os

from waitress import serve

from app import app

if __name__ == "__main__":
    host = os.getenv("HOST") or "127.0.0.1"
    port = int(os.getenv("PORT") or 8000)
    print("waitress 서버 시작: http://%s:%d" % (host, port), flush=True)
    serve(app, host=host, port=port)
