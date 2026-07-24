# AI Ops Studio

패션 쇼핑몰 **Everyday Market**과 고객 문의를 자동 응대·관찰하는 **AI Ops Console**을 한 저장소에서 실행하는 포트폴리오 프로젝트입니다. 상품 탐색부터 주문 후 클레임까지의 커머스 흐름과 OpenRouter 응답, Langfuse 프롬프트·트레이스를 함께 확인할 수 있습니다.

## 포함된 애플리케이션

```text
apps/
  demo-store/          고객용 패션 쇼핑몰 (React)
  ops-console/         문의 목록·AI 대화 로그 운영 화면 (React)
services/
  core-api/            OpenRouter 응대·문의 저장 API (FastAPI)
  mock-commerce-api/   상품·장바구니·주문·배송 API (FastAPI + SQLite)
packages/
  shared-types/        프런트엔드 공용 타입
docs/
  demo-store-prd.md    쇼핑몰 상세 PRD
  langfuse-tracing.md  트레이싱 구조와 검증법
  langfuse-personas.md 프롬프트 name·config·페르소나 설계
  ai-ops-studio-master-prd.html
                       커머스 AI 비서·요금제 통합 Master PRD
```

`docs/ai-ops-studio-master-prd.html`은 현재 구현과 다음 개발 단계를 함께 정리한
정적 기획 문서입니다. 브라우저에서 직접 열면 문의 자동화, 매출·환불·순이익 분석,
Basic/Pro/Business 요금제, Discord Webhook 알림 설계를 한 번에 볼 수 있습니다.
문서의 로드맵 기능은 구현 완료 항목과 구분되어 있습니다.

## 구현 범위

- 패션 상품 6종과 옵션·재고, 검색·카테고리·정렬·품절 필터
- 상품 상세, 장바구니 수량·쿠폰, 배송지 입력, 서버 가격 재검증
- 테스트 결제 승인, 주문 내역·배송 타임라인, 주문 취소·반품/환불
- OpenRouter 고객 문의, 동일 문의의 후속 대화, 고객 문의 내역
- 문의 상태·에스컬레이션·AI 전체 메시지 로그를 보는 Ops Console
- 자동화 워크플로 활성화·중지와 실행 성공/실패 현황
- AI 지식 문서 등록·게시·보관, 외부 연동 연결 점검
- 실패 작업 재시도와 운영 변경 감사 로그
- Langfuse 원격 프롬프트, trace/session/user 연결, 민감정보 마스킹
- SQLite 영속 저장과 재실행 가능한 패션 데모 시드

결제는 포트폴리오 로컬 실행을 위해 서버에서 모사합니다. 실제 배포 시 PG 웹훅 검증과 인증·인가 강화가 필요합니다.

## 처음 실행

### 1. 환경 변수

```powershell
cd "D:\Github\AI-Ops-Studio"
Copy-Item .env.example .env
```

`.env`에 `OPENROUTER_API_KEY`를 입력합니다. Langfuse를 사용하려면 Japan 리전 프로젝트의 `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 입력하고 `LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com`을 유지합니다. 실제 모델·temperature·max tokens는 Langfuse prompt `config`에서 가져오며 `.env`의 `OPENROUTER_DEFAULT_MODEL`은 Langfuse를 사용할 수 없을 때의 fallback입니다.

`AUTH_SECRET_KEY`(로그인 토큰 서명)는 개발용 기본값이 코드에 있어 비워둬도 실행됩니다. 실제 배포 시에는 반드시 무작위 값으로 교체하세요.

**구글 로그인(선택)**: 비워두면 로그인·회원가입 화면에 "구글 로그인은 설정되면 활성화됩니다" 안내만 표시되고 이메일·비밀번호 로그인은 그대로 동작합니다. 실제로 켜려면:

1. [Google Cloud Console](https://console.cloud.google.com/) → API 및 서비스 → 사용자 인증 정보에서 OAuth 클라이언트 ID(웹 애플리케이션)를 만듭니다.
2. 승인된 자바스크립트 원본에 `http://localhost:5174`(고객 쇼핑몰)를 등록합니다.
3. 발급된 클라이언트 ID를 `.env`의 `GOOGLE_CLIENT_ID`와 `VITE_GOOGLE_CLIENT_ID`에 동일하게 넣습니다.

### 2. Python 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. 서버 실행

```powershell
cd "D:\Github\AI-Ops-Studio"
corepack enable
corepack prepare pnpm@10.14.0 --activate
pnpm install
pnpm dev
```

`pnpm dev` 한 번으로 AI/문의 API(8000), 쇼핑몰 API(8001), 고객 쇼핑몰(5174), Ops Console(5173)이 `concurrently`로 한 창에서 함께 실행되며 `commerce`/`core`/`web` 라벨로 로그가 구분됩니다. `Ctrl+C` 한 번으로 넷 다 같이 종료됩니다. Python 서버는 저장소 루트의 `.venv`를 직접 호출하므로("2. Python 설치"에서 만든 가상환경) 별도 활성화가 필요 없습니다.

각 서버를 따로 확인하거나 로그를 분리하고 싶다면 개별 스크립트도 그대로 사용할 수 있습니다.

```powershell
pnpm dev:core       # AI/문의 API만
pnpm dev:commerce   # 쇼핑몰 API만
pnpm dev:web        # 고객 쇼핑몰 + Ops Console만
```

접속 주소:

- 고객 쇼핑몰: http://localhost:5174
- Ops Console: http://localhost:5173
- AI/문의 API 문서: http://localhost:8000/docs
- 쇼핑몰 API 문서: http://localhost:8001/docs

`http://localhost:8000`과 `http://localhost:8001`은 API 상태와 문서 주소를 JSON으로 보여줍니다. 실제 화면은 5173/5174 포트입니다.

고객 쇼핑몰에는 데모 로그인 계정(`demo@example.com` / `demo1234`)이 시드돼 있습니다. 회원가입 화면에서 "판매자로 시작하기"를 선택하거나, 로그인 후 마이페이지에서 "비즈니스로 가입하기"를 눌러 판매자로 전환할 수 있습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m ruff check services tests scripts
.\.venv\Scripts\python.exe -m pytest -q
$env:PYTHONPATH="services\mock-commerce-api"
.\.venv\Scripts\python.exe scripts\verify_commerce_flow.py
pnpm typecheck
pnpm build
```

실제 OpenRouter/Langfuse 트레이스를 한 건 전송하려면:

```powershell
$env:PYTHONPATH="services\core-api"
.\.venv\Scripts\python.exe scripts\verify_langfuse_trace.py
```

상세 트레이스 구조는 `docs/langfuse-tracing.md`, 페르소나와 config 예시는 `docs/langfuse-personas.md`, 제품 요구사항과 우선순위는 `docs/demo-store-prd.md`를 참고합니다.

## 데모 데이터와 이미지

상품 데이터는 의류·가방·신발·액세서리로 통일했습니다. 이미지는 무료 사용 가능한 Unsplash 이미지를 원격 URL로 사용하며, 실제 서비스 배포 전에는 자체 촬영 이미지나 CDN 자산으로 교체하는 것을 권장합니다.
