# AI Ops Studio · 판매자 연동 Discord 봇

판매자가 **자기 Discord 서버에 초대**해서 쓰는 봇입니다. 판매자 플랜에 맞는
채널·웹훅을 자동으로 깔아주고, 슬래시 명령으로 매출·조회수 같은 지표를 즉시
보여줍니다. 실제 AI 리포트 생성·발신은 판매자 노트북이 이 봇이 만든
**웹훅 URL**로 담당합니다(요구사항: "AI 관련은 내 노트북에서").

## 실행 방식 두 가지

같은 기능(`/실행`, `/수익`, `/조회수`, `/일일리포트`, `/재고`, `/연동상태`)을
서로 다른 방식으로 구현한 두 파일이 있습니다 — 하나를 골라서 씁니다.

| | `bot.py` (Gateway) | `interactions_app.py` (HTTP Interactions) |
|---|---|---|
| 연결 방식 | WebSocket을 계속 열어두는 상시 프로세스 | 요청 하나마다 실행되는 일반 HTTP 엔드포인트 |
| 배포 위치 | **Vercel 불가** — Render/Railway나 상시 켜진 PC/서버에서 `python bot.py` | **`api/discord/index.py`로 Vercel에 core-api/commerce-api와 같이 배포됨** (이 프로젝트의 기본값) |
| 서버 참여 환영 메시지 | 있음(`on_guild_join`) | 없음 — Gateway 이벤트라 HTTP 방식엔 대응 개념이 없음. 사이트 콘솔의 3단계 안내가 같은 역할을 함 |
| 필요 크리덴셜 | `DISCORD_BOT_TOKEN` | `DISCORD_BOT_TOKEN` + `DISCORD_PUBLIC_KEY`(서명 검증용, Bot 토큰과 다른 값) |

둘 다 [`discord_rest.py`](discord_rest.py)/[`provisioning.py`](provisioning.py)
(채널·웹훅 생성)와 [`api_client.py`](api_client.py)/[`formatting.py`](formatting.py)
(커머스 API 조회·응답 포맷)의 같은 로직을 쓰므로 동작은 동일합니다.
`bot.py`만 discord.py의 Gateway Client·슬래시 명령 트리를 통해 붙고,
`interactions_app.py`는 discord.py 없이 요청을 직접 받아 같은 로직을 호출합니다.

## 전체 흐름

```
[판매자 콘솔]  ──(1) 연동 코드 발급──▶  organizations.discord_link_code
     │                                        ▲
     │(2) "봇 초대하기"                         │ POST /internal/discord/link
     ▼                                        │  {guild_id, code}
[Discord 서버] ──(3) /실행 코드:<코드>──▶ [이 봇] ┘  → guild_id ↔ org 바인딩
     │                                     (같은 명령 안에서 이어서 진행)
     │
     ▼
[이 봇] ─ GET /internal/discord/org ─▶ 플랜별 채널 스펙(plan_channels)
     │  카테고리·채널 생성 + 채널마다 웹훅 생성
     └─ PUT /internal/discord/channels ─▶ discord_channels(웹훅 URL 저장)
     │
     │(4) /수익 · /조회수 · /일일리포트 · /재고
     ▼
[이 봇] ─ GET /internal/discord/metrics ─▶ 커머스 API가 SQL로 집계한 숫자
```

봇은 DB에 직접 붙지 않습니다. 모든 데이터는 커머스 API의 `/internal/discord/*`
엔드포인트를 통해서만 오가며, 공유 비밀(`DISCORD_BOT_SHARED_SECRET`)을
`X-Internal-Token` 헤더로 실어 인증합니다.

