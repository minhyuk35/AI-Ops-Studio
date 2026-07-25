"""Vercel Python 서버리스 진입점 — 코어 API (core-api, AI 응대·리포트).

동작 방식은 api/commerce/index.py 와 동일하다. services/core-api 의 FastAPI
앱을 import해 `/api/core` 아래에 마운트하므로, 프런트가 부르는
`/api/core/api/v1/inquiries` 는 실제 앱의 `/api/v1/inquiries` 로,
Vercel Cron이 치는 `/api/core/internal/cron/...` 는 `/internal/cron/...` 로
이어진다. 번들 포함은 vercel.json의 includeFiles(services/core-api/**)가 담당.
"""

import pathlib
import sys
from contextlib import asynccontextmanager

_SERVICE_DIR = pathlib.Path(__file__).resolve().parents[2] / "services" / "core-api"
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

from app.main import app as core_app  # noqa: E402
from fastapi import FastAPI  # noqa: E402


# 마운트된 서브앱의 lifespan을 바깥 앱이 뜰 때 함께 실행한다(스케줄러 설정 등).
@asynccontextmanager
async def lifespan(_: FastAPI):
    async with core_app.router.lifespan_context(core_app):
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/api/core", core_app)
