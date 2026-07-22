# AI Ops Studio

패션 쇼핑몰 **Everyday Market**과 고객 문의를 자동 응대·관찰하는 **AI Ops Console**을 한 저장소에서 실행하는 포트폴리오 프로젝트입니다. 상품 탐색부터 주문 후 클레임까지의 커머스 흐름과 Gemini 답변, Langfuse 프롬프트·트레이스를 함께 확인할 수 있습니다.

## 포함된 애플리케이션

```text
apps/
  demo-store/          고객용 패션 쇼핑몰 (React)
  ops-console/         문의 목록·AI 대화 로그 운영 화면 (React)
services/
  core-api/            Gemini 응대·문의 저장 API (FastAPI)
  mock-commerce-api/   상품·장바구니·주문·배송 API (FastAPI + SQLite)
packages/
  shared-types/        프런트엔드 공용 타입
docs/
  demo-store-prd.md    쇼핑몰 상세 PRD
  langfuse-tracing.md  트레이싱 구조와 검증법
```

## 구현 범위

- 패션 상품 6종과 옵션·재고, 검색·카테고리·정렬·품절 필터
- 상품 상세, 장바구니 수량·쿠폰, 배송지 입력, 서버 가격 재검증
- 테스트 결제 승인, 주문 내역·배송 타임라인, 주문 취소·반품/환불
- Gemini 고객 문의, 동일 문의의 후속 대화, 고객 문의 내역
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

`.env`에 `GEMINI_API_KEY`를 입력합니다. Langfuse를 사용하려면 Japan 리전 프로젝트의 `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 입력하고 `LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com`을 유지합니다.

### 2. Python 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. 각 서버 실행

PowerShell 창을 세 개 열어 각각 실행합니다. Uvicorn 명령은 실행 중인 서버를 점유하므로 한 창에 연달아 입력하지 않습니다.

```powershell
# 창 1: AI/문의 API
cd "D:\Github\AI-Ops-Studio"
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir services/core-api --reload --port 8000
```

```powershell
# 창 2: 쇼핑몰 API
cd "D:\Github\AI-Ops-Studio"
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir services/mock-commerce-api --reload --port 8001
```

```powershell
# 창 3: 고객 쇼핑몰 + 운영자 화면
cd "D:\Github\AI-Ops-Studio"
corepack enable
corepack prepare pnpm@10.14.0 --activate
pnpm install
pnpm dev
```

접속 주소:

- 고객 쇼핑몰: http://localhost:5174
- Ops Console: http://localhost:5173
- AI/문의 API 문서: http://localhost:8000/docs
- 쇼핑몰 API 문서: http://localhost:8001/docs

`http://localhost:8000`과 `http://localhost:8001`은 API 상태와 문서 주소를 JSON으로 보여줍니다. 실제 화면은 5173/5174 포트입니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m ruff check services tests scripts
.\.venv\Scripts\python.exe -m pytest -q
$env:PYTHONPATH="services\mock-commerce-api"
.\.venv\Scripts\python.exe scripts\verify_commerce_flow.py
pnpm typecheck
pnpm build
```

실제 Gemini/Langfuse 트레이스를 한 건 전송하려면:

```powershell
$env:PYTHONPATH="services\core-api"
.\.venv\Scripts\python.exe scripts\verify_langfuse_trace.py
```

상세 트레이스 구조는 `docs/langfuse-tracing.md`, 제품 요구사항과 우선순위는 `docs/demo-store-prd.md`를 참고합니다.

## 데모 데이터와 이미지

상품 데이터는 의류·가방·신발·액세서리로 통일했습니다. 이미지는 무료 사용 가능한 Unsplash 이미지를 원격 URL로 사용하며, 실제 서비스 배포 전에는 자체 촬영 이미지나 CDN 자산으로 교체하는 것을 권장합니다.