**판매자 계정 하나 = 디스코드 서버 하나로 고정됩니다.** 한 번 연동되면
커머스 API(`POST /internal/discord/link`)가 같은 상점이 다른 서버로
재연동하는 걸 거부합니다(같은 서버로 `/실행`을 다시 돌리는 건 계속 허용 —
채널 재생성 용도). "봇을 초대했는지"는 사이트 판매자 콘솔의 디스코드
연동 탭(연동 완료 배지 + 생성된 채널·웹훅 개수)과 봇의 `/연동상태` 명령
양쪽에서 같은 `organizations.discord_guild_id`/`discord_linked_at` 값을
보고 확인합니다 — 별도로 카운트를 관리하는 곳은 없고, 이 컬럼이 곧 그
기록입니다.

## 플랜 → 채널/페르소나 매핑

매핑의 **단일 진실 공급원**은 커머스 API의
[`app/discord_spec.py`](../mock-commerce-api/app/discord_spec.py)입니다. 봇은
이 매핑을 직접 갖지 않고 `/internal/discord/org` 응답으로 받아 그대로 만듭니다.

| 채널 | 채널 key | 페르소나(Langfuse name) | FREE | BASIC | PRO | BUSINESS |
|------|----------|--------------------------|:----:|:-----:|:---:|:--------:|
| 봇-명령 | `commands` | — (슬래시 명령용) | ✅ | ✅ | ✅ | ✅ |
| 일일-리포트 | `daily` | `daily-seller-report` | ✅ | ✅ | ✅ | ✅ |
| 문의-이관 | `support` | `customer-support-answer` | | ✅ | ✅ | ✅ |
| 월간-리포트 | `monthly` | `commerce-monthly-report` | | | ✅ | ✅ |
| 매출-인사이트 | `insight` | `commerce-insight` | | | | ✅ |

> 관리자 전용 페르소나(`platform-daily-traffic`, `seller-market-share-report`)는
> 판매자에게 노출되면 안 되므로 어떤 판매자 플랜에도 들어가지 않습니다.

## 슬래시 명령

| 명령 | 권한 | 설명 |
|------|------|------|
| `/실행 [코드] [전체초기화:bool]` | 서버 관리 | 아직 연동 전이면 코드로 상점을 연결하고, 이어서(또는 이미 연동돼 있으면 바로) 플랜에 맞는 카테고리·채널·웹훅을 (재)생성 |
| `/수익 [기간:YYYY-MM]` | 누구나 | 이 상점의 월 매출 요약 |
| `/조회수 [날짜:YYYY-MM-DD]` | 누구나 | 오늘(또는 지정일) 상품 조회수 |
| `/일일리포트 [날짜]` | 누구나 | 오늘의 조회·판매·환불·재고 스냅샷 |
| `/재고` | 누구나 | 품절·재고 임박 상품 |
| `/연동상태` | 누구나 | 연동 여부와 생성된 채널 목록 |

### `/실행`의 삭제 범위 (안전장치)

- 기본값은 봇이 관리하는 **`AI OPS STUDIO` 카테고리와 그 하위 채널만** 지우고
  다시 만듭니다. 판매자가 따로 만든 다른 채널은 건드리지 않습니다.
- `전체초기화:true`를 주면 삭제 가능한 **모든** 카테고리/채널을 지워 완전히 새
  서버처럼 재구성합니다(요구사항의 "디스코드 샘플링 서버" 초기화 용도).

### 플랜 게이팅은 지금 꺼져 있음

`app/discord_spec.py`의 `PLAN_GATING_ENABLED = False`로, 지금은 상점의
실제 플랜과 무관하게 **모든 채널(5개)**이 생성됩니다. `PLAN_CHANNELS`
매핑 자체는 그대로 있으니, 실제 배포(플랜 판매) 직전에 그 플래그만 켜면
위 표의 플랜별 차등이 다시 적용됩니다.

## Discord Developer Portal 공통 설정 (두 방식 모두 필요)

1. https://discord.com/developers/applications → New Application
2. **Bot** 탭에서 토큰 발급 → `.env`의 `DISCORD_BOT_TOKEN`. Privileged Intents는
   필요 없음.
