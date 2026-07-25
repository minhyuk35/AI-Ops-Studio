"""Vercel Python 서버리스 진입점 — Discord HTTP Interactions 엔드포인트.

commerce/core는 서브앱을 `/api/commerce`, `/api/core` 아래에 마운트하는
패턴을 쓰지만, 그 방식은 여기선 안 맞는다: Discord Developer Portal에
등록하는 Interactions Endpoint URL은 정확히 하나의 고정 경로(`/api/discord`,
쿼리 파라미터도 하위 경로도 없음)라서, `app.mount("/api/discord", ...)`로
붙이면 슬래시 없이 그 경로에 접근할 때 307 리다이렉트가 발생한다(실측
확인됨) — Discord가 엔드포인트 검증(PING) 요청에서 리다이렉트를 따라가지
않으면 등록 자체가 실패한다. 그래서 마운트 대신 interactions_app의 라우트
함수를 이 앱에 정확히 `/api/discord` 경로로 직접 등록한다.
"""

import pathlib
import sys

_SERVICE_DIR = pathlib.Path(__file__).resolve().parents[2] / "services" / "discord-bot"
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

from fastapi import FastAPI  # noqa: E402
from interactions_app import health, interactions  # noqa: E402

app = FastAPI()
app.add_api_route("/api/discord", interactions, methods=["POST"])
app.add_api_route("/api/discord/health", health, methods=["GET"])
