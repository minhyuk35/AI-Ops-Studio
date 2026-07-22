# Architecture

```text
Demo Store ──HTTP──> Mock Commerce API
    │                     │
    └── inquiry ──> Core API ──> Gemini API
                       │             │
                       ├──> Langfuse prompt + trace
                       ├──> PostgreSQL / pgvector
                       ├──> Redis worker queue
                       └──> Ops Console
```

## Boundary

- Demo Store: 고객 경험과 테스트 데이터 생성
- Mock Commerce API: 외부 쇼핑몰 시스템 역할
- Core API: 문의 상태와 AI 오케스트레이션의 단일 진실 공급원
- Ops Console: 운영자·상담원 UI
- Langfuse: 프롬프트 배포 버전과 LLM 관측성

## AI request lifecycle

1. 문의와 주문 ID 수신
2. Mock Commerce API에서 주문 스냅샷 조회
3. 관련 정책 검색
4. Langfuse에서 production prompt 조회, 실패 시 fallback 사용
5. Gemini 호출을 Langfuse generation observation으로 기록
6. 신뢰도/위험 규칙에 따라 자동 답변 또는 상담원 이관

## Langfuse trace shape

```text
answer-customer-inquiry (span; one customer turn)
├── retrieve-support-prompt (retriever)
└── generate-support-reply (generation)
```

- Root input/output: 고객 질문과 최종 답변만 기록
- Context: `user_id`, `session_id`, environment, channel tags
- Generation: Gemini model, prompt version link, token usage, interaction ID
- Privacy: export 직전에 이메일, 한국 휴대전화 번호, 카드번호 마스킹
