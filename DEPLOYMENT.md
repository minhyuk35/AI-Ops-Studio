# 배포 가이드 (Vercel) — 왜 상품이 안 떴고, 어떻게 고치는가

## 진단 요약 (증거)

- 프런트엔드(`https://ai-ops-studio-demo-store.vercel.app/`)는 **정상 배포**됨(정적 SPA).
- 그러나 백엔드가 통째로 죽어 있었음:
  - `GET /api/commerce/products` → **404**
  - `GET /api/commerce/health` → **404** (이 엔드포인트는 DB가 전혀 필요 없음)
- Neon DB는 **정상 연결 + 시드 완료**(products 34, categories 3, organizations 6,
  commerce_events 195 등 22개 테이블). **DB는 문제가 아니었다.**

> **핵심:** DB가 필요 없는 `/health`까지 404라는 건, 환경변수(예: `DATABASE_URL`)
> 문제가 아니라 **그 경로에 함수가 아예 매핑되지 않은 라우팅/배포 문제**라는 뜻이다.
> (env 변수 누락이면 함수는 뜨되 실행 중 크래시 → **500**이 나야 한다.)

**원인:** 기존 `vercel.json`이 표준 Vercel 스키마가 아닌 최상위 `services` 키와
`"destination": { "service": ... }` 형태를 사용했다. Vercel이 인식하는 건
`functions` / `rewrites` / `builds` 등이라, 두 FastAPI 서비스가 **서버리스 함수로
배포되지 않았다.** 그래서 프런트만 뜨고 `/api/*`는 전부 404.

## 이 저장소가 적용한 수정

1. `api/commerce/index.py`, `api/core/index.py` — 표준 Vercel Python 진입점.
   각 서비스의 FastAPI 앱을 import해 `/api/commerce`, `/api/core` 아래에 마운트한다
   (마운트가 접두사를 벗겨 실제 라우트로 연결 + 서브앱 lifespan을 전파해 스키마
   초기화까지 실행). 두 서비스 모두 `app` 패키지명을 쓰지만 Vercel에서 각 함수는
   **별도 프로세스·번들**이라 런타임 충돌이 없다.
2. `vercel.json` — 표준 스키마로 교체: `functions.includeFiles`로 각 서비스 폴더를
   번들에 포함, `rewrites`로 `/api/commerce/*`·`/api/core/*`를 함수로, 나머지는
   SPA(`/index.html`)로. `crons`는 유지.
3. `mock-commerce-api`의 CORS를 환경변수(`COMMERCE_CORS_ORIGINS`) 기반으로 전환하고
   기본 허용에 배포 도메인 + `*.vercel.app` 정규식을 추가.

> 로컬 검증 완료: 래퍼가 `/api/commerce/products`(33개)·`/health`·`/categories`를
> 200으로 반환하는 것을 SQLite로 확인. **단, Vercel 상의 최종 라우팅/번들은 실제
> 재배포로 확인해야 한다(아래 검증 절차).**

## Vercel 프로젝트 설정 (대시보드)

이 방식은 **프런트 + 백엔드를 한 프로젝트**에서 같은 도메인으로 서비스한다
(동일 출처라 CORS 불필요). 반드시 아래를 맞춘다:

| 항목 | 값 |
|------|-----|
| **Root Directory** | **저장소 루트(비움)** — ⚠️ `apps/demo-store` 로 돼 있으면 루트로 바꿔야 `vercel.json`과 `/api`가 인식된다 |
| Framework Preset | Other (vercel.json의 build/output 사용) |
| Install Command | `pnpm install --no-frozen-lockfile` (vercel.json에 있음) |
| Build Command | `pnpm -r build` (vercel.json에 있음) |
| Output Directory | `apps/demo-store/dist` (vercel.json에 있음) |
| Node.js Version | 20.x |

## 환경 변수 (Vercel > Settings > Environment Variables)

**프런트(빌드 시 주입, 상대경로):**
```
VITE_COMMERCE_API_URL=/api/commerce
VITE_CORE_API_URL=/api/core
VITE_GOOGLE_CLIENT_ID=<구글 OAuth 클라이언트 ID>        # 구글 로그인 켤 때만
VITE_DISCORD_INVITE_URL=<봇 초대 URL>                   # 판매자 콘솔 "봇 초대" 버튼
```

**백엔드(런타임):**
```
DATABASE_URL=postgresql://.../neondb?sslmode=require   # Neon 연결 문자열
AUTH_SECRET_KEY=<무작위 32자+>
GOOGLE_CLIENT_ID=<VITE_GOOGLE_CLIENT_ID와 동일>
CRON_SECRET=<무작위 16자+>                              # Vercel Cron 검증
OPENROUTER_API_KEY=<...>                                # AI 응대/리포트 켤 때
LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY=<...>         # 트레이싱 켤 때
DISCORD_BOT_SHARED_SECRET=<봇과 동일한 무작위 값>       # 봇 내부 API 인증
DISCORD_BOT_TOKEN=<...>                                 # 디스코드 봇(/api/discord)
DISCORD_APPLICATION_ID=<...>                            # 디스코드 봇
DISCORD_PUBLIC_KEY=<...>                                # 디스코드 봇 서명 검증(Bot 토큰과 다른 값)
# (선택) COMMERCE_CORS_ORIGINS=https://ai-ops-studio-demo-store.vercel.app
```

디스코드 봇은 `api/discord/index.py`로 같이 배포된다 — 자세한 설정(Interactions
Endpoint URL 등록, 슬래시 명령 등록)은 `services/discord-bot/README.md` 참고.

