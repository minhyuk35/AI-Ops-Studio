"""Vercel Python 서버리스 진입점 — 커머스 API (mock-commerce-api).

Vercel은 `api/**` 의 각 `.py` 파일을 **개별 서버리스 함수**로 배포한다. 이
파일은 services/mock-commerce-api 의 FastAPI 앱을 그 폴더를 sys.path에 얹어
import한 뒤, `/api/commerce` 경로 아래에 마운트한다. 그래서 브라우저가 부르는
`/api/commerce/products` 가 실제 앱의 `/products` 라우트로 이어진다
(마운트가 접두사 `/api/commerce` 를 벗겨준다).

주의: core-api와 commerce-api는 둘 다 `app` 패키지를 갖지만, Vercel에서 각
함수 파일은 별도 프로세스·별도 번들로 돌기 때문에 런타임에서 패키지 이름이
충돌하지 않는다. 번들에 서비스 코드가 반드시 포함되도록 vercel.json의
`functions[...].includeFiles` 로 services/mock-commerce-api/** 를 강제 포함한다.
필요한 환경변수(DATABASE_URL 등)는 Vercel 프로젝트 Environment Variables에
설정한다 — 자세한 내용은 저장소 루트 DEPLOYMENT.md.
"""

import pathlib
import sys
from contextlib import asynccontextmanager

_SERVICE_DIR = pathlib.Path(__file__).resolve().parents[2] / "services" / "mock-commerce-api"
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

from app.main import app as commerce_app  # noqa: E402
from fastapi import FastAPI  # noqa: E402


# 마운트된 서브앱의 lifespan(startup에서 initialize_database 실행)은 바깥 앱이
# 뜰 때 자동으로 돌지 않는다. 서브앱의 lifespan 컨텍스트를 바깥 앱 lifespan에서
# 직접 열어 스키마 생성·시드가 반드시 실행되게 한다.
@asynccontextmanager
async def lifespan(_: FastAPI):
    async with commerce_app.router.lifespan_context(commerce_app):
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/api/commerce", commerce_app)
