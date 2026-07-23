# Langfuse tracing

## Trace contract

One customer message is one trace. Multi-turn messages share a `session_id`.

```text
answer-customer-inquiry (span)
├── retrieve-support-prompt (retriever)
└── generate-support-reply (generation)
```

Stable observation names are intentional because dashboards and evaluators may depend on them.

## Captured fields

- Root input/output: customer question and final answer
- Context: `user_id`, `session_id`, environment, feature/channel tags
- Metadata: request ID, organization ID, order ID
- Generation: OpenRouter가 실제 사용한 모델, 연결된 Langfuse prompt name/version
- Usage/cost: OpenRouter가 모든 응답에 자동 포함하는 usage accounting을 Langfuse OpenAI wrapper로 수집
- Privacy: emails, Korean mobile numbers and card-like numbers are masked before export

## Live verification

After filling `.env`, create one real trace:

```powershell
cd "D:\AI Ops Studio"
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="services/core-api"
python scripts/verify_langfuse_trace.py
```

Then open the Japan project in Langfuse and inspect the trace named
`answer-customer-inquiry`. Confirm the observation hierarchy, token usage,
prompt version link, session, environment and masking.

프롬프트의 `config.model`을 바꾼 새 버전에 `production` 라벨을 지정하면 재빌드 없이
모델을 전환할 수 있습니다. 기본 캐시 TTL은 300초이므로 즉시 검증할 때는
`LANGFUSE_PROMPT_CACHE_TTL_SECONDS=0`을 임시로 사용하거나 TTL 만료를 기다립니다.