3. **General Information**의 Application ID → `DISCORD_APPLICATION_ID`.
4. **OAuth2 > URL Generator**: scopes = `bot` + `applications.commands`,
   Bot Permissions = **Manage Channels · Manage Webhooks · Send Messages**.
   생성된 URL을 `.env`의 `VITE_DISCORD_INVITE_URL`에 넣으면 판매자 콘솔에
   "봇 초대하기" 버튼으로 뜹니다.
5. 슬래시 명령을 **전역으로 등록**(최초 1회, 명령 이름/옵션을 바꿀 때마다 재실행):
   ```powershell
   .venv\Scripts\python.exe services\discord-bot\register_commands.py
   ```
   반영까지 최대 1시간 걸릴 수 있습니다.

## 방법 1: HTTP Interactions (Vercel, 기본값)

추가로 필요한 것: **General Information > Public Key** → `.env`의
`DISCORD_PUBLIC_KEY`.

1. `DATABASE_URL`, `DISCORD_BOT_TOKEN`, `DISCORD_APPLICATION_ID`,
   `DISCORD_PUBLIC_KEY`, `DISCORD_BOT_SHARED_SECRET`을 Vercel 프로젝트
   Environment Variables에 등록(자세한 값 목록은 `DEPLOYMENT.md`).
2. 배포.
3. Developer Portal → **General Information > Interactions Endpoint URL**에
   `https://<배포 도메인>/api/discord` (슬래시 없이) 입력 후 저장 — Discord가
   그 자리에서 PING을 보내 검증하고, 통과해야 저장됩니다. 실패하면 2번의
   배포가 끝났는지 · 위 환경변수가 다 등록됐는지 확인하세요.
4. `curl -s https://<배포 도메인>/api/discord/health` → `{"status":"ok",...}`
   로 응답하면 정상.

## 방법 2: Gateway (로컬/상시 서버)

```powershell
# 1) 봇 전용 가상환경
python -m venv .venv-bot
.\.venv-bot\Scripts\Activate.ps1
pip install -r services/discord-bot/requirements.txt

# 2) .env 채우기(저장소 루트 .env) — 위 공통 설정 값들 +
#    DISCORD_BOT_API_BASE=http://localhost:8001 (배포 시 https://<도메인>/api/commerce)
#    DISCORD_DEV_GUILD_ID=... (선택, 지정 시 슬래시 명령이 그 서버에만 즉시 반영)

# 3) 실행 (커머스 API가 떠 있어야 지표 명령이 동작)
python services/discord-bot/bot.py
```

## 파일 구성

| 파일 | 역할 |
|------|------|
| `bot.py` | 방법 2(Gateway) 본체 · discord.py 슬래시 명령 트리 |
| `interactions_app.py` | 방법 1(HTTP Interactions) 본체 · 서명 검증 · 명령 디스패치 |
| `provisioning.py` | `/실행`의 채널·웹훅 (재)생성 로직(REST, `interactions_app.py` 전용) |
| `discord_rest.py` | httpx 기반 Discord REST 클라이언트(Gateway 없이 채널/웹훅 조작) |
| `register_commands.py` | 전역 슬래시 명령 등록(1회성 스크립트, 둘 다에 필요) |
| `api_client.py` | 커머스 API `/internal/discord/*` 호출(비동기 httpx) |
| `formatting.py` | 지표 dict → Discord 메시지 문자열(순수 함수, 테스트 가능) |
| `requirements.txt` | `bot.py`용 discord.py 포함 전체 의존성 목록(로컬 설치용) |

`interactions_app.py`가 실제로 필요로 하는 패키지(fastapi/httpx/pynacl)는
루트 `pyproject.toml`의 `[project]`에도 있습니다 — Vercel 빌드는 그쪽을 읽고,
이 `requirements.txt`는 `bot.py`를 로컬에서 돌릴 때만 씁니다.
