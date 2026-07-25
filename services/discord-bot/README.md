# AI Ops Studio · 판매자 연동 Discord 봇

판매자가 **자기 Discord 서버에 초대**해서 쓰는 독립 실행 봇입니다. 판매자
플랜에 맞는 채널·웹훅을 자동으로 깔아주고, 슬래시 명령으로 매출·조회수 같은
지표를 즉시 보여줍니다. 실제 AI 리포트 생성·발신은 판매자 노트북이 이 봇이
만든 **웹훅 URL**로 담당합니다(요구사항: "AI 관련은 내 노트북에서").

> 이 봇은 저장소 루트의 두 API 서비스(core-api, mock-commerce-api)와 **별개
> 프로세스**입니다. Vercel에 배포되는 대상이 아니라, 판매자/운영자의 PC나 상시
> 켜진 서버에서 `python bot.py`로 돌립니다.

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

## 실행

```powershell
# 1) 봇 전용 가상환경
python -m venv .venv-bot
.\.venv-bot\Scripts\Activate.ps1
pip install -r services/discord-bot/requirements.txt

# 2) .env 채우기 (저장소 루트 .env, 자세한 설명은 .env.example)
#    DISCORD_BOT_TOKEN=...            Developer Portal > Bot > Reset Token
#    DISCORD_APPLICATION_ID=...       Developer Portal > General Information
#    DISCORD_BOT_API_BASE=http://localhost:8001   (배포 시 https://<도메인>/api/commerce)
#    DISCORD_BOT_SHARED_SECRET=...    커머스 API와 동일한 값
#    DISCORD_DEV_GUILD_ID=...         (선택) 지정 시 슬래시 명령 즉시 반영

# 3) 실행 (커머스 API가 떠 있어야 지표 명령이 동작)
python services/discord-bot/bot.py
```

### Discord Developer Portal 설정

1. https://discord.com/developers/applications → New Application
2. **Bot** 탭에서 토큰 발급(`DISCORD_BOT_TOKEN`). Privileged Intents는 필요 없음.
3. **OAuth2 > URL Generator**: scopes = `bot` + `applications.commands`,
   Bot Permissions = **Manage Channels · Manage Webhooks · Send Messages**.
   생성된 URL을 `.env`의 `VITE_DISCORD_INVITE_URL`에 넣으면 판매자 콘솔에
   "봇 초대하기" 버튼으로 뜹니다.

## 파일 구성

| 파일 | 역할 |
|------|------|
| `bot.py` | 봇 본체 · 슬래시 명령 · 채널/웹훅 프로비저닝 |
| `api_client.py` | 커머스 API `/internal/discord/*` 호출(비동기 httpx) |
| `formatting.py` | 지표 dict → Discord 메시지 문자열(순수 함수, 테스트 가능) |
| `requirements.txt` | 봇 전용 의존성(discord.py, httpx, python-dotenv) |