> ⚠️ **`.env` 파일은 절대 커밋/업로드하지 않는다**(`.gitignore`에 있음). 위 값은
> Vercel 대시보드에만 넣는다. Neon 키는 재발급 예정인 테스트용이므로 운영 전
> 반드시 교체한다.

## 재배포 후 검증 (이 순서대로)

```bash
# 1) 백엔드가 살아났는지 (DB 불필요) — 200 + JSON 이어야 함
curl -s https://ai-ops-studio-demo-store.vercel.app/api/commerce/health

# 2) 상품이 나오는지 — JSON 배열(34개 근처)
curl -s https://ai-ops-studio-demo-store.vercel.app/api/commerce/products | head -c 300

# 3) 코어 API
curl -s https://ai-ops-studio-demo-store.vercel.app/api/core/health
```

1번이 여전히 404면 → **Root Directory가 저장소 루트로 바뀌었는지** 먼저 확인.
1번은 200인데 2번이 500이면 → **`DATABASE_URL` 환경변수**를 확인(이때는 진짜 DB
문제). Vercel의 **Functions 로그**에서 스택트레이스를 볼 수 있다.

## 상품 이미지 파일 업로드 (Vercel Blob) 연결하기

기본값은 이미지 URL 직접 붙여넣기다. `BLOB_READ_WRITE_TOKEN` 환경변수가 없으면
`GET /api/commerce/uploads/status`가 `{"enabled": false}`를 반환하고, 판매자
콘솔의 상품 등록/수정 폼에는 "파일 업로드" 버튼 자체가 나타나지 않는다(URL
입력만 가능) — 즉 **토큰 없이도 정상 동작**하며, 아래 절차로 토큰만 추가하면
코드 변경 없이 버튼이 즉시 나타난다.

1. Vercel 대시보드 → 이 프로젝트 → **Storage** 탭 → **Create Database** →
   **Blob** 선택 → 이름 지정 후 생성.
2. 생성된 Blob 스토어를 프로젝트에 **Connect**하면 `BLOB_READ_WRITE_TOKEN`이
   해당 프로젝트의 환경변수에 자동으로 추가된다(Production/Preview/Development
   범위를 원하는 대로 선택).
3. 재배포하면 `POST /api/commerce/sellers/me/uploads`(판매자 인증 필요, JPEG/
   PNG/WEBP/GIF, 4MB 이하)가 파일을 Blob에 업로드하고 공개 URL을 반환한다.
   업로드된 URL은 기존 이미지 URL 필드와 동일하게 쓰인다 — 별도 DB 컬럼/마이그
   레이션 없음.
4. 로컬 개발에서 켜고 싶다면 `.env`(커밋 금지)에 `BLOB_READ_WRITE_TOKEN=...`을
   추가한다(같은 대시보드의 Blob 스토어 → `.env.local` 다운로드 버튼으로 값을
   얻을 수 있다).

> ⚠️ Vercel Blob REST API의 실제 응답 형태는 이 프로젝트에서 토큰이 없어 실제
> 호출로 검증하지 못했다(`services/mock-commerce-api/app/main.py`의
> `_upload_to_vercel_blob` 참고). 토큰 연결 후 상품 등록 화면에서 실제 파일
> 업로드를 한 번 테스트해보는 것을 권장한다 — 헤더 이름이나 응답 스키마가
> 다르면 502(`이미지 업로드에 실패했습니다`)로 나타난다.

## 총관리자·판매자 운영 콘솔 (ops-console)

`apps/ops-console`은 demo-store와 별도의 SPA로, 루트 `vercel.json`의
`buildCommand`가 `pnpm -r build`(전체 워크스페이스 빌드) 후
`cp -r apps/ops-console/dist apps/demo-store/dist/console`로 demo-store의
빌드 출력물 안에 정적 파일을 그대로 얹는 방식으로 같이 배포된다 — 별도
Vercel 프로젝트나 환경 변수 설정이 필요 없다(demo-store 빌드와 같은
`VITE_COMMERCE_API_URL=/api/commerce`/`VITE_CORE_API_URL=/api/core`를
그대로 물려받음). `apps/ops-console/vite.config.ts`의 `base: "/console/"`가
이 서브패스 배포를 위한 설정이다.

배포 후 접속: `https://ai-ops-studio-demo-store.vercel.app/console/`
(판매자/관리자 계정으로 로그인 — 역할에 따라 메뉴가 갈린다. 계정 목록은
`docs/test-accounts.txt` 참고, 이 파일은 gitignore돼 있어 커밋되지 않는다.)

## 구글 로그인 프로덕션 전환

1. Google Cloud Console → 사용자 인증 정보 → 해당 OAuth 클라이언트.
2. **승인된 JavaScript 원본**에 `https://ai-ops-studio-demo-store.vercel.app` 추가
   (기존 `http://localhost:5174` 는 로컬용으로 유지).
3. `VITE_GOOGLE_CLIENT_ID`(프런트)와 `GOOGLE_CLIENT_ID`(백엔드)에 같은 값 설정 후 재배포.

## 플랜 B — 서비스별 별도 프로젝트 (동일출처가 어려울 때)

한 프로젝트 방식이 막히면, 각 서비스를 별도 Vercel 프로젝트로 배포할 수도 있다
(Root Directory를 각각 `services/mock-commerce-api`, `services/core-api`로). 이때는
프런트의 `VITE_*_API_URL`을 각 절대 URL로 바꾸고, 커머스 API의
`COMMERCE_CORS_ORIGINS`에 프런트 도메인을 넣어야 한다(코드는 이미 대비돼 있음).
